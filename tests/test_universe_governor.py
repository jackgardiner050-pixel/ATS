"""Tests for src/universe/universe_governor.py

Validates:
- Current universe triggers cyclical concentration warnings
- Absent archetypes are flagged as gaps
- Small/balanced sub-portfolios have fewer warnings
- Governance result has required fields
- Edge cases: empty universe, single archetype universe
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.universe.universe_governor import assess_universe_balance, UniverseGovernanceResult

_TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "universe_taxonomy.yaml"
_UNIVERSE_PATH = Path(__file__).parent.parent / "config" / "universe.yaml"

import yaml
with open(_UNIVERSE_PATH) as f:
    _UNIVERSE_CFG = yaml.safe_load(f)
CURRENT_UNIVERSE = [t.upper() for t in _UNIVERSE_CFG.get("universe", [])]

# Balanced subset: defense + consumer_staples + healthcare + financial + software
BALANCED_SUBSET = ["GD", "LDOS", "KO", "PG", "V", "MA", "SYK", "MDT", "SPGI", "ORCL"]

# Cyclical-only subset
CYCLICAL_SUBSET = ["AMAT", "LRCX", "KLAC", "CAT", "AGX", "EMR", "HON", "FIX", "ACM", "DY", "VMC"]


class TestCurrentUniverseGovernance:
    def test_governance_result_is_correct_type(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert isinstance(result, UniverseGovernanceResult)

    def test_current_universe_has_warnings(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        # Universe with 143 tickers will have concentration warnings
        assert len(result.warnings) >= 1 or len(result.gap_alerts) >= 1, \
            "Current universe should have at least one warning or gap alert"

    def test_current_universe_has_cyclical_warning(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        cyclical_warns = [w for w in result.warnings if "cyclical" in w.lower()]
        cyclical_overrep = "cyclical_industrial" in result.overrepresented_archetypes
        # Either a warning OR an overrepresented flag — one of them must fire
        assert cyclical_warns or cyclical_overrep, (
            f"cyclical_industrial at {result.archetype_fractions.get('cyclical_industrial', 0):.1%} "
            f"should trigger warning or overrepresented flag; warnings={result.warnings[:2]}"
        )

    def test_regulated_utility_gap_detected(self):
        # NEE added 2026-05-26 fills absent → archetype is now underrepresented (<3%)
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert "regulated_utility" in result.underrepresented_archetypes, (
            f"regulated_utility at {result.archetype_fractions.get('regulated_utility', 0):.1%} "
            f"should be underrepresented; underrepresented: {result.underrepresented_archetypes}"
        )

    def test_asset_manager_gap_detected(self):
        # CME + BLK added 2026-05-26 — archetype is now underrepresented (<3%)
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert "asset_manager" in result.underrepresented_archetypes, (
            f"asset_manager at {result.archetype_fractions.get('asset_manager', 0):.1%} "
            f"should be underrepresented; underrepresented: {result.underrepresented_archetypes}"
        )

    def test_thin_archetypes_flagged(self):
        # After 2026-05-26 additions, no archetypes are fully absent but several are thin
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert len(result.underrepresented_archetypes) >= 2, (
            "regulated_utility, asset_manager, and financial_data should be flagged as underrepresented"
        )

    def test_gap_alerts_non_empty(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert len(result.gap_alerts) >= 2

    def test_governance_result_has_required_fields(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        assert result.n_tickers == len(CURRENT_UNIVERSE)
        assert isinstance(result.archetype_fractions, dict)
        assert isinstance(result.warnings, list)
        assert isinstance(result.gap_alerts, list)
        assert isinstance(result.overrepresented_archetypes, list)
        assert isinstance(result.absent_archetypes, list)
        assert isinstance(result.cyclical_fraction, float)
        assert isinstance(result.defensive_fraction, float)
        assert 0.0 <= result.diversity_score <= 1.0

    def test_archetype_fractions_in_range(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        for archetype, frac in result.archetype_fractions.items():
            assert 0.0 <= frac <= 1.0, f"{archetype} fraction {frac} out of range"

    def test_escalation_triggered_for_current_universe(self):
        result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        # Should have escalation due to missing regulated_utility and asset_manager
        assert result.escalation_required or len(result.gap_alerts) >= 1


class TestBalancedSubsetGovernance:
    def test_balanced_subset_has_fewer_warnings(self):
        full_result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        balanced_result = assess_universe_balance(BALANCED_SUBSET, _TAXONOMY_PATH)
        # Balanced subset should have fewer concentration warnings
        assert len(balanced_result.warnings) <= len(full_result.warnings)

    def test_cyclical_subset_has_high_cyclical_fraction(self):
        result = assess_universe_balance(CYCLICAL_SUBSET, _TAXONOMY_PATH)
        # All tickers are cyclical_industrial → very high cyclical fraction
        assert result.cyclical_fraction > 0.80, (
            f"Cyclical-only subset should have >80% cyclical fraction; got {result.cyclical_fraction}"
        )

    def test_cyclical_subset_has_cyclical_warning(self):
        result = assess_universe_balance(CYCLICAL_SUBSET, _TAXONOMY_PATH)
        cyclical_warns = [w for w in result.warnings if "cyclical" in w.lower()]
        cyclical_overrep = "cyclical_industrial" in result.overrepresented_archetypes
        assert cyclical_warns or cyclical_overrep, \
            "All-cyclical subset must trigger cyclical concentration warning"


class TestEdgeCases:
    def test_empty_universe_returns_result(self):
        result = assess_universe_balance([], _TAXONOMY_PATH)
        assert result.n_tickers == 0
        assert isinstance(result.absent_archetypes, list)

    def test_empty_universe_has_gaps(self):
        result = assess_universe_balance([], _TAXONOMY_PATH)
        assert len(result.absent_archetypes) >= 5

    def test_single_defensive_ticker(self):
        result = assess_universe_balance(["KO"], _TAXONOMY_PATH)
        assert result.n_tickers == 1
        # KO is defensive, cyclical fraction should be low
        assert result.cyclical_fraction <= 0.10

    def test_single_cyclical_ticker(self):
        result = assess_universe_balance(["AMAT"], _TAXONOMY_PATH)
        assert result.cyclical_fraction > 0.50

    def test_diversity_score_lower_for_cyclical_subset(self):
        full_result = assess_universe_balance(CURRENT_UNIVERSE, _TAXONOMY_PATH)
        cyclical_result = assess_universe_balance(CYCLICAL_SUBSET, _TAXONOMY_PATH)
        assert cyclical_result.diversity_score <= full_result.diversity_score

    def test_governance_with_taxonomy_path(self):
        result = assess_universe_balance(BALANCED_SUBSET, _TAXONOMY_PATH)
        assert result is not None
        assert isinstance(result, UniverseGovernanceResult)
