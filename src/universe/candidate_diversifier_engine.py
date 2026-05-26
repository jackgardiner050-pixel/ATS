"""Candidate Diversifier Engine — recommend economically diversifying additions.

Given the current universe and its structural biases, this engine identifies
which tickers would most improve economic behavior diversity.

The goal is NOT a longer ticker list. The goal is:
"What ONE addition would most reduce the universe's structural concentration?"

Optimization target: behavior diversity, not ticker count.

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
    ARCHETYPE_CHARACTERISTICS,
)
from .universe_governor import (
    assess_universe_balance,
    _CYCLICAL_ARCHETYPES,
    _DEFENSIVE_ARCHETYPES,
)

_UNIVERSE_PATH = Path(__file__).parent.parent.parent / "config" / "universe.yaml"


@dataclass
class CandidateRecommendation:
    """A recommended ticker addition for universe diversification."""
    ticker: str
    archetype_memberships: list[str]
    diversification_contribution: float    # 0.0–1.0, higher = more unique
    addresses_gaps: list[str]              # which absent/thin archetypes it fills
    rationale: str
    priority: str                          # HIGH / MEDIUM / LOW


@dataclass
class DiversifierReport:
    """Full output of the diversifier engine."""
    current_universe_size: int
    top_recommendations: list[CandidateRecommendation]
    addressed_gaps: list[str]             # gaps that at least one candidate fills
    remaining_gaps: list[str]             # gaps not addressed by any candidate
    portfolio_universe_alignment: dict    # universe-portfolio interaction analysis


def _get_expansion_candidates(
    taxonomy_cfg: dict,
    current_universe: list[str],
) -> dict[str, list[str]]:
    """Return tickers in taxonomy but NOT in current universe: {ticker: [archetypes]}."""
    ticker_archetype_map = build_ticker_archetype_map(taxonomy_cfg)
    upper_universe = {t.upper() for t in current_universe}
    return {
        ticker: archetypes
        for ticker, archetypes in ticker_archetype_map.items()
        if ticker not in upper_universe
    }


def _diversification_score(
    candidate_archetypes: list[str],
    absent_archetypes: list[str],
    underrepresented_archetypes: list[str],
    archetype_fractions: dict[str, float],
    n_universe: int,
) -> float:
    """Score how much a candidate improves universe diversity.

    Components:
    1. Coverage of absent archetypes (highest weight)
    2. Coverage of underrepresented archetypes (moderate weight)
    3. Avoidance of overrepresented archetypes (penalty)
    """
    score = 0.0

    for archetype in candidate_archetypes:
        if archetype in absent_archetypes:
            score += 1.0          # filling an absent archetype is maximum value
        elif archetype in underrepresented_archetypes:
            score += 0.50         # filling a thin archetype is medium value
        else:
            # Penalty for adding to already-overrepresented archetypes
            current_frac = archetype_fractions.get(archetype, 0.0)
            if current_frac > 0.25:
                score -= 0.20

    if not candidate_archetypes:
        return 0.0

    return round(max(0.0, min(1.0, score / max(len(candidate_archetypes), 1))), 4)


def _addressed_gaps(
    candidate_archetypes: list[str],
    absent: list[str],
    underrepresented: list[str],
) -> list[str]:
    gaps = []
    for a in candidate_archetypes:
        if a in absent:
            gaps.append(f"{a} [ABSENT]")
        elif a in underrepresented:
            gaps.append(f"{a} [THIN]")
    return gaps


def _build_rationale(
    ticker: str,
    archetypes: list[str],
    gaps: list[str],
    taxonomy_cfg: dict,
) -> str:
    if not gaps:
        unique = [a for a in archetypes if ARCHETYPE_CHARACTERISTICS.get(a, {}).get("defensiveness", 0) > 0.70]
        if unique:
            return f"{ticker} adds {unique[0]} economic behavior to the universe."
        return f"{ticker} adds economic behavior diversity across {', '.join(archetypes[:3])}."

    gap_names = [g.split(" [")[0] for g in gaps[:2]]
    arch_descs = [
        taxonomy_cfg.get("archetypes", {}).get(a, {}).get("description", a)[:50]
        for a in gap_names
    ]
    return (
        f"{ticker} fills {len(gaps)} structural gap(s): {', '.join(gap_names)}. "
        f"{arch_descs[0] if arch_descs else ''}."
    )


def _priority(div_score: float, gaps: list[str]) -> str:
    absent_gaps = sum(1 for g in gaps if "[ABSENT]" in g)
    if absent_gaps >= 1 or div_score >= 0.70:
        return "HIGH"
    if div_score >= 0.40:
        return "MEDIUM"
    return "LOW"


def recommend_diversifiers(
    current_tickers: list[str] | None = None,
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
    n: int = 10,
) -> DiversifierReport:
    """Recommend the most diversifying additions to the current universe.

    If current_tickers is None, loads from universe.yaml.
    Returns the top n recommendations sorted by diversification contribution.
    """
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    ticker_archetype_map = build_ticker_archetype_map(taxonomy_cfg)

    universe = current_tickers if current_tickers is not None else load_current_universe(universe_path)
    upper_universe = [t.upper() for t in universe]

    gov = assess_universe_balance(upper_universe, taxonomy_path, universe_path)
    absent = gov.absent_archetypes
    underrepresented = gov.underrepresented_archetypes
    archetype_fracs = gov.archetype_fractions
    n_universe = len(upper_universe)

    # All taxonomy tickers not in current universe
    candidates = _get_expansion_candidates(taxonomy_cfg, upper_universe)

    recommendations: list[CandidateRecommendation] = []
    for ticker, archetypes in candidates.items():
        div_score = _diversification_score(
            archetypes, absent, underrepresented, archetype_fracs, n_universe
        )
        gaps = _addressed_gaps(archetypes, absent, underrepresented)
        rationale = _build_rationale(ticker, archetypes, gaps, taxonomy_cfg)
        priority = _priority(div_score, gaps)

        recommendations.append(CandidateRecommendation(
            ticker=ticker,
            archetype_memberships=sorted(archetypes),
            diversification_contribution=div_score,
            addresses_gaps=gaps,
            rationale=rationale,
            priority=priority,
        ))

    # Sort: by diversification contribution descending, then alpha
    recommendations.sort(key=lambda r: (-r.diversification_contribution, r.ticker))
    top = recommendations[:n]

    # Gaps addressed by any recommendation
    all_addressed = set()
    for rec in recommendations:
        for g in rec.addresses_gaps:
            all_addressed.add(g.split(" [")[0])

    remaining_gaps = [a for a in absent if a not in all_addressed]

    return DiversifierReport(
        current_universe_size=n_universe,
        top_recommendations=top,
        addressed_gaps=sorted(all_addressed),
        remaining_gaps=remaining_gaps,
        portfolio_universe_alignment={},  # populated by check_universe_portfolio_alignment
    )


def check_universe_portfolio_alignment(
    portfolio_tickers: list[str],
    universe_tickers: list[str] | None = None,
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
) -> dict:
    """Assess how universe concentration affects portfolio governance standards.

    When the universe is structurally biased, the portfolio governance layer
    must compensate — this function makes that compensation explicit.

    Returns a dict with:
    - raised_cyclical_standards: if universe is cyclical-heavy, portfolio bar is higher
    - defensive_premium: boost to diversification score for defensive candidates
    - policy_pressure: if universe overweights policy, portfolio needs to be more cautious
    - escalation_notes: what the governance layer should do differently
    """
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    ticker_archetype_map = build_ticker_archetype_map(taxonomy_cfg)

    u_tickers = universe_tickers if universe_tickers is not None else load_current_universe(universe_path)
    upper_universe = [t.upper() for t in u_tickers]
    upper_portfolio = [t.upper() for t in portfolio_tickers]

    universe_gov = assess_universe_balance(upper_universe, taxonomy_path, universe_path)

    u_cyclical = universe_gov.cyclical_fraction
    u_defensive = universe_gov.defensive_fraction
    u_policy = universe_gov.policy_fraction

    # Portfolio cyclical fraction
    p_cyclical = sum(
        1 for t in upper_portfolio
        if any(a in _CYCLICAL_ARCHETYPES for a in ticker_archetype_map.get(t, []))
    ) / max(len(upper_portfolio), 1)

    # Portfolio defensive fraction
    p_defensive = sum(
        1 for t in upper_portfolio
        if any(a in _DEFENSIVE_ARCHETYPES for a in ticker_archetype_map.get(t, []))
    ) / max(len(upper_portfolio), 1)

    raised_cyclical_standards = u_cyclical > 0.28 and p_cyclical > 0.25
    defensive_premium = max(0.0, (0.15 - u_defensive) * 3.0) if u_defensive < 0.15 else 0.0
    policy_pressure = u_policy > 0.18 and p_cyclical > 0.20

    escalation_notes: list[str] = []
    if raised_cyclical_standards:
        escalation_notes.append(
            f"Universe is {u_cyclical:.0%} cyclical — portfolio cyclical standards RAISED; "
            f"portfolio cyclical exposure of {p_cyclical:.0%} amplifies universe bias"
        )
    if defensive_premium > 0.10:
        escalation_notes.append(
            f"Universe has thin defensive coverage ({u_defensive:.0%}) — "
            f"any defensive addition scores +{defensive_premium:.1f}x diversification premium"
        )
    if policy_pressure:
        escalation_notes.append(
            f"Universe ({u_policy:.0%}) and portfolio are both policy-heavy — "
            f"new positions should prioritize policy-independent economic behavior"
        )
    if universe_gov.absent_archetypes:
        absent_str = ", ".join(universe_gov.absent_archetypes[:3])
        escalation_notes.append(
            f"Universe lacks {len(universe_gov.absent_archetypes)} archetypes ({absent_str}) — "
            f"portfolio cannot diversify into these behaviors even if it wanted to"
        )

    return {
        "universe_cyclical_fraction": u_cyclical,
        "universe_defensive_fraction": u_defensive,
        "universe_policy_fraction": u_policy,
        "portfolio_cyclical_fraction": p_cyclical,
        "portfolio_defensive_fraction": p_defensive,
        "raised_cyclical_standards": raised_cyclical_standards,
        "defensive_premium": round(defensive_premium, 4),
        "policy_pressure": policy_pressure,
        "universe_absent_archetypes": universe_gov.absent_archetypes,
        "universe_overrepresented_archetypes": universe_gov.overrepresented_archetypes,
        "escalation_notes": escalation_notes,
    }
