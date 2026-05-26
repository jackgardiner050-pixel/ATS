"""Tests for src/universe/universe_balance_audit.py, candidate_diversifier_engine.py,
and economic_behavior_engine.py

Validates:
- Audit correctly identifies overrepresented and absent archetypes
- Diversifier engine recommends appropriate gap-filling candidates
- Portfolio-universe alignment detects when universe biases compound portfolio
- Historical analog validation: diversified universes produce better regime outcomes
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.universe.universe_balance_audit import run_universe_audit, UniverseAuditResult
from src.universe.candidate_diversifier_engine import (
    recommend_diversifiers,
    check_universe_portfolio_alignment,
    DiversifierReport,
    CandidateRecommendation,
)
from src.universe.economic_behavior_engine import run_behavior_analysis, BehaviorAnalysis

_TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "universe_taxonomy.yaml"
_UNIVERSE_PATH = Path(__file__).parent.parent / "config" / "universe.yaml"

with open(_UNIVERSE_PATH) as f:
    _U_CFG = yaml.safe_load(f)
CURRENT_UNIVERSE = [t.upper() for t in _U_CFG.get("universe", [])]

PAPER_PORTFOLIO = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]


# ─── Universe balance audit ───────────────────────────────────────────────────

class TestUniverseBalanceAudit:
    def test_audit_runs_on_current_universe(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert isinstance(result, UniverseAuditResult)
        assert result.n_tickers == len(CURRENT_UNIVERSE)

    def test_audit_result_has_required_fields(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert isinstance(result.archetype_exposures, dict)
        assert isinstance(result.cyclicality_distribution, dict)
        assert isinstance(result.overrepresented_archetypes, list)
        assert isinstance(result.absent_archetypes, list)
        assert isinstance(result.diversification_gaps, list)
        assert isinstance(result.balance_score, float)
        assert isinstance(result.universe_bias_summary, str)

    def test_cyclical_industrial_overrepresented(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert "cyclical_industrial" in result.overrepresented_archetypes, (
            f"cyclical_industrial at {result.archetype_exposures.get('cyclical_industrial', 0):.1%} "
            f"should be overrepresented; overrepresented list: {result.overrepresented_archetypes}"
        )

    def test_regulated_utility_underrepresented(self):
        # NEE added 2026-05-26 fills the gap but archetype is still thin (<3% threshold)
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert "regulated_utility" in result.underrepresented_archetypes, (
            f"regulated_utility at {result.archetype_exposures.get('regulated_utility', 0):.1%} "
            f"should be flagged as underrepresented; underrepresented: {result.underrepresented_archetypes}"
        )

    def test_asset_manager_underrepresented(self):
        # CME + BLK added 2026-05-26 but archetype is still thin (<3% threshold)
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert "asset_manager" in result.underrepresented_archetypes, (
            f"asset_manager at {result.archetype_exposures.get('asset_manager', 0):.1%} "
            f"should be flagged as underrepresented; underrepresented: {result.underrepresented_archetypes}"
        )

    def test_balance_score_in_range(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert 0.0 <= result.balance_score <= 1.0

    def test_current_universe_balance_below_perfect(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.balance_score < 0.90, (
            f"Universe with missing regulated_utility/asset_manager should score <0.90; "
            f"got {result.balance_score}"
        )

    def test_diversification_gaps_non_empty(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert len(result.diversification_gaps) >= 2

    def test_avg_cyclicality_elevated(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.avg_cyclicality > 0.35, (
            f"Universe with 30%+ cyclical tickers should have avg cyclicality > 0.35; "
            f"got {result.avg_cyclicality}"
        )

    def test_defensive_fraction_computed(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.defensive_fraction >= 0.0
        assert result.defensive_fraction <= 1.0

    def test_recession_resilient_fraction_computed(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.recession_resilient_fraction > 0.05, \
            "Universe has recession_resilient tickers (GD, LDOS, KO, PG, etc.)"

    def test_global_diversifier_fraction_computed(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.global_diversifier_fraction > 0.0, \
            "Universe has global diversifiers (CAT, MCD, KO, V, etc.)"

    def test_cyclicality_distribution_sums_to_one(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        total = sum(result.cyclicality_distribution.values())
        assert abs(total - 1.0) < 0.01, f"Cyclicality distribution should sum to ~1.0; got {total}"

    def test_bias_summary_is_non_empty_string(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert len(result.universe_bias_summary) > 20

    def test_governance_warnings_non_empty(self):
        result = run_universe_audit(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert len(result.governance_warnings) >= 1


# ─── Candidate diversifier engine ────────────────────────────────────────────

class TestCandidateDiversifierEngine:
    def test_diversifier_report_is_correct_type(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert isinstance(report, DiversifierReport)

    def test_diversifier_returns_recommendations(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH, n=10)
        assert len(report.top_recommendations) >= 1

    def test_recommendations_are_not_in_current_universe(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        upper_universe = {t.upper() for t in CURRENT_UNIVERSE}
        for rec in report.top_recommendations:
            assert rec.ticker not in upper_universe, \
                f"{rec.ticker} is already in universe but was recommended"

    def test_diversifier_recommends_utility(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        utility_recs = [r for r in report.top_recommendations
                        if "regulated_utility" in r.archetype_memberships]
        assert len(utility_recs) >= 1, (
            "Diversifier should recommend regulated_utility tickers "
            f"(NEE, DUK, SO, AEP); top recommendations: "
            f"{[r.ticker for r in report.top_recommendations[:5]]}"
        )

    def test_diversifier_recommends_asset_manager(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        mgr_recs = [r for r in report.top_recommendations
                    if "asset_manager" in r.archetype_memberships]
        assert len(mgr_recs) >= 1, (
            "Diversifier should recommend asset_manager tickers (CME, ICE, BLK); "
            f"top: {[r.ticker for r in report.top_recommendations[:5]]}"
        )

    def test_recommendations_have_required_fields(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        for rec in report.top_recommendations:
            assert isinstance(rec.ticker, str)
            assert isinstance(rec.archetype_memberships, list)
            assert 0.0 <= rec.diversification_contribution <= 1.0
            assert isinstance(rec.addresses_gaps, list)
            assert isinstance(rec.rationale, str)
            assert rec.priority in ("HIGH", "MEDIUM", "LOW")

    def test_utility_recommendation_not_blocked(self):
        # regulated_utility is now UNDERREPRESENTED (not ABSENT) — still worth recommending
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        utility_recs = [r for r in report.top_recommendations
                        if "regulated_utility" in r.archetype_memberships]
        assert len(utility_recs) >= 1, (
            "Diversifier should still recommend utility tickers to grow the thin archetype; "
            f"top: {[r.ticker for r in report.top_recommendations[:5]]}"
        )

    def test_top_recommendations_sorted_by_contribution(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        scores = [r.diversification_contribution for r in report.top_recommendations]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], "Recommendations must be sorted descending by contribution"

    def test_addressed_gaps_populated(self):
        report = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        # Should address at least regulated_utility and asset_manager
        assert len(report.addressed_gaps) >= 1

    def test_n_parameter_respected(self):
        report5 = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH, n=5)
        report10 = recommend_diversifiers(CURRENT_UNIVERSE, _TAXONOMY_PATH, n=10)
        assert len(report5.top_recommendations) <= 5
        assert len(report10.top_recommendations) <= 10


# ─── Portfolio-universe alignment ─────────────────────────────────────────────

class TestPortfolioUniverseAlignment:
    def test_alignment_runs(self):
        result = check_universe_portfolio_alignment(
            PAPER_PORTFOLIO, CURRENT_UNIVERSE, _TAXONOMY_PATH
        )
        assert isinstance(result, dict)

    def test_alignment_has_required_keys(self):
        result = check_universe_portfolio_alignment(
            PAPER_PORTFOLIO, CURRENT_UNIVERSE, _TAXONOMY_PATH
        )
        required = [
            "universe_cyclical_fraction", "portfolio_cyclical_fraction",
            "raised_cyclical_standards", "defensive_premium",
            "escalation_notes", "universe_absent_archetypes",
        ]
        for k in required:
            assert k in result, f"Missing key: {k}"

    def test_paper_portfolio_triggers_raised_cyclical_standards(self):
        # Universe is cyclical-heavy (~30%) AND portfolio is cyclical-heavy → raised standards
        result = check_universe_portfolio_alignment(
            PAPER_PORTFOLIO, CURRENT_UNIVERSE, _TAXONOMY_PATH
        )
        # Either raised_cyclical_standards is True OR there's an escalation note
        has_signal = (
            result["raised_cyclical_standards"]
            or any("cyclical" in note.lower() for note in result["escalation_notes"])
        )
        assert has_signal, (
            "Paper portfolio + cyclical universe should produce cyclical warning; "
            f"result: {result}"
        )

    def test_alignment_result_has_absent_archetypes_key(self):
        # regulated_utility and asset_manager are now underrepresented, not absent;
        # the absent list may be empty but the key must still exist
        result = check_universe_portfolio_alignment(
            PAPER_PORTFOLIO, CURRENT_UNIVERSE, _TAXONOMY_PATH
        )
        assert "universe_absent_archetypes" in result

    def test_escalation_notes_populated_for_biased_combination(self):
        result = check_universe_portfolio_alignment(
            PAPER_PORTFOLIO, CURRENT_UNIVERSE, _TAXONOMY_PATH
        )
        assert len(result["escalation_notes"]) >= 1


# ─── Economic behavior engine ─────────────────────────────────────────────────

class TestEconomicBehaviorEngine:
    def test_behavior_analysis_runs_on_full_universe(self):
        sample = CURRENT_UNIVERSE[:30]
        result = run_behavior_analysis(sample, _TAXONOMY_PATH)
        assert isinstance(result, BehaviorAnalysis)
        assert result.n_tickers == len(sample)

    def test_behavior_clusters_exist(self):
        sample = CURRENT_UNIVERSE[:30]
        result = run_behavior_analysis(sample, _TAXONOMY_PATH)
        assert result.n_behavior_clusters >= 1

    def test_effective_economic_bets_less_than_tickers(self):
        # A universe with 30 tickers will have behavioral clusters → effective < n
        sample = CURRENT_UNIVERSE[:30]
        result = run_behavior_analysis(sample, _TAXONOMY_PATH)
        assert result.effective_economic_bets < len(sample), (
            "Clustered universe should have fewer effective bets than raw ticker count"
        )

    def test_regime_diversification_scores_populated(self):
        sample = CURRENT_UNIVERSE[:20]
        result = run_behavior_analysis(sample, _TAXONOMY_PATH)
        assert len(result.regime_diversification_scores) >= 3
        for regime, score in result.regime_diversification_scores.items():
            assert 0.0 <= score <= 1.0, f"Regime {regime} score {score} out of range"

    def test_always_vulnerable_archetypes_populated(self):
        result = run_behavior_analysis(CURRENT_UNIVERSE[:20], _TAXONOMY_PATH)
        # cyclical_industrial and leverage_sensitive should appear as always vulnerable
        assert len(result.always_vulnerable_archetypes) >= 1

    def test_similarity_matrix_symmetric(self):
        sample = ["GD", "KO", "AMAT", "V", "KMI"]
        result = run_behavior_analysis(sample, _TAXONOMY_PATH)
        for t1 in sample:
            for t2 in sample:
                if t1 != t2:
                    s12 = result.similarity_matrix.get(t1.upper(), {}).get(t2.upper(), 0)
                    s21 = result.similarity_matrix.get(t2.upper(), {}).get(t1.upper(), 0)
                    assert s12 == s21, f"Similarity matrix not symmetric: {t1}-{t2}"

    def test_empty_universe_behavior_analysis(self):
        result = run_behavior_analysis([], _TAXONOMY_PATH)
        assert result.n_tickers == 0
        assert result.effective_economic_bets == 0.0


# ─── Historical analog validation ─────────────────────────────────────────────

class TestHistoricalAnalogs:
    def test_2008_analog_cyclicals_hurt_in_recession(self):
        """Universe with high cyclical fraction should have poor recession resilience."""
        from src.universe.economic_behavior_engine import _REGIME_ARCHETYPE_SENSITIVITIES
        recession = _REGIME_ARCHETYPE_SENSITIVITIES.get("recession", {})
        # cyclical_industrial should have strong negative sensitivity in recession
        assert recession.get("cyclical_industrial", 0) < -0.50, \
            "cyclical_industrial must have severe negative recession sensitivity"
        assert recession.get("AI_capex", 0) < -0.50, \
            "AI_capex must be heavily impacted in recession"

    def test_2022_analog_rates_hurt_leverage(self):
        """High-leverage names should be disproportionately impacted by rate shocks."""
        from src.universe.economic_behavior_engine import _REGIME_ARCHETYPE_SENSITIVITIES
        rates = _REGIME_ARCHETYPE_SENSITIVITIES.get("rates_shock", {})
        assert rates.get("leverage_sensitive", 0) < -0.50, \
            "leverage_sensitive must have strong negative rates shock sensitivity"

    def test_2020_analog_defensives_resilient(self):
        """Consumer staples and healthcare should be resilient in recession."""
        from src.universe.economic_behavior_engine import _REGIME_ARCHETYPE_SENSITIVITIES
        recession = _REGIME_ARCHETYPE_SENSITIVITIES.get("recession", {})
        assert recession.get("consumer_staples", 0) >= -0.20, \
            "consumer_staples should not be heavily impacted in recession"
        assert recession.get("healthcare_stable", 0) >= -0.20, \
            "healthcare_stable should be recession-resilient"

    def test_2013_analog_rates_defensives_outperform_leverage(self):
        """In rate shock, defensive compounders should outperform leverage-sensitive."""
        from src.universe.economic_behavior_engine import _REGIME_ARCHETYPE_SENSITIVITIES
        rates = _REGIME_ARCHETYPE_SENSITIVITIES.get("rates_shock", {})
        defensive_impact = rates.get("defensive_compounder", 0)
        leverage_impact = rates.get("leverage_sensitive", 0)
        assert leverage_impact < defensive_impact, (
            f"Leverage-sensitive ({leverage_impact}) should be harder hit than "
            f"defensive compounders ({defensive_impact}) in rate shock"
        )

    def test_balanced_universe_better_regime_diversity(self):
        """Universe with multiple archetype types should have better regime diversification."""
        cyclical_only = ["AMAT", "LRCX", "CAT", "AGX", "EMR"]
        balanced = ["GD", "KO", "V", "AMAT", "KMI"]

        cyclical_result = run_behavior_analysis(cyclical_only, _TAXONOMY_PATH)
        balanced_result = run_behavior_analysis(balanced, _TAXONOMY_PATH)

        assert balanced_result.overall_regime_diversity >= cyclical_result.overall_regime_diversity, (
            f"Balanced universe ({balanced_result.overall_regime_diversity:.2f}) should have "
            f">= regime diversity vs cyclical-only ({cyclical_result.overall_regime_diversity:.2f})"
        )
