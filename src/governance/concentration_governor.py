"""Concentration Governor — hard blocking layer for portfolio construction.

These are BLOCKING constraints, not informational warnings.
A CONCENTRATION_BLOCK requires explicit human override before proceeding.

The governor serves two purposes:
  1. Assess current portfolio concentration (are we already in violation?)
  2. Evaluate a proposed new position (would adding it breach a hard limit?)

Governance philosophy: approvals are the DEFAULT DENY position.
The portfolio must actively qualify for inclusion, not passively escape exclusion.

No autonomous execution. No live trading. Diagnostic only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..portfolio.exposure_engine import (
    load_themes,
    build_ticker_theme_map,
    get_theme_limits,
    compute_theme_exposure,
    analyze_clusters,
)


# ─── Decision types ───────────────────────────────────────────────────────────

APPROVED = "APPROVED"
APPROVED_WITH_WARNINGS = "APPROVED_WITH_WARNINGS"
CONCENTRATION_BLOCK = "CONCENTRATION_BLOCK"

# Theme/cluster hard blocks only make sense for portfolios large enough to
# comply with them. Below this size, breaches become warnings (not blocks),
# since a 2-position portfolio cannot possibly have each theme below 25%.
_MIN_POSITIONS_FOR_HARD_BLOCKS = 5

# Confidence tier position size caps
_CONFIDENCE_CAPS = {
    "HIGH": 0.10,
    "MED_HIGH": 0.10,
    "MED": 0.10,
    "MED_LOW": 0.04,
    "LOW": 0.02,
    "BROKEN": 0.0,  # Never allocate to BROKEN
}


@dataclass
class ConcentrationDecision:
    """Result of a concentration governor check.

    decision: APPROVED | APPROVED_WITH_WARNINGS | CONCENTRATION_BLOCK
    block_reasons: non-empty when CONCENTRATION_BLOCK — specific limit breaches
    warnings: soft warnings that should be reviewed but don't block
    override_required: True when human override is needed to proceed
    override_instruction: exact text to display to the human reviewer
    new_exposures: what the portfolio would look like after the addition
    """
    decision: str
    block_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    override_required: bool = False
    override_instruction: str = ""
    new_exposures: dict = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return self.decision == CONCENTRATION_BLOCK

    @property
    def is_clean(self) -> bool:
        return self.decision == APPROVED and not self.warnings


# ─── Current portfolio checks ─────────────────────────────────────────────────

def check_current_portfolio(
    tickers: list[str],
    confidence_tiers: dict[str, str] | None = None,
    themes_path: Path | None = None,
) -> ConcentrationDecision:
    """Check current portfolio for hard limit violations.

    confidence_tiers: {ticker: tier_string} — used for satellite capital check.
    Returns a ConcentrationDecision summarizing the governance state.
    """
    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)
    limits = get_theme_limits(themes_cfg)

    blocks, warnings = [], []
    n = len(tickers) if tickers else 1
    hard_blocks_active = n >= _MIN_POSITIONS_FOR_HARD_BLOCKS

    # Theme concentration
    theme_exposure = compute_theme_exposure(tickers, ticker_theme_map)
    theme_limit = limits.get("max_single_theme", 0.25)
    for theme, w in theme_exposure.items():
        if theme == "unclassified":
            continue
        if w > theme_limit:
            msg = (
                f"Theme '{theme}' is {w:.1%} of portfolio (limit: {theme_limit:.1%}). "
                f"Positions: {[t for t in tickers if theme in ticker_theme_map.get(t.upper(), [])]}"
            )
            if hard_blocks_active:
                blocks.append(msg)
            else:
                warnings.append(f"[small portfolio] {msg}")

    # Cluster hard limits
    cluster_analysis = analyze_clusters(tickers, ticker_theme_map, limits)
    for cluster_key, cluster_data in cluster_analysis.items():
        if cluster_data["breached"]:
            msg = (
                f"{cluster_key.replace('_', ' ').title()} exposure is "
                f"{cluster_data['exposure']:.1%} (limit: {cluster_data['limit']:.1%}). "
                f"Positions: {cluster_data['tickers']}"
            )
            if hard_blocks_active:
                blocks.append(msg)
            else:
                warnings.append(f"[small portfolio] {msg}")

    # Single position concentration (equal weight assumed if no weights provided)
    equal_w = 1.0 / n if n > 0 else 0.0
    position_limit = limits.get("max_single_position", 0.10)
    if equal_w > position_limit:
        warnings.append(
            f"Portfolio has {n} positions; equal weight {equal_w:.1%} exceeds "
            f"single-position limit {position_limit:.1%} — diversify further"
        )

    # Confidence tier satellite cap
    if confidence_tiers:
        low_tickers = [t for t, tier in confidence_tiers.items()
                       if tier in ("LOW", "BROKEN")]
        low_frac = len(low_tickers) / n if n > 0 else 0.0
        if low_frac > 0.30:
            warnings.append(
                f"{low_frac:.1%} of portfolio is LOW/BROKEN confidence "
                f"({low_tickers}) — exceeds MAX_SATELLITE_CAPITAL=30%"
            )

    decision = CONCENTRATION_BLOCK if blocks else (
        APPROVED_WITH_WARNINGS if warnings else APPROVED
    )
    override_inst = (
        "HUMAN OVERRIDE REQUIRED: review the block reasons above and explicitly "
        "approve continuation with justification documented in the governance log."
        if blocks else ""
    )

    return ConcentrationDecision(
        decision=decision,
        block_reasons=blocks,
        warnings=warnings,
        override_required=bool(blocks),
        override_instruction=override_inst,
        new_exposures={"theme_exposure": theme_exposure, "clusters": cluster_analysis},
    )


# ─── New position approval ────────────────────────────────────────────────────

def assess_proposed_position(
    current_tickers: list[str],
    candidate_ticker: str,
    candidate_confidence_tier: str = "MED",
    themes_path: Path | None = None,
) -> ConcentrationDecision:
    """Assess whether adding a new ticker would breach hard concentration limits.

    Checks the portfolio AFTER adding the candidate. Does NOT check whether the
    individual stock is a good investment — that is the DCF pipeline's job.
    This function only enforces portfolio-level governance.

    Returns ConcentrationDecision with CONCENTRATION_BLOCK if adding this
    position would create or worsen a hard limit breach.
    """
    candidate = candidate_ticker.upper()
    if candidate in [t.upper() for t in current_tickers]:
        return ConcentrationDecision(
            decision=APPROVED_WITH_WARNINGS,
            warnings=[f"{candidate} is already in portfolio — adding would double concentration"],
        )

    # BROKEN confidence is a hard stop — never allocate
    if candidate_confidence_tier == "BROKEN":
        return ConcentrationDecision(
            decision=CONCENTRATION_BLOCK,
            block_reasons=[f"{candidate} has BROKEN confidence — position size cap is 0%"],
            override_required=True,
            override_instruction="HUMAN OVERRIDE REQUIRED: BROKEN confidence is a hard stop. "
                                 "This requires explicit portfolio manager review and approval.",
        )

    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)
    limits = get_theme_limits(themes_cfg)

    prospective_tickers = current_tickers + [candidate]
    blocks, warnings = [], []
    n_new = len(prospective_tickers)
    hard_blocks_active = n_new >= _MIN_POSITIONS_FOR_HARD_BLOCKS

    # Prospective theme exposure
    new_theme_exposure = compute_theme_exposure(prospective_tickers, ticker_theme_map)
    old_theme_exposure = compute_theme_exposure(current_tickers, ticker_theme_map)
    theme_limit = limits.get("max_single_theme", 0.25)

    for theme, w in new_theme_exposure.items():
        if theme == "unclassified":
            continue
        old_w = old_theme_exposure.get(theme, 0.0)
        if w > theme_limit:
            if old_w <= theme_limit:
                msg = (
                    f"Adding {candidate} would push theme '{theme}' from "
                    f"{old_w:.1%} to {w:.1%}, breaching the {theme_limit:.1%} hard limit"
                )
            else:
                msg = (
                    f"Theme '{theme}' is already at {old_w:.1%} (limit: {theme_limit:.1%}); "
                    f"adding {candidate} worsens it to {w:.1%}"
                )
            if hard_blocks_active:
                blocks.append(msg)
            else:
                warnings.append(msg)

    # Prospective cluster checks
    new_clusters = analyze_clusters(prospective_tickers, ticker_theme_map, limits)
    old_clusters = analyze_clusters(current_tickers, ticker_theme_map, limits)
    for cluster_key, cluster_data in new_clusters.items():
        old_data = old_clusters[cluster_key]
        if cluster_data["breached"]:
            if not old_data["breached"]:
                msg = (
                    f"Adding {candidate} would breach {cluster_key.replace('_', ' ').title()} "
                    f"limit: {old_data['exposure']:.1%} → {cluster_data['exposure']:.1%} "
                    f"(limit: {cluster_data['limit']:.1%})"
                )
            else:
                msg = (
                    f"{cluster_key.replace('_', ' ').title()} already breached at "
                    f"{old_data['exposure']:.1%}; {candidate} worsens it to {cluster_data['exposure']:.1%}"
                )
            if hard_blocks_active:
                blocks.append(msg)
            else:
                warnings.append(msg)

    # Confidence tier position size check
    tier_cap = _CONFIDENCE_CAPS.get(candidate_confidence_tier, 0.10)
    equal_weight = 1.0 / n_new
    if equal_weight > tier_cap:
        if tier_cap == 0.0:
            blocks.append(
                f"{candidate} confidence tier '{candidate_confidence_tier}' has 0% allocation cap"
            )
        else:
            warnings.append(
                f"Equal-weight position ({equal_weight:.1%}) exceeds "
                f"tier cap for '{candidate_confidence_tier}' ({tier_cap:.1%}) — "
                f"consider sizing down or improving confidence before entry"
            )

    # Watch: candidate's themes (informational)
    candidate_themes = ticker_theme_map.get(candidate, [])
    if not candidate_themes:
        warnings.append(f"{candidate} is not in themes.yaml — add it before proceeding")
    else:
        # Check if candidate shares >2 themes with any existing cluster tickers
        from ..portfolio.exposure_engine import _cluster_tickers_by_theme_overlap
        clusters_after = _cluster_tickers_by_theme_overlap(prospective_tickers, ticker_theme_map)
        for cluster in clusters_after:
            if candidate in cluster and len(cluster) >= 4:
                warnings.append(
                    f"{candidate} would join a {len(cluster)}-ticker thematic cluster "
                    f"{cluster} — watch for synchronized drawdown risk"
                )

    decision = CONCENTRATION_BLOCK if blocks else (
        APPROVED_WITH_WARNINGS if warnings else APPROVED
    )
    override_inst = (
        f"HUMAN OVERRIDE REQUIRED to add {candidate}: "
        "document justification and acknowledge the specific concentration risks listed above."
        if blocks else ""
    )

    return ConcentrationDecision(
        decision=decision,
        block_reasons=blocks,
        warnings=warnings,
        override_required=bool(blocks),
        override_instruction=override_inst,
        new_exposures={
            "theme_exposure": new_theme_exposure,
            "clusters": new_clusters,
            "candidate_themes": candidate_themes,
        },
    )


# ─── Escalation triggers ──────────────────────────────────────────────────────

def compute_escalation_triggers(
    tickers: list[str],
    survivability_score: float | None = None,
    expected_max_drawdown: float | None = None,
    themes_path: Path | None = None,
) -> list[str]:
    """Return list of escalation triggers that require mandatory review.

    These are portfolio-level conditions requiring human attention before
    the next governance cycle completes.
    """
    triggers = []
    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)
    limits = get_theme_limits(themes_cfg)

    theme_exposure = compute_theme_exposure(tickers, ticker_theme_map)
    cluster_analysis = analyze_clusters(tickers, ticker_theme_map, limits)

    # Concentration breaches
    theme_limit = limits.get("max_single_theme", 0.25)
    breached_themes = [(t, w) for t, w in theme_exposure.items()
                       if t != "unclassified" and w > theme_limit]
    if breached_themes:
        triggers.append(
            f"CONCENTRATION_BREACH: {len(breached_themes)} themes exceed {theme_limit:.0%} limit "
            f"({', '.join(f'{t}={w:.0%}' for t, w in breached_themes[:3])})"
        )

    for cluster_key, cluster_data in cluster_analysis.items():
        if cluster_data["breached"]:
            triggers.append(
                f"CLUSTER_BREACH_{cluster_key.upper()}: "
                f"{cluster_data['exposure']:.0%} of portfolio "
                f"(limit: {cluster_data['limit']:.0%})"
            )

    # Survivability threshold
    if survivability_score is not None and survivability_score < 40:
        triggers.append(
            f"LOW_SURVIVABILITY: portfolio survivability score is {survivability_score:.0f}/100 "
            f"(threshold: 40) — portfolio may not survive an adverse macro shift"
        )

    # Drawdown threshold
    if expected_max_drawdown is not None and expected_max_drawdown > 0.30:
        triggers.append(
            f"HIGH_DRAWDOWN_RISK: worst-case expected drawdown is {expected_max_drawdown:.0%} "
            f"(threshold: 30%) — consider de-risking before next positions"
        )

    return triggers
