"""Portfolio Stress Engine — scenario-based drawdown estimation.

Runs 10 adversarial macro scenarios and estimates portfolio impairment
based on theme membership sensitivity. Results classify the portfolio
from STABLE to HIGHLY_FRAGILE per scenario, and identify:
  - which positions are most vulnerable
  - which clusters get simultaneously impaired
  - which positions are likely recovery leaders

IMPORTANT: These are governance heuristics — scenario estimates, not predictions.
They are intentionally conservative to surface hidden fragility.
Drawdown estimates do NOT account for individual stock picking skill.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .exposure_engine import (
    load_themes,
    build_ticker_theme_map,
    compute_theme_exposure,
    get_cluster_tickers,
)

# ─── Scenario sensitivity table ───────────────────────────────────────────────
# {scenario_name: {theme: estimated_drawdown_fraction}}
# Positive = gain, negative = loss.
# Conservative (pessimistic) estimates throughout.

SCENARIO_SENSITIVITIES: dict[str, dict[str, float]] = {
    "rates_shock_150bps": {
        "leverage_sensitive":    -0.25,
        "rates_sensitive":       -0.18,
        "energy_infrastructure": -0.18,
        "quality_compounder":    -0.10,
        "housing_sensitive":     -0.15,
        "cyclical_industrial":   -0.08,
        "infrastructure":        -0.05,
        "defense":               -0.03,
        "semiconductor_cycle":   -0.08,
        "AI_capex":              -0.10,
        "AI_capex_adjacent":     -0.08,
        "industrial_capex":      -0.05,
        "recession_resilient":   -0.05,
        "government_spending":   -0.03,
        "utility_grid":          -0.08,
        "telecom_infrastructure": -0.05,
    },
    "recession": {
        "cyclical_industrial":   -0.32,
        "semiconductor_cycle":   -0.38,
        "infrastructure":        -0.20,
        "industrial_capex":      -0.22,
        "housing_sensitive":     -0.28,
        "AI_capex":              -0.35,
        "AI_capex_adjacent":     -0.22,
        "leverage_sensitive":    -0.18,
        "defense":               -0.05,
        "government_spending":   -0.03,
        "quality_compounder":    -0.10,
        "recession_resilient":   -0.05,
        "energy_infrastructure": -0.10,
        "rates_sensitive":       -0.12,
        "utility_grid":          -0.12,
        "policy_sensitive":      -0.08,
        "telecom_infrastructure": -0.15,
    },
    "ai_capex_slowdown": {
        "AI_capex":              -0.42,
        "semiconductor_cycle":   -0.38,
        "AI_capex_adjacent":     -0.28,
        "utility_grid":          -0.15,
        "industrial_capex":      -0.12,
        "infrastructure":        -0.08,
        "defense":               -0.03,
        "leverage_sensitive":    -0.05,
        "government_spending":   -0.02,
        "telecom_infrastructure": -0.10,
        "energy_infrastructure": -0.02,
        "quality_compounder":    -0.05,
    },
    "defense_spending_cuts": {
        "defense":               -0.28,
        "government_spending":   -0.22,
        "policy_sensitive":      -0.18,
        "infrastructure":        -0.12,
        "cyclical_industrial":   -0.05,
        "industrial_capex":      -0.03,
        "quality_compounder":    -0.02,
    },
    "liquidity_crisis": {
        "leverage_sensitive":    -0.38,
        "cyclical_industrial":   -0.28,
        "semiconductor_cycle":   -0.32,
        "AI_capex":              -0.28,
        "AI_capex_adjacent":     -0.22,
        "energy_infrastructure": -0.15,
        "infrastructure":        -0.18,
        "defense":               -0.10,
        "government_spending":   -0.08,
        "quality_compounder":    -0.15,
        "rates_sensitive":       -0.18,
        "housing_sensitive":     -0.25,
        "utility_grid":          -0.15,
        "industrial_capex":      -0.20,
        "telecom_infrastructure": -0.20,
    },
    "industrial_contraction": {
        "cyclical_industrial":   -0.25,
        "industrial_capex":      -0.22,
        "infrastructure":        -0.18,
        "semiconductor_cycle":   -0.30,
        "AI_capex":              -0.20,
        "AI_capex_adjacent":     -0.15,
        "energy_infrastructure": -0.05,
        "defense":               -0.02,
        "quality_compounder":    -0.05,
        "utility_grid":          -0.10,
        "telecom_infrastructure": -0.12,
    },
    "commodity_shock": {
        "industrial_capex":      -0.12,
        "infrastructure":        -0.08,
        "cyclical_industrial":   -0.10,
        "AI_capex":              -0.05,
        "energy_infrastructure": +0.05,
        "semiconductor_cycle":   -0.08,
        "quality_compounder":    -0.03,
        "defense":               -0.02,
        "leverage_sensitive":    -0.05,
    },
    "credit_spread_expansion": {
        "leverage_sensitive":    -0.22,
        "energy_infrastructure": -0.15,
        "infrastructure":        -0.08,
        "industrial_capex":      -0.08,
        "cyclical_industrial":   -0.08,
        "housing_sensitive":     -0.12,
        "rates_sensitive":       -0.12,
        "quality_compounder":    -0.05,
        "defense":               -0.03,
        "AI_capex":              -0.08,
        "utility_grid":          -0.08,
    },
    "stagflation": {
        "rates_sensitive":       -0.18,
        "leverage_sensitive":    -0.22,
        "quality_compounder":    -0.12,
        "cyclical_industrial":   -0.10,
        "infrastructure":        -0.05,
        "defense":               -0.03,
        "energy_infrastructure":  0.00,
        "AI_capex":              -0.08,
        "housing_sensitive":     -0.15,
        "industrial_capex":      -0.08,
        "semiconductor_cycle":   -0.12,
    },
    "policy_austerity": {
        "government_spending":   -0.32,
        "defense":               -0.28,
        "infrastructure":        -0.22,
        "policy_sensitive":      -0.28,
        "industrial_capex":      -0.10,
        "cyclical_industrial":   -0.05,
        "leverage_sensitive":    -0.05,
        "quality_compounder":    -0.03,
    },
}

SCENARIO_DESCRIPTIONS = {
    "rates_shock_150bps": "Interest rates rise +150bps — leverage and duration stressed",
    "recession": "Economic recession — cyclicals, semicap, housing impaired",
    "ai_capex_slowdown": "AI / data center capex slowdown — semicap and adjacent impaired",
    "defense_spending_cuts": "US defense budget cuts — DoD and government IT impaired",
    "liquidity_crisis": "Liquidity crisis — leverage, growth, and cyclicals all sell off",
    "industrial_contraction": "Industrial activity contraction — capex and EPC impaired",
    "commodity_shock": "Commodity price spike — industrials hurt, energy mixed",
    "credit_spread_expansion": "Credit spread widening — high-leverage names disproportionately impaired",
    "stagflation": "Stagflation — rates and margins compressed simultaneously",
    "policy_austerity": "US government austerity / sequester — spending-dependent names impaired",
}

_CLASSIFICATIONS = [
    (0.10, "STABLE"),
    (0.20, "MODERATE_RISK"),
    (0.30, "FRAGILE"),
    (1.00, "HIGHLY_FRAGILE"),
]


def _classify_scenario(drawdown: float) -> str:
    for threshold, label in _CLASSIFICATIONS:
        if abs(drawdown) <= threshold:
            return label
    return "HIGHLY_FRAGILE"


# ─── Per-ticker impact ────────────────────────────────────────────────────────

def _estimate_ticker_drawdown(
    ticker: str,
    ticker_theme_map: dict[str, list[str]],
    scenario_sensitivities: dict[str, float],
) -> float:
    """Estimate a single ticker's drawdown under a scenario.

    Takes the average sensitivity across all of the ticker's themes.
    Tickers in many themes with high sensitivities get compounded impact.
    """
    themes = ticker_theme_map.get(ticker.upper(), [])
    if not themes:
        return -0.05  # unknown ticker: apply mild base drawdown

    sensitivities = [
        scenario_sensitivities.get(t, 0.0) for t in themes
    ]
    # Use the most negative (worst) + mean combination for conservatism
    avg = sum(sensitivities) / len(sensitivities)
    worst = min(sensitivities)
    return round(0.6 * avg + 0.4 * worst, 4)


# ─── Scenario analysis ───────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    scenario_name: str
    description: str
    estimated_portfolio_drawdown: float
    classification: str
    vulnerable_positions: list[str]
    recovery_leaders: list[str]
    impaired_themes: list[str]
    ticker_impacts: dict[str, float]


@dataclass
class PortfolioStressResult:
    scenarios: dict[str, ScenarioResult]
    worst_scenario: str
    worst_case_drawdown: float
    portfolio_classification: str
    average_drawdown: float
    always_vulnerable: list[str]   # tickers hurt in 7+ of 10 scenarios
    always_resilient: list[str]    # tickers hurt least across scenarios
    escalation_required: bool
    escalation_reasons: list[str]


def run_scenario(
    tickers: list[str],
    ticker_theme_map: dict[str, list[str]],
    scenario_name: str,
    scenario_sensitivities: dict[str, float],
) -> ScenarioResult:
    """Compute impact of one scenario on the portfolio."""
    impacts = {
        t.upper(): _estimate_ticker_drawdown(t, ticker_theme_map, scenario_sensitivities)
        for t in tickers
    }

    # Portfolio drawdown = equal-weighted average
    portfolio_drawdown = sum(impacts.values()) / len(tickers) if tickers else 0.0

    # Most vulnerable: worst 3 individual impacts
    sorted_impacts = sorted(impacts.items(), key=lambda x: x[1])
    vulnerable = [t for t, _ in sorted_impacts[:3] if sorted_impacts[0][1] < -0.05]

    # Recovery leaders: least negative or positive impact
    recovery = [t for t, v in sorted_impacts[::-1][:3] if v > sorted_impacts[-1][1] + 0.05]

    # Which themes are most impaired
    theme_impacts = sorted(
        [(theme, sens) for theme, sens in scenario_sensitivities.items() if sens < -0.10],
        key=lambda x: x[1]
    )
    impaired_themes = [t for t, _ in theme_impacts[:5]]

    return ScenarioResult(
        scenario_name=scenario_name,
        description=SCENARIO_DESCRIPTIONS.get(scenario_name, scenario_name),
        estimated_portfolio_drawdown=round(portfolio_drawdown, 4),
        classification=_classify_scenario(portfolio_drawdown),
        vulnerable_positions=vulnerable,
        recovery_leaders=recovery,
        impaired_themes=impaired_themes,
        ticker_impacts=impacts,
    )


def run_portfolio_stress(
    tickers: list[str],
    themes_path: Path | None = None,
) -> PortfolioStressResult:
    """Run all 10 stress scenarios against the portfolio."""
    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)

    scenario_results: dict[str, ScenarioResult] = {}
    for scenario_name, sensitivities in SCENARIO_SENSITIVITIES.items():
        scenario_results[scenario_name] = run_scenario(
            tickers, ticker_theme_map, scenario_name, sensitivities
        )

    # Worst scenario by portfolio drawdown
    worst_name = min(
        scenario_results.keys(),
        key=lambda s: scenario_results[s].estimated_portfolio_drawdown,
    )
    worst_drawdown = scenario_results[worst_name].estimated_portfolio_drawdown
    avg_drawdown = sum(
        r.estimated_portfolio_drawdown for r in scenario_results.values()
    ) / len(scenario_results)

    # Portfolio classification = based on worst scenario
    portfolio_classification = _classify_scenario(worst_drawdown)

    # Tickers hurt in most scenarios (>= 7 of 10)
    hurt_counts: dict[str, int] = {}
    hurt_total: dict[str, float] = {}
    for sr in scenario_results.values():
        for ticker, impact in sr.ticker_impacts.items():
            if impact < -0.10:
                hurt_counts[ticker] = hurt_counts.get(ticker, 0) + 1
            hurt_total[ticker] = hurt_total.get(ticker, 0.0) + impact

    always_vulnerable = sorted(
        [t for t, count in hurt_counts.items() if count >= 7],
        key=lambda t: hurt_total.get(t, 0)
    )
    always_resilient = sorted(
        [t for t in [x.upper() for x in tickers] if hurt_counts.get(t, 0) <= 2],
        key=lambda t: -hurt_total.get(t, 0),
    )

    # Escalation
    escalation_reasons = []
    if abs(worst_drawdown) > 0.15:
        escalation_reasons.append(
            f"Worst-case scenario '{worst_name}' estimates {abs(worst_drawdown):.0%} portfolio drawdown"
        )
    if portfolio_classification in ("MODERATE_RISK", "FRAGILE", "HIGHLY_FRAGILE"):
        escalation_reasons.append(
            f"Portfolio stress classification is {portfolio_classification} — review before next entry"
        )
    if len(always_vulnerable) >= 3:
        escalation_reasons.append(
            f"{len(always_vulnerable)} positions are hurt in 7+ of 10 scenarios: {always_vulnerable}"
        )

    return PortfolioStressResult(
        scenarios=scenario_results,
        worst_scenario=worst_name,
        worst_case_drawdown=worst_drawdown,
        portfolio_classification=portfolio_classification,
        average_drawdown=round(avg_drawdown, 4),
        always_vulnerable=always_vulnerable,
        always_resilient=always_resilient,
        escalation_required=bool(escalation_reasons),
        escalation_reasons=escalation_reasons,
    )
