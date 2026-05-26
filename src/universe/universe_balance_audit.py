"""Universe Balance Audit — continuous composition health assessment.

Answers: "Is the tradable universe itself structurally biased toward a
specific macro regime?"

Outputs per-archetype exposure, cyclicality/defensive balance, recession
resilience profile, policy sensitivity distribution, and identifies both
overrepresented and absent economic behaviors.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .universe_classifier import (
    load_taxonomy,
    build_ticker_archetype_map,
    load_current_universe,
    get_taxonomy_limits,
    classify_ticker,
)
from .universe_governor import (
    assess_universe_balance,
    _CYCLICAL_ARCHETYPES,
    _DEFENSIVE_ARCHETYPES,
    _POLICY_ARCHETYPES,
    _LEVERAGE_ARCHETYPES,
    _CORE_ARCHETYPES,
)

_UNIVERSE_PATH = Path(__file__).parent.parent.parent / "config" / "universe.yaml"


@dataclass
class UniverseAuditResult:
    """Full universe composition audit output."""
    n_tickers: int
    archetype_exposures: dict[str, float]     # {archetype: fraction of universe}
    cyclicality_distribution: dict            # histogram buckets
    avg_cyclicality: float
    avg_defensiveness: float
    avg_recession_sensitivity: float
    avg_policy_sensitivity: float
    defensive_fraction: float
    recession_resilient_fraction: float
    policy_fraction: float
    leverage_fraction: float
    cyclical_fraction: float
    global_diversifier_fraction: float
    overrepresented_archetypes: list[str]
    underrepresented_archetypes: list[str]
    absent_archetypes: list[str]
    diversification_gaps: list[str]           # human-readable gap descriptions
    balance_score: float                      # 0.0 = highly imbalanced, 1.0 = balanced
    universe_bias_summary: str               # plain-language characterization
    governance_warnings: list[str]
    escalation_triggers: list[str]


def _compute_avg_characteristic(
    tickers: list[str],
    ticker_archetype_map: dict[str, list[str]],
    taxonomy_cfg: dict,
    characteristic: str,
) -> float:
    """Average a derived characteristic across all universe tickers."""
    if not tickers:
        return 0.0
    total = 0.0
    for t in tickers:
        classification = classify_ticker(t, ticker_archetype_map, taxonomy_cfg, tickers)
        val = getattr(classification, characteristic, 0.50)
        total += val
    return round(total / len(tickers), 4)


def _cyclicality_histogram(
    tickers: list[str],
    ticker_archetype_map: dict[str, list[str]],
    taxonomy_cfg: dict,
) -> dict:
    """Bucket tickers by cyclicality score."""
    buckets = {"low": 0, "moderate": 0, "high": 0, "extreme": 0}
    for t in tickers:
        c = classify_ticker(t, ticker_archetype_map, taxonomy_cfg, tickers)
        score = c.cyclicality_score
        if score < 0.25:
            buckets["low"] += 1
        elif score < 0.50:
            buckets["moderate"] += 1
        elif score < 0.75:
            buckets["high"] += 1
        else:
            buckets["extreme"] += 1
    n = len(tickers) if tickers else 1
    return {k: round(v / n, 3) for k, v in buckets.items()}


def _compute_group_fraction(
    tickers: list[str],
    ticker_archetype_map: dict[str, list[str]],
    group_archetypes: frozenset[str],
) -> float:
    if not tickers:
        return 0.0
    count = sum(
        1 for t in tickers
        if any(a in group_archetypes for a in ticker_archetype_map.get(t.upper(), []))
    )
    return round(count / len(tickers), 4)


def _balance_score(
    overrepresented: list[str],
    absent: list[str],
    underrepresented: list[str],
    n_core_archetypes: int,
) -> float:
    """Score universe balance from 0.0 (imbalanced) to 1.0 (balanced).

    Penalizes absent and overrepresented archetypes.
    """
    n = max(n_core_archetypes, 1)
    absent_penalty = len(absent) / n * 0.50
    overrep_penalty = len(overrepresented) / n * 0.30
    underrep_penalty = len(underrepresented) / n * 0.20
    return round(max(0.0, 1.0 - absent_penalty - overrep_penalty - underrep_penalty), 4)


def _bias_summary(
    cyclical_frac: float,
    defensive_frac: float,
    policy_frac: float,
    absent: list[str],
    overrepresented: list[str],
) -> str:
    parts = []
    if cyclical_frac > 0.30:
        parts.append(f"cyclical-heavy ({cyclical_frac:.0%} cyclical industrial/capex exposure)")
    if defensive_frac < 0.20:
        parts.append(f"defensively thin ({defensive_frac:.0%} defensive archetype coverage)")
    if policy_frac > 0.15:
        parts.append(f"policy-dependent ({policy_frac:.0%} government/defense/policy exposure)")
    if absent:
        parts.append(f"missing {len(absent)} core archetypes ({', '.join(absent[:3])})")
    if not parts:
        return "Universe appears reasonably balanced across economic behaviors."
    bias = "; ".join(parts)
    return (
        f"Universe is structurally biased: {bias}. "
        f"This predisposes any portfolio drawn from it to inherit these concentrations."
    )


def run_universe_audit(
    tickers: list[str] | None = None,
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
) -> UniverseAuditResult:
    """Run full universe composition audit.

    If tickers is None, loads the current universe from universe.yaml.
    """
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    ticker_archetype_map = build_ticker_archetype_map(taxonomy_cfg)
    limits = get_taxonomy_limits(taxonomy_cfg)
    all_archetypes = list(taxonomy_cfg.get("archetypes", {}).keys())

    universe_tickers = tickers if tickers is not None else load_current_universe(universe_path)
    upper = [t.upper() for t in universe_tickers]
    n = len(upper)

    # Run governance check for archetype fractions and gap alerts
    gov = assess_universe_balance(upper, taxonomy_path, universe_path)

    archetype_exposures = gov.archetype_fractions
    overrepresented = gov.overrepresented_archetypes
    absent = gov.absent_archetypes
    underrepresented = gov.underrepresented_archetypes

    # Average characteristics across universe
    avg_cyclicality = _compute_avg_characteristic(upper, ticker_archetype_map, taxonomy_cfg, "cyclicality_score")
    avg_defensiveness = _compute_avg_characteristic(upper, ticker_archetype_map, taxonomy_cfg, "defensiveness_score")
    avg_recession_sens = _compute_avg_characteristic(upper, ticker_archetype_map, taxonomy_cfg, "recession_sensitivity")
    avg_policy_sens = _compute_avg_characteristic(upper, ticker_archetype_map, taxonomy_cfg, "policy_sensitivity")

    cyclicality_dist = _cyclicality_histogram(upper, ticker_archetype_map, taxonomy_cfg)

    # Group fractions
    cyclical_frac = gov.cyclical_fraction
    defensive_frac = gov.defensive_fraction
    policy_frac = gov.policy_fraction
    leverage_frac = gov.leverage_fraction
    global_div_frac = _compute_group_fraction(upper, ticker_archetype_map, frozenset(["global_diversifier"]))
    recession_resilient_frac = _compute_group_fraction(upper, ticker_archetype_map, frozenset(["recession_resilient"]))

    # Balance score
    n_core = len(_CORE_ARCHETYPES)
    bal_score = _balance_score(overrepresented, absent, underrepresented, n_core)

    # Diversification gaps
    gaps: list[str] = []
    for archetype in absent:
        archetype_data = taxonomy_cfg.get("archetypes", {}).get(archetype, {})
        desc = archetype_data.get("description", "")
        gaps.append(
            f"ABSENT: '{archetype}' — {desc[:80] if desc else 'no coverage in current universe'}"
        )
    for archetype in underrepresented:
        frac = archetype_exposures.get(archetype, 0.0)
        gaps.append(
            f"THIN: '{archetype}' at {frac:.1%} — near-absent economic behavior"
        )
    for archetype in overrepresented:
        frac = archetype_exposures.get(archetype, 0.0)
        gaps.append(
            f"OVERWEIGHT: '{archetype}' at {frac:.1%} — dominates opportunity set"
        )

    # Bias summary
    bias_summary = _bias_summary(cyclical_frac, defensive_frac, policy_frac, absent, overrepresented)

    # Escalation
    escalation_triggers = list(gov.escalation_triggers)
    if bal_score < 0.50:
        escalation_triggers.append(
            f"UNIVERSE_IMBALANCE: balance score is {bal_score:.2f} — "
            f"universe structure predisposes portfolio concentration"
        )

    return UniverseAuditResult(
        n_tickers=n,
        archetype_exposures=archetype_exposures,
        cyclicality_distribution=cyclicality_dist,
        avg_cyclicality=avg_cyclicality,
        avg_defensiveness=avg_defensiveness,
        avg_recession_sensitivity=avg_recession_sens,
        avg_policy_sensitivity=avg_policy_sens,
        defensive_fraction=defensive_frac,
        recession_resilient_fraction=recession_resilient_frac,
        policy_fraction=policy_frac,
        leverage_fraction=leverage_frac,
        cyclical_fraction=cyclical_frac,
        global_diversifier_fraction=global_div_frac,
        overrepresented_archetypes=overrepresented,
        underrepresented_archetypes=underrepresented,
        absent_archetypes=absent,
        diversification_gaps=gaps,
        balance_score=bal_score,
        universe_bias_summary=bias_summary,
        governance_warnings=gov.warnings + gov.gap_alerts,
        escalation_triggers=escalation_triggers,
    )
