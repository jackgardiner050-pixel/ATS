"""Universe Governor — hard concentration limits at the universe level.

The portfolio governance layer catches concentration IN the portfolio.
This layer catches concentration IN the tradable universe itself.

A concentrated universe predisposes every portfolio drawn from it to
inherit that concentration — the governance layers above cannot fully
compensate for structural bias at the universe level.

Outputs: UNIVERSE_CONCENTRATION_WARNING for each violated limit.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .universe_classifier import (
    load_taxonomy,
    load_current_universe,
    build_ticker_archetype_map,
    get_taxonomy_limits,
)

# Archetypes considered "cyclical heavy" for the cyclical fraction check
_CYCLICAL_ARCHETYPES = frozenset([
    "cyclical_industrial", "AI_capex", "housing_sensitive", "commodity_sensitive",
])

# Archetypes considered "defensive" for the defensive fraction check
_DEFENSIVE_ARCHETYPES = frozenset([
    "defensive_compounder", "consumer_staples", "healthcare_stable",
    "regulated_utility", "recession_resilient",
])

# Archetypes considered "policy sensitive"
_POLICY_ARCHETYPES = frozenset([
    "policy_sensitive", "government_spending", "defense",
])

# Archetypes considered "leverage sensitive"
_LEVERAGE_ARCHETYPES = frozenset(["leverage_sensitive"])

# Core archetypes that represent important economic behaviors —
# their absence is a structural gap worth flagging
_CORE_ARCHETYPES = frozenset([
    "defensive_compounder", "cyclical_industrial", "AI_capex", "infrastructure",
    "government_spending", "defense", "energy_infrastructure", "regulated_utility",
    "healthcare_stable", "software_platform", "financial_data", "consumer_staples",
    "recession_resilient", "quality_compounder", "global_diversifier", "asset_manager",
])


@dataclass
class UniverseGovernanceResult:
    """Output of universe-level concentration governance check."""
    n_tickers: int
    archetype_fractions: dict[str, float]        # {archetype: fraction of universe}
    warnings: list[str]                           # UNIVERSE_CONCENTRATION_WARNING strings
    gap_alerts: list[str]                         # absent or severely underrepresented archetypes
    overrepresented_archetypes: list[str]         # archetypes exceeding max_archetype_fraction
    absent_archetypes: list[str]                  # archetypes with 0 coverage in current universe
    underrepresented_archetypes: list[str]        # archetypes below min threshold
    cyclical_fraction: float
    defensive_fraction: float
    policy_fraction: float
    leverage_fraction: float
    diversity_score: float                        # 0.0 = monopoly, 1.0 = perfectly balanced
    escalation_required: bool
    escalation_triggers: list[str] = field(default_factory=list)


def _compute_archetype_fractions(
    universe_tickers: list[str],
    ticker_archetype_map: dict[str, list[str]],
    all_archetypes: list[str],
) -> dict[str, float]:
    """Compute fraction of universe tickers in each archetype."""
    n = len(universe_tickers)
    if n == 0:
        return {a: 0.0 for a in all_archetypes}
    counts: dict[str, int] = {a: 0 for a in all_archetypes}
    for t in universe_tickers:
        for archetype in ticker_archetype_map.get(t.upper(), []):
            if archetype in counts:
                counts[archetype] += 1
    return {a: round(c / n, 4) for a, c in counts.items()}


def _group_fraction(
    universe_tickers: list[str],
    ticker_archetype_map: dict[str, list[str]],
    group_archetypes: frozenset[str],
) -> float:
    """Fraction of universe tickers that are in ANY of the group archetypes."""
    n = len(universe_tickers)
    if n == 0:
        return 0.0
    count = sum(
        1 for t in universe_tickers
        if any(a in group_archetypes for a in ticker_archetype_map.get(t.upper(), []))
    )
    return round(count / n, 4)


def _herfindahl_diversity(fractions: list[float]) -> float:
    """Diversity score based on inverse Herfindahl-Hirschman Index.

    Returns 1.0 when all archetypes equally represented, 0.0 when monopoly.
    """
    nonzero = [f for f in fractions if f > 0]
    if not nonzero:
        return 0.0
    n_ideal = len(fractions)
    hhi = sum(f ** 2 for f in nonzero)
    min_hhi = 1.0 / n_ideal if n_ideal > 0 else 1.0
    return round(max(0.0, 1.0 - (hhi - min_hhi) / (1.0 - min_hhi)), 4)


def assess_universe_balance(
    tickers: list[str] | None = None,
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
) -> UniverseGovernanceResult:
    """Assess universe-level concentration and diversity.

    If tickers is None, loads the current universe from universe.yaml.
    """
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    limits = get_taxonomy_limits(taxonomy_cfg)
    ticker_archetype_map = build_ticker_archetype_map(taxonomy_cfg)
    all_archetypes = list(taxonomy_cfg.get("archetypes", {}).keys())

    universe_tickers = tickers if tickers is not None else load_current_universe(universe_path)
    upper_tickers = [t.upper() for t in universe_tickers]
    n = len(upper_tickers)

    archetype_fractions = _compute_archetype_fractions(upper_tickers, ticker_archetype_map, all_archetypes)

    cyclical_frac = _group_fraction(upper_tickers, ticker_archetype_map, _CYCLICAL_ARCHETYPES)
    defensive_frac = _group_fraction(upper_tickers, ticker_archetype_map, _DEFENSIVE_ARCHETYPES)
    policy_frac = _group_fraction(upper_tickers, ticker_archetype_map, _POLICY_ARCHETYPES)
    leverage_frac = _group_fraction(upper_tickers, ticker_archetype_map, _LEVERAGE_ARCHETYPES)

    max_arch = limits.get("max_archetype_fraction", 0.20)
    max_cyclical = limits.get("max_cyclical_fraction", 0.30)
    max_policy = limits.get("max_policy_fraction", 0.20)
    max_leverage = limits.get("max_leverage_fraction", 0.15)
    min_defensive = limits.get("min_defensive_fraction", 0.15)
    overrep_threshold = limits.get("overrepresented_threshold", 0.25)

    warnings: list[str] = []
    gap_alerts: list[str] = []
    overrepresented: list[str] = []
    absent: list[str] = []
    underrepresented: list[str] = []

    # Per-archetype concentration checks
    for archetype, frac in archetype_fractions.items():
        if frac > overrep_threshold:
            overrepresented.append(archetype)
            warnings.append(
                f"UNIVERSE_CONCENTRATION_WARNING: archetype '{archetype}' represents "
                f"{frac:.1%} of universe (overrepresented threshold: {overrep_threshold:.0%})"
            )
        elif frac > max_arch:
            overrepresented.append(archetype)
            warnings.append(
                f"UNIVERSE_CONCENTRATION_WARNING: archetype '{archetype}' at {frac:.1%} "
                f"exceeds {max_arch:.0%} single-archetype limit"
            )

    # Core archetype absence / underrepresentation
    for archetype in _CORE_ARCHETYPES:
        frac = archetype_fractions.get(archetype, 0.0)
        if frac == 0.0:
            absent.append(archetype)
            gap_alerts.append(
                f"UNIVERSE_GAP: archetype '{archetype}' has 0 members in current universe — "
                f"this economic behavior is completely absent"
            )
        elif frac < 0.03:
            underrepresented.append(archetype)
            gap_alerts.append(
                f"UNIVERSE_UNDERREPRESENTED: archetype '{archetype}' at {frac:.1%} — "
                f"near-absent economic behavior"
            )

    # Group-level checks
    if cyclical_frac > max_cyclical:
        warnings.append(
            f"UNIVERSE_CONCENTRATION_WARNING: cyclical group (cyclical_industrial + AI_capex + "
            f"housing_sensitive + commodity_sensitive) represents {cyclical_frac:.1%} of universe "
            f"(limit: {max_cyclical:.0%}) — adverse capex cycle impairs >30% of opportunity set"
        )

    if policy_frac > max_policy:
        warnings.append(
            f"UNIVERSE_CONCENTRATION_WARNING: policy-sensitive group at {policy_frac:.1%} "
            f"(limit: {max_policy:.0%}) — budget cuts or policy shifts affect majority of universe"
        )

    if leverage_frac > max_leverage:
        warnings.append(
            f"UNIVERSE_CONCENTRATION_WARNING: leverage-sensitive group at {leverage_frac:.1%} "
            f"(limit: {max_leverage:.0%}) — rate shocks disproportionately impair opportunity set"
        )

    if defensive_frac < min_defensive:
        gap_alerts.append(
            f"UNIVERSE_GAP: defensive archetypes represent only {defensive_frac:.1%} of universe "
            f"(minimum: {min_defensive:.0%}) — universe lacks recession-resilient opportunity set"
        )

    # Diversity score
    fracs = list(archetype_fractions.values())
    diversity_score = _herfindahl_diversity(fracs)

    # Escalation
    escalation_triggers: list[str] = []
    if len(overrepresented) >= 3:
        escalation_triggers.append(
            f"UNIVERSE_STRUCTURAL_BIAS: {len(overrepresented)} archetypes overrepresented — "
            f"universe predisposes portfolios to concentrated macro bets"
        )
    if absent:
        escalation_triggers.append(
            f"UNIVERSE_CRITICAL_GAPS: {len(absent)} core archetypes absent — "
            f"({', '.join(absent[:4])})"
        )
    if diversity_score < 0.40:
        escalation_triggers.append(
            f"UNIVERSE_LOW_DIVERSITY: diversity score {diversity_score:.2f} — "
            f"universe is structurally concentrated"
        )

    all_warnings = warnings + gap_alerts
    escalation_required = bool(escalation_triggers)

    return UniverseGovernanceResult(
        n_tickers=n,
        archetype_fractions=archetype_fractions,
        warnings=warnings,
        gap_alerts=gap_alerts,
        overrepresented_archetypes=overrepresented,
        absent_archetypes=absent,
        underrepresented_archetypes=underrepresented,
        cyclical_fraction=cyclical_frac,
        defensive_fraction=defensive_frac,
        policy_fraction=policy_frac,
        leverage_fraction=leverage_frac,
        diversity_score=diversity_score,
        escalation_required=escalation_required,
        escalation_triggers=escalation_triggers,
    )
