"""Constitutional Risk Layer — centralized immutable portfolio laws.

Loads config/constitution.yaml and exposes check functions.
ConstitutionalViolation is raised for hard boolean rule failures.
Check functions return lists of violation/warning strings for soft limits.

IMPORTANT: This module is diagnostic only. It never modifies portfolio state.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path


_CONSTITUTION_PATH = Path(__file__).parent.parent.parent / "config" / "constitution.yaml"

_HARD_BOOLEANS = [
    "NO_LEVERAGE",
    "NO_SHORT_SELLING",
    "NO_AUTONOMOUS_EXECUTION",
    "HUMAN_APPROVAL_REQUIRED",
    "NO_LIVE_PNL_LEARNING",
    "NO_BROKER_INTEGRATION",
    "NO_SELF_MODIFYING_RISK_RULES",
]


class ConstitutionalViolation(Exception):
    """Raised when a hard constitutional rule is breached."""


@dataclass
class ConstitutionalReport:
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return len(self.violations) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def load_constitution(path: Path | None = None) -> dict:
    """Load and validate constitution.yaml. Raises on missing hard booleans."""
    p = path or _CONSTITUTION_PATH
    if not p.exists():
        raise FileNotFoundError(f"Constitution file not found: {p}")
    with open(p) as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        raise ValueError("Constitution file is empty.")
    _validate_hard_booleans(cfg)
    return cfg


def _validate_hard_booleans(cfg: dict) -> None:
    """Raise ConstitutionalViolation if any hard prohibition is not True."""
    for key in _HARD_BOOLEANS:
        if key not in cfg:
            raise ConstitutionalViolation(
                f"Missing hard prohibition in constitution: {key}"
            )
        if cfg[key] is not True:
            raise ConstitutionalViolation(
                f"Constitutional violation: {key} must be True, got {cfg[key]!r}. "
                f"This is an immutable hard rule — it cannot be disabled."
            )


def check_position_concentration(
    position_weights: dict[str, float],
    constitution: dict | None = None,
) -> list[str]:
    """Return violation strings for any position exceeding MAX_SINGLE_POSITION.

    position_weights: {ticker: fraction_of_portfolio, ...}
    Empty list = compliant.
    """
    cfg = constitution or load_constitution()
    limit = float(cfg.get("MAX_SINGLE_POSITION", 0.10))
    return [
        f"Position concentration: {ticker} = {w:.1%} exceeds limit {limit:.1%}"
        for ticker, w in position_weights.items()
        if w > limit
    ]


def check_theme_concentration(
    theme_weights: dict[str, float],
    constitution: dict | None = None,
) -> list[str]:
    """Return violation strings for any theme exceeding MAX_SINGLE_THEME_EXPOSURE.

    theme_weights: {theme_name: fraction_of_portfolio, ...}
    """
    cfg = constitution or load_constitution()
    limit = float(cfg.get("MAX_SINGLE_THEME_EXPOSURE", 0.25))
    return [
        f"Theme concentration: {theme} = {w:.1%} exceeds limit {limit:.1%}"
        for theme, w in theme_weights.items()
        if w > limit
    ]


def check_factor_concentration(
    factor_weights: dict[str, float],
    constitution: dict | None = None,
) -> list[str]:
    """Return violation strings for any factor exceeding MAX_SINGLE_FACTOR_EXPOSURE."""
    cfg = constitution or load_constitution()
    limit = float(cfg.get("MAX_SINGLE_FACTOR_EXPOSURE", 0.40))
    return [
        f"Factor concentration: {factor} = {w:.1%} exceeds limit {limit:.1%}"
        for factor, w in factor_weights.items()
        if w > limit
    ]


def check_confidence_quality(
    confidence_counts: dict[str, int],
    constitution: dict | None = None,
) -> list[str]:
    """Return warning strings if LOW/BROKEN fraction exceeds WARN_CONFIDENCE_LOW_FRACTION."""
    cfg = constitution or load_constitution()
    warn_frac = float(cfg.get("WARN_CONFIDENCE_LOW_FRACTION", 0.50))
    total = sum(confidence_counts.values())
    if total == 0:
        return []
    low_broken = confidence_counts.get("LOW", 0) + confidence_counts.get("BROKEN", 0)
    frac = low_broken / total
    if frac > warn_frac:
        return [
            f"Confidence quality: {frac:.1%} of positions are LOW/BROKEN "
            f"(warn threshold: {warn_frac:.1%})"
        ]
    return []


def check_satellite_capital(
    low_confidence_fraction: float,
    constitution: dict | None = None,
) -> list[str]:
    """Return violation strings if LOW-confidence fraction exceeds MAX_SATELLITE_CAPITAL."""
    cfg = constitution or load_constitution()
    limit = float(cfg.get("MAX_SATELLITE_CAPITAL", 0.30))
    if low_confidence_fraction > limit:
        return [
            f"Satellite capital: {low_confidence_fraction:.1%} of book is LOW/BROKEN confidence "
            f"(limit: {limit:.1%})"
        ]
    return []


def run_all_checks(
    position_weights: dict[str, float],
    theme_weights: dict[str, float],
    factor_weights: dict[str, float],
    confidence_counts: dict[str, int],
    path: Path | None = None,
) -> ConstitutionalReport:
    """Run all constitutional checks. Never raises — violations accumulate in report.

    Hard boolean failures (NO_LEVERAGE etc.) are enforced inside load_constitution().
    """
    cfg = load_constitution(path)
    report = ConstitutionalReport()

    report.violations.extend(check_position_concentration(position_weights, cfg))
    report.violations.extend(check_theme_concentration(theme_weights, cfg))
    report.violations.extend(check_factor_concentration(factor_weights, cfg))

    total = sum(confidence_counts.values())
    if total > 0:
        low_broken_frac = (
            confidence_counts.get("LOW", 0) + confidence_counts.get("BROKEN", 0)
        ) / total
        report.violations.extend(check_satellite_capital(low_broken_frac, cfg))

    report.warnings.extend(check_confidence_quality(confidence_counts, cfg))

    return report
