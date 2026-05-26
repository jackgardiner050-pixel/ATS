"""Survivability Engine — portfolio fragility and drawdown estimation.

The system asks NOT "what is expected return?" but "what breaks this portfolio?"

Survivability score (0–100):
  100 = exceptionally well-diversified, low leverage, low cyclical concentration
    0 = single-bet, high leverage, maximum cyclical / policy concentration

All estimates are governance heuristics, not predictions. They are designed to
be conservative — to err on the side of flagging fragility rather than missing it.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .exposure_engine import (
    load_themes,
    build_ticker_theme_map,
    get_theme_limits,
    compute_theme_exposure,
    analyze_clusters,
    estimate_effective_bets,
)

# ─── Classification thresholds ────────────────────────────────────────────────

_CLASSIFICATIONS = [
    (70, "ROBUST"),
    (50, "ADEQUATE"),
    (30, "FRAGILE"),
    (0,  "HIGHLY_FRAGILE"),
]

_RECOVERY_DIFFICULTY = [
    (70, "LOW"),
    (50, "MODERATE"),
    (30, "HIGH"),
    (0,  "SEVERE"),
]

# Target effective bets for a well-diversified portfolio.
# For a 12-position book, a fully diversified portfolio would have 12 independent bets.
# We target 10 as the "full credit" ceiling (allowing for some structural overlap).
_TARGET_EFFECTIVE_BETS = 10


@dataclass
class SurvivabilityResult:
    """Full survivability analysis output."""
    survivability_score: float      # 0–100
    classification: str             # ROBUST / ADEQUATE / FRAGILE / HIGHLY_FRAGILE
    fragility_score: float          # 0.0–1.0 (complement of survivability)
    concentration_score: float      # 0.0–1.0 component
    leverage_score: float           # 0.0–1.0 component
    cyclical_score: float           # 0.0–1.0 component
    policy_score: float             # 0.0–1.0 component
    diversification_score: float    # 0.0–1.0 component
    effective_bets: float
    effective_diversification_ratio: float
    estimated_max_drawdown: float   # fraction, e.g. 0.28 = 28%
    recovery_difficulty: str        # LOW / MODERATE / HIGH / SEVERE
    cluster_contagion_risk: float   # 0.0–1.0
    downside_asymmetry: float       # ratio: downside risk / upside potential
    escalation_required: bool
    escalation_reasons: list[str] = field(default_factory=list)
    component_breakdown: dict = field(default_factory=dict)


# ─── Component scoring ────────────────────────────────────────────────────────

def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def _score_diversification(effective_bets: float, n_positions: int) -> float:
    """Higher effective bets → higher diversification score."""
    if n_positions <= 0:
        return 0.0
    ratio = effective_bets / _TARGET_EFFECTIVE_BETS
    return _clamp01(ratio)


def _score_concentration(theme_exposure: dict[str, float], theme_limit: float) -> float:
    """Lower max theme exposure → higher score (better)."""
    if not theme_exposure:
        return 1.0
    max_theme = max(
        (w for t, w in theme_exposure.items() if t != "unclassified"),
        default=0.0,
    )
    if max_theme <= theme_limit:
        return 1.0
    # Excess fraction above the limit, capped at 1.0 penalty
    excess = (max_theme - theme_limit) / theme_limit
    return _clamp01(1.0 - excess)


def _score_leverage(leverage_exposure: float, leverage_limit: float) -> float:
    """Lower leverage cluster → higher score."""
    if leverage_exposure <= leverage_limit:
        return 1.0
    excess = (leverage_exposure - leverage_limit) / leverage_limit
    return _clamp01(1.0 - excess)


def _score_cyclical(cyclical_exposure: float, cyclical_limit: float) -> float:
    """Lower cyclical cluster → higher score."""
    if cyclical_exposure <= cyclical_limit:
        return 1.0
    excess = (cyclical_exposure - cyclical_limit) / cyclical_limit
    return _clamp01(1.0 - excess)


def _score_policy(policy_exposure: float, policy_limit: float) -> float:
    """Lower policy dependency cluster → higher score."""
    if policy_exposure <= policy_limit:
        return 1.0
    excess = (policy_exposure - policy_limit) / policy_limit
    return _clamp01(1.0 - excess)


def _estimate_max_drawdown(
    diversification_score: float,
    concentration_score: float,
    leverage_score: float,
    cyclical_score: float,
    policy_score: float,
) -> float:
    """Heuristic estimate of portfolio max drawdown in an adverse scenario.

    Base drawdown: 15% (market beta for this type of portfolio).
    Each fragility dimension adds to base.
    """
    base = 0.15
    # Each score below 1.0 contributes a drawdown premium
    concentration_add = (1.0 - concentration_score) * 0.18
    leverage_add = (1.0 - leverage_score) * 0.12
    cyclical_add = (1.0 - cyclical_score) * 0.10
    policy_add = (1.0 - policy_score) * 0.08
    diversification_add = (1.0 - diversification_score) * 0.08

    return round(min(0.65, base + concentration_add + leverage_add + cyclical_add + policy_add + diversification_add), 3)


def _estimate_contagion_risk(
    clusters: list[list[str]],
    n_positions: int,
) -> float:
    """Estimate the fraction of portfolio at risk from cluster contagion.

    When a large cluster is impaired, what fraction of positions are affected?
    """
    if not clusters or n_positions == 0:
        return 0.0
    largest_cluster = max(len(c) for c in clusters)
    return round(_clamp01(largest_cluster / n_positions), 3)


# ─── Classification helpers ───────────────────────────────────────────────────

def _classify(score: float, thresholds: list[tuple]) -> str:
    for threshold, label in thresholds:
        if score >= threshold:
            return label
    return thresholds[-1][1]


# ─── Escalation logic ────────────────────────────────────────────────────────

def _compute_escalation(
    survivability_score: float,
    max_drawdown: float,
    theme_exposure: dict[str, float],
    clusters: dict,
    limits: dict,
) -> tuple[bool, list[str]]:
    """Return (escalation_required, reasons)."""
    reasons = []

    if survivability_score < 40:
        reasons.append(
            f"Portfolio survivability score is {survivability_score:.0f}/100 — "
            f"below minimum acceptable threshold of 40"
        )
    if max_drawdown > 0.30:
        reasons.append(
            f"Estimated max drawdown is {max_drawdown:.0%} — exceeds 30% governance threshold"
        )

    theme_limit = limits.get("max_single_theme", 0.25)
    breached = [(t, w) for t, w in theme_exposure.items()
                if t != "unclassified" and w > theme_limit]
    for t, w in breached:
        reasons.append(f"Theme '{t}' is {w:.0%} of portfolio (limit: {theme_limit:.0%})")

    for cluster_key, cluster_data in clusters.items():
        if cluster_data["breached"]:
            reasons.append(
                f"{cluster_key.replace('_', ' ')} exposure {cluster_data['exposure']:.0%} "
                f"exceeds {cluster_data['limit']:.0%} limit"
            )

    return bool(reasons), reasons


# ─── Main entry point ─────────────────────────────────────────────────────────

def compute_survivability(
    tickers: list[str],
    themes_path: Path | None = None,
    position_weights: dict[str, float] | None = None,
) -> SurvivabilityResult:
    """Compute full survivability analysis for a portfolio.

    Weights:
      0.30 — effective diversification (how many real bets do we have?)
      0.25 — theme concentration (how peaked is the largest theme?)
      0.20 — leverage cluster (how much high-leverage exposure?)
      0.15 — cyclical concentration (how cyclically exposed are we?)
      0.10 — policy dependency (how dependent on government spending?)
    """
    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)
    limits = get_theme_limits(themes_cfg)

    n = len(tickers)
    if n == 0:
        return SurvivabilityResult(
            survivability_score=0.0,
            classification="HIGHLY_FRAGILE",
            fragility_score=1.0,
            concentration_score=0.0,
            leverage_score=0.0,
            cyclical_score=0.0,
            policy_score=0.0,
            diversification_score=0.0,
            effective_bets=0.0,
            effective_diversification_ratio=0.0,
            estimated_max_drawdown=0.65,
            recovery_difficulty="SEVERE",
            cluster_contagion_risk=1.0,
            downside_asymmetry=5.0,
            escalation_required=True,
            escalation_reasons=["Empty portfolio"],
        )

    theme_exposure = compute_theme_exposure(tickers, ticker_theme_map)
    cluster_analysis = analyze_clusters(tickers, ticker_theme_map, limits)
    effective_bets, macro_clusters = estimate_effective_bets(tickers, ticker_theme_map)

    leverage_exp = cluster_analysis["leverage_cluster"]["exposure"]
    policy_exp = cluster_analysis["policy_cluster"]["exposure"]
    cyclical_exp = cluster_analysis["cyclical_cluster"]["exposure"]

    theme_limit = limits.get("max_single_theme", 0.25)
    leverage_limit = limits.get("max_leverage_cluster", 0.20)
    policy_limit = limits.get("max_policy_cluster", 0.25)
    cyclical_limit = limits.get("max_cyclical_cluster", 0.35)

    div_score = _score_diversification(effective_bets, n)
    conc_score = _score_concentration(theme_exposure, theme_limit)
    lev_score = _score_leverage(leverage_exp, leverage_limit)
    cyc_score = _score_cyclical(cyclical_exp, cyclical_limit)
    pol_score = _score_policy(policy_exp, policy_limit)

    # Weighted survivability
    raw = (
        0.30 * div_score +
        0.25 * conc_score +
        0.20 * lev_score +
        0.15 * cyc_score +
        0.10 * pol_score
    )
    survivability_score = round(raw * 100, 1)
    fragility_score = round(1.0 - raw, 4)

    max_drawdown = _estimate_max_drawdown(
        div_score, conc_score, lev_score, cyc_score, pol_score
    )
    contagion = _estimate_contagion_risk(macro_clusters, n)

    # Downside asymmetry: ratio of fragility-weighted loss to diversification benefit
    downside_asymmetry = round(max_drawdown / max(0.05, div_score * 0.12), 2)

    classification = _classify(survivability_score, _CLASSIFICATIONS)
    recovery = _classify(survivability_score, _RECOVERY_DIFFICULTY)

    escalation_required, escalation_reasons = _compute_escalation(
        survivability_score, max_drawdown, theme_exposure, cluster_analysis, limits
    )

    return SurvivabilityResult(
        survivability_score=survivability_score,
        classification=classification,
        fragility_score=fragility_score,
        concentration_score=round(conc_score, 4),
        leverage_score=round(lev_score, 4),
        cyclical_score=round(cyc_score, 4),
        policy_score=round(pol_score, 4),
        diversification_score=round(div_score, 4),
        effective_bets=effective_bets,
        effective_diversification_ratio=round(effective_bets / n, 3),
        estimated_max_drawdown=max_drawdown,
        recovery_difficulty=recovery,
        cluster_contagion_risk=contagion,
        downside_asymmetry=downside_asymmetry,
        escalation_required=escalation_required,
        escalation_reasons=escalation_reasons,
        component_breakdown={
            "diversification": round(div_score, 4),
            "theme_concentration": round(conc_score, 4),
            "leverage_cluster": round(lev_score, 4),
            "cyclical_cluster": round(cyc_score, 4),
            "policy_cluster": round(pol_score, 4),
            "effective_bets": effective_bets,
            "leverage_exposure": round(leverage_exp, 4),
            "cyclical_exposure": round(cyclical_exp, 4),
            "policy_exposure": round(policy_exp, 4),
        },
    )
