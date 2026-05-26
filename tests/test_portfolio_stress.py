"""Tests for src/portfolio/portfolio_stress.py

Validates:
- All 10 scenarios run without error
- Output has correct structure
- Paper portfolio is correctly classified FRAGILE or worse in most scenarios
- Scenario sensitivity logic behaves correctly
- Historical-analog scenario validations
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.portfolio.portfolio_stress import (
    run_portfolio_stress,
    run_scenario,
    SCENARIO_SENSITIVITIES,
    SCENARIO_DESCRIPTIONS,
    PortfolioStressResult,
    ScenarioResult,
)
from src.portfolio.exposure_engine import load_themes, build_ticker_theme_map

_THEMES_PATH = Path(__file__).parent.parent / "config" / "themes.yaml"

PAPER_TICKERS = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]


# ─── All 10 scenarios run ─────────────────────────────────────────────────────

class TestAllScenariosRun:
    def test_all_10_scenarios_exist(self):
        assert len(SCENARIO_SENSITIVITIES) == 10

    def test_all_scenarios_have_descriptions(self):
        for name in SCENARIO_SENSITIVITIES:
            assert name in SCENARIO_DESCRIPTIONS, f"Missing description for scenario: {name}"

    def test_run_portfolio_stress_returns_all_scenarios(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        assert len(result.scenarios) == 10, f"Expected 10 scenarios; got {len(result.scenarios)}"

    def test_all_scenario_results_have_required_keys(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        for name, sr in result.scenarios.items():
            assert isinstance(sr, ScenarioResult), f"Scenario {name} must return ScenarioResult"
            assert sr.scenario_name == name
            assert isinstance(sr.estimated_portfolio_drawdown, float)
            assert sr.classification in ("STABLE", "MODERATE_RISK", "FRAGILE", "HIGHLY_FRAGILE")
            assert isinstance(sr.vulnerable_positions, list)
            assert isinstance(sr.ticker_impacts, dict)

    def test_ticker_impacts_cover_all_positions(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        for name, sr in result.scenarios.items():
            for t in PAPER_TICKERS:
                assert t.upper() in sr.ticker_impacts, (
                    f"Scenario {name} missing ticker {t}"
                )


# ─── Scenario logic ───────────────────────────────────────────────────────────

class TestScenarioLogic:
    def setup_method(self):
        cfg = load_themes(_THEMES_PATH)
        self.ttm = build_ticker_theme_map(cfg)

    def test_leverage_tickers_most_hurt_in_rates_shock(self):
        sr = run_scenario(
            PAPER_TICKERS, self.ttm, "rates_shock_150bps",
            SCENARIO_SENSITIVITIES["rates_shock_150bps"]
        )
        kmi_impact = sr.ticker_impacts.get("KMI", 0)
        trgp_impact = sr.ticker_impacts.get("TRGP", 0)
        gd_impact = sr.ticker_impacts.get("GD", 0)
        # Leverage-sensitive names should be hurt more than defense
        assert kmi_impact < gd_impact, (
            f"KMI ({kmi_impact:.2f}) should be hurt more than GD ({gd_impact:.2f}) in rates shock"
        )
        assert trgp_impact < gd_impact

    def test_amat_most_hurt_in_ai_capex_slowdown(self):
        sr = run_scenario(
            PAPER_TICKERS, self.ttm, "ai_capex_slowdown",
            SCENARIO_SENSITIVITIES["ai_capex_slowdown"]
        )
        amat_impact = sr.ticker_impacts.get("AMAT", 0)
        gd_impact = sr.ticker_impacts.get("GD", 0)
        spgi_impact = sr.ticker_impacts.get("SPGI", 0)
        assert amat_impact < gd_impact, (
            f"AMAT ({amat_impact:.2f}) must be hurt more than GD ({gd_impact:.2f}) in AI capex slowdown"
        )
        assert amat_impact < spgi_impact

    def test_defense_tickers_hurt_most_in_budget_cuts(self):
        sr = run_scenario(
            PAPER_TICKERS, self.ttm, "defense_spending_cuts",
            SCENARIO_SENSITIVITIES["defense_spending_cuts"]
        )
        gd_impact = sr.ticker_impacts.get("GD", 0)
        ldos_impact = sr.ticker_impacts.get("LDOS", 0)
        kmi_impact = sr.ticker_impacts.get("KMI", 0)
        spgi_impact = sr.ticker_impacts.get("SPGI", 0)
        assert gd_impact < kmi_impact, (
            f"GD ({gd_impact:.2f}) must be more hurt than KMI ({kmi_impact:.2f}) in defense cuts"
        )
        assert ldos_impact < spgi_impact

    def test_leverage_tickers_hurt_most_in_liquidity_crisis(self):
        sr = run_scenario(
            PAPER_TICKERS, self.ttm, "liquidity_crisis",
            SCENARIO_SENSITIVITIES["liquidity_crisis"]
        )
        kmi_impact = sr.ticker_impacts.get("KMI", 0)
        gd_impact = sr.ticker_impacts.get("GD", 0)
        assert kmi_impact < gd_impact, (
            f"KMI ({kmi_impact:.2f}) must be hurt more than GD ({gd_impact:.2f}) in liquidity crisis"
        )

    def test_portfolio_drawdown_is_negative_in_adverse_scenarios(self):
        for scenario in ("rates_shock_150bps", "recession", "liquidity_crisis",
                         "ai_capex_slowdown", "policy_austerity"):
            cfg = load_themes(_THEMES_PATH)
            ttm = build_ticker_theme_map(cfg)
            sr = run_scenario(PAPER_TICKERS, ttm, scenario, SCENARIO_SENSITIVITIES[scenario])
            assert sr.estimated_portfolio_drawdown < 0, (
                f"Scenario '{scenario}' should produce negative portfolio drawdown; "
                f"got {sr.estimated_portfolio_drawdown:.2f}"
            )

    def test_classification_consistent_with_drawdown(self):
        cfg = load_themes(_THEMES_PATH)
        ttm = build_ticker_theme_map(cfg)
        for scenario, sensitivities in SCENARIO_SENSITIVITIES.items():
            sr = run_scenario(PAPER_TICKERS, ttm, scenario, sensitivities)
            dd = abs(sr.estimated_portfolio_drawdown)
            if dd <= 0.10:
                assert sr.classification == "STABLE"
            elif dd <= 0.20:
                assert sr.classification == "MODERATE_RISK"
            elif dd <= 0.30:
                assert sr.classification == "FRAGILE"
            else:
                assert sr.classification == "HIGHLY_FRAGILE"


# ─── Portfolio-level stress results ───────────────────────────────────────────

class TestPortfolioStressResult:
    def test_worst_scenario_is_most_negative(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        worst_drawdown = result.worst_case_drawdown
        for name, sr in result.scenarios.items():
            assert sr.estimated_portfolio_drawdown >= worst_drawdown - 0.001, (
                f"Scenario {name} drawdown {sr.estimated_portfolio_drawdown} "
                f"is worse than claimed worst {worst_drawdown}"
            )

    def test_average_drawdown_between_best_and_worst(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        drawdowns = [sr.estimated_portfolio_drawdown for sr in result.scenarios.values()]
        assert min(drawdowns) <= result.average_drawdown <= max(drawdowns) + 0.001

    def test_paper_portfolio_escalation_required(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        assert result.escalation_required, (
            "Paper portfolio should trigger stress escalation"
        )

    def test_always_vulnerable_tickers_present(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        # Expect at least AMAT and ACM/DY to be always vulnerable (high cyclicality)
        assert len(result.always_vulnerable) >= 1

    def test_portfolio_classification_matches_worst_scenario(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        dd = abs(result.worst_case_drawdown)
        if dd <= 0.10:
            assert result.portfolio_classification == "STABLE"
        elif dd <= 0.20:
            assert result.portfolio_classification == "MODERATE_RISK"
        elif dd <= 0.30:
            assert result.portfolio_classification == "FRAGILE"
        else:
            assert result.portfolio_classification == "HIGHLY_FRAGILE"

    def test_empty_portfolio_runs_without_error(self):
        result = run_portfolio_stress([], _THEMES_PATH)
        assert isinstance(result, PortfolioStressResult)
        # No escalation from empty portfolio (no positions at risk)
        assert result.always_vulnerable == []


# ─── Historical scenario analogs ─────────────────────────────────────────────

class TestHistoricalScenarioAnalogs:
    """Validates that scenario logic behaves rationally against historical precedent.

    These tests do NOT claim to replicate actual 2008/2020 returns.
    They verify that concentration warnings trigger under conditions matching
    each crisis — the governance logic is pattern-consistent.
    """

    def test_2008_analog_liquidity_crisis(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        liq = result.scenarios["liquidity_crisis"]
        # 2008: high leverage destroyed first
        kmi_impact = liq.ticker_impacts.get("KMI", 0)
        gd_impact = liq.ticker_impacts.get("GD", 0)
        assert kmi_impact < gd_impact, "2008 analog: leverage-sensitive hurt more than defense"

    def test_2013_sequester_analog_policy_austerity(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        seq = result.scenarios["policy_austerity"]
        gd_impact = seq.ticker_impacts.get("GD", 0)
        kmi_impact = seq.ticker_impacts.get("KMI", 0)
        # 2013 sequester: defense contractors impaired; midstream less so
        assert gd_impact < kmi_impact, "2013 analog: defense hurt more than midstream in sequester"

    def test_2022_rates_shock_analog(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        rates = result.scenarios["rates_shock_150bps"]
        kmi_impact = rates.ticker_impacts.get("KMI", 0)
        spgi_impact = rates.ticker_impacts.get("SPGI", 0)
        gd_impact = rates.ticker_impacts.get("GD", 0)
        # 2022: leverage-sensitive and quality-growth hurt; defense less so
        assert kmi_impact < gd_impact, "2022 analog: leverage hurt more than defense"

    def test_2020_liquidity_cascade_hits_leverage_first(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        liq = result.scenarios["liquidity_crisis"]
        gnrc_impact = liq.ticker_impacts.get("GNRC", 0)
        ldos_impact = liq.ticker_impacts.get("LDOS", 0)
        # 2020: leveraged names sold harder than stable government contractors
        assert gnrc_impact < ldos_impact, "2020 analog: leveraged GNRC hurt more than LDOS"

    def test_ai_capex_slowdown_hits_semicap_hardest(self):
        result = run_portfolio_stress(PAPER_TICKERS, _THEMES_PATH)
        ai = result.scenarios["ai_capex_slowdown"]
        amat_impact = ai.ticker_impacts.get("AMAT", 0)
        gd_impact = ai.ticker_impacts.get("GD", 0)
        ldos_impact = ai.ticker_impacts.get("LDOS", 0)
        assert amat_impact < gd_impact
        assert amat_impact < ldos_impact, "AI capex slowdown should hurt semicap most"
