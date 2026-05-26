"""Tests for src/portfolio/survivability_engine.py and src/portfolio/factor_engine.py

Validates:
- Survivability scores are in valid range
- Paper portfolio is classified FRAGILE or HIGHLY_FRAGILE (it is concentrated)
- Score components are individually valid
- Factor engine produces valid outputs
- Escalation triggers correctly
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.portfolio.survivability_engine import (
    compute_survivability,
    SurvivabilityResult,
)
from src.portfolio.factor_engine import (
    run_factor_analysis,
    compute_portfolio_factors,
    detect_factor_concentrations,
    get_ticker_factors,
    FACTORS,
    FactorAnalysis,
)

_THEMES_PATH = Path(__file__).parent.parent / "config" / "themes.yaml"

PAPER_TICKERS = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]


# ─── Survivability scoring ────────────────────────────────────────────────────

class TestSurvivabilityScoring:
    def test_score_in_valid_range(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert 0.0 <= result.survivability_score <= 100.0

    def test_paper_portfolio_is_fragile_or_worse(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert result.classification in ("FRAGILE", "HIGHLY_FRAGILE"), (
            f"Concentrated 12-position portfolio should be FRAGILE or HIGHLY_FRAGILE; "
            f"got {result.classification} (score={result.survivability_score:.1f})"
        )

    def test_fragility_score_complement_of_survivability(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert abs(result.fragility_score - (1.0 - result.survivability_score / 100.0)) < 0.02

    def test_component_scores_in_range(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        for component in ("concentration_score", "leverage_score", "cyclical_score",
                          "policy_score", "diversification_score"):
            v = getattr(result, component)
            assert 0.0 <= v <= 1.0, f"{component} must be in [0, 1]; got {v}"

    def test_effective_bets_less_than_positions(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert result.effective_bets < len(PAPER_TICKERS), (
            f"Effective bets ({result.effective_bets}) must be < "
            f"{len(PAPER_TICKERS)} positions due to thematic overlap"
        )

    def test_max_drawdown_in_valid_range(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert 0.0 < result.estimated_max_drawdown < 0.65

    def test_escalation_triggered_for_paper_portfolio(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert result.escalation_required, (
            "Paper portfolio should trigger escalation due to concentration"
        )
        assert len(result.escalation_reasons) >= 1

    def test_concentrated_worse_than_diversified(self):
        # ACM, DY, J, EMR: all infra/cyclical
        concentrated = compute_survivability(["ACM", "DY", "J", "EMR"], _THEMES_PATH)
        # GD, SPGI, KMI, AMAT: different macro bets
        diversified = compute_survivability(["GD", "SPGI", "KMI", "AMAT"], _THEMES_PATH)
        assert concentrated.survivability_score <= diversified.survivability_score, (
            f"Concentrated portfolio ({concentrated.survivability_score:.1f}) should score ≤ "
            f"diversified ({diversified.survivability_score:.1f})"
        )

    def test_empty_portfolio_returns_result(self):
        result = compute_survivability([], _THEMES_PATH)
        assert result.classification == "HIGHLY_FRAGILE"
        assert result.survivability_score == 0.0

    def test_component_breakdown_populated(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        bd = result.component_breakdown
        for key in ("diversification", "theme_concentration", "leverage_cluster",
                    "cyclical_cluster", "policy_cluster", "effective_bets"):
            assert key in bd, f"Missing key in component_breakdown: {key}"

    def test_recovery_difficulty_set(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert result.recovery_difficulty in ("LOW", "MODERATE", "HIGH", "SEVERE")

    def test_contagion_risk_in_range(self):
        result = compute_survivability(PAPER_TICKERS, _THEMES_PATH)
        assert 0.0 <= result.cluster_contagion_risk <= 1.0


# ─── Factor engine ────────────────────────────────────────────────────────────

class TestFactorEngine:
    def test_all_factors_present_in_output(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        for f in FACTORS:
            assert f in portfolio_factors, f"Missing factor: {f}"

    def test_factor_scores_in_valid_range(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        for f, v in portfolio_factors.items():
            assert 0.0 <= v <= 1.0, f"Factor {f} = {v} out of [0, 1]"

    def test_paper_portfolio_elevated_cyclicality(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        # GD/LDOS/KMI/TRGP/SPGI lower the average; threshold reflects blended portfolio
        assert portfolio_factors["cyclicality"] > 0.45, (
            f"Portfolio with AMAT, ACM, DY, EMR, J should show elevated cyclicality; "
            f"got {portfolio_factors['cyclicality']:.2f}"
        )

    def test_paper_portfolio_elevated_recession_sensitivity(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        assert portfolio_factors["recession_sensitivity"] > 0.40

    def test_paper_portfolio_elevated_leverage(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        assert portfolio_factors["leverage"] > 0.30, (
            "KMI (0.85) and TRGP (0.80) in the portfolio should elevate leverage factor"
        )

    def test_amat_has_highest_ai_capex_beta(self):
        amat_factors = get_ticker_factors("AMAT")
        spgi_factors = get_ticker_factors("SPGI")
        assert amat_factors["ai_capex_beta"] > spgi_factors["ai_capex_beta"]

    def test_unknown_ticker_returns_defaults(self):
        factors = get_ticker_factors("AAPL")
        assert all(0.0 <= v <= 1.0 for v in factors.values())
        assert len(factors) == len(FACTORS)

    def test_factor_concentration_warnings_generated(self):
        portfolio_factors = compute_portfolio_factors(PAPER_TICKERS)
        warnings = detect_factor_concentrations(portfolio_factors)
        # Elevated cyclicality and/or recession_sensitivity should trigger
        assert len(warnings) >= 1, (
            f"Paper portfolio should generate at least 1 factor concentration warning; "
            f"factors: {portfolio_factors}"
        )

    def test_run_factor_analysis_returns_dataclass(self):
        result = run_factor_analysis(PAPER_TICKERS)
        assert isinstance(result, FactorAnalysis)
        assert result.most_concentrated_factor in FACTORS
        assert 0.0 <= result.factor_dominance_score <= 1.0

    def test_equal_weight_vs_explicit_weight(self):
        n = len(PAPER_TICKERS)
        equal = compute_portfolio_factors(PAPER_TICKERS)
        explicit = compute_portfolio_factors(
            PAPER_TICKERS,
            weights={t.upper(): 1.0 / n for t in PAPER_TICKERS},
        )
        for f in FACTORS:
            assert abs(equal[f] - explicit[f]) < 0.001, (
                f"Equal weight and explicit 1/N weight should produce same result for {f}"
            )

    def test_defense_names_have_low_recession_sensitivity(self):
        defense_factors = compute_portfolio_factors(["GD", "LDOS"])
        assert defense_factors["recession_sensitivity"] < 0.25, (
            "Defense names should have low recession sensitivity"
        )
