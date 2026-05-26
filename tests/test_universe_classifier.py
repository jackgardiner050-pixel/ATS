"""Tests for src/universe/universe_classifier.py

Validates:
- Taxonomy loads and maps archetypes correctly
- Known tickers have expected archetype memberships
- Derived characteristic scores are directionally correct
- Behavioral similarity is higher for economically similar tickers
- Unknown tickers get neutral defaults
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.universe.universe_classifier import (
    load_taxonomy,
    load_current_universe,
    build_ticker_archetype_map,
    classify_ticker,
    classify_universe,
    ARCHETYPE_CHARACTERISTICS,
    CHARACTERISTIC_NAMES,
)
from src.universe.economic_behavior_engine import (
    _jaccard_similarity,
    run_behavior_analysis,
)

_TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "universe_taxonomy.yaml"
_UNIVERSE_PATH = Path(__file__).parent.parent / "config" / "universe.yaml"


@pytest.fixture(scope="module")
def taxonomy_cfg():
    return load_taxonomy(_TAXONOMY_PATH)


@pytest.fixture(scope="module")
def archetype_map(taxonomy_cfg):
    return build_ticker_archetype_map(taxonomy_cfg)


@pytest.fixture(scope="module")
def current_universe():
    return load_current_universe(_UNIVERSE_PATH)


# ─── Taxonomy structure ───────────────────────────────────────────────────────

class TestTaxonomyStructure:
    def test_taxonomy_loads(self, taxonomy_cfg):
        assert taxonomy_cfg, "Taxonomy must load non-empty"
        assert "archetypes" in taxonomy_cfg

    def test_taxonomy_has_required_archetypes(self, taxonomy_cfg):
        archetypes = set(taxonomy_cfg["archetypes"].keys())
        required = {
            "defensive_compounder", "cyclical_industrial", "AI_capex",
            "consumer_staples", "healthcare_stable", "regulated_utility",
            "software_platform", "financial_data", "payments_network",
            "quality_compounder", "global_diversifier", "energy_infrastructure",
            "leverage_sensitive", "policy_sensitive",
        }
        for a in required:
            assert a in archetypes, f"Missing required archetype: {a}"

    def test_taxonomy_has_limits(self, taxonomy_cfg):
        limits = taxonomy_cfg.get("limits", {})
        assert "max_cyclical_fraction" in limits
        assert "max_archetype_fraction" in limits
        assert "min_defensive_fraction" in limits

    def test_each_archetype_has_tickers(self, taxonomy_cfg):
        for name, data in taxonomy_cfg["archetypes"].items():
            assert data.get("tickers"), f"Archetype '{name}' has no tickers"

    def test_each_archetype_has_cyclicality_score(self, taxonomy_cfg):
        for name, data in taxonomy_cfg["archetypes"].items():
            assert "cyclicality" in data, f"Archetype '{name}' missing cyclicality"
            assert 0.0 <= data["cyclicality"] <= 1.0

    def test_each_archetype_has_defensiveness_score(self, taxonomy_cfg):
        for name, data in taxonomy_cfg["archetypes"].items():
            assert "defensiveness" in data, f"Archetype '{name}' missing defensiveness"
            assert 0.0 <= data["defensiveness"] <= 1.0


# ─── Known archetype memberships ─────────────────────────────────────────────

class TestKnownArchetypeMemberships:
    def test_v_ma_in_payments_network(self, archetype_map):
        for ticker in ("V", "MA"):
            assert "payments_network" in archetype_map.get(ticker, []), \
                f"{ticker} must be in payments_network"

    def test_v_ma_in_capital_light(self, archetype_map):
        for ticker in ("V", "MA"):
            assert "capital_light" in archetype_map.get(ticker, []), \
                f"{ticker} must be in capital_light"

    def test_kmi_in_leverage_sensitive(self, archetype_map):
        assert "leverage_sensitive" in archetype_map.get("KMI", [])

    def test_kmi_in_energy_infrastructure(self, archetype_map):
        assert "energy_infrastructure" in archetype_map.get("KMI", [])

    def test_gd_in_defense(self, archetype_map):
        assert "defense" in archetype_map.get("GD", [])

    def test_gd_in_recession_resilient(self, archetype_map):
        assert "recession_resilient" in archetype_map.get("GD", [])

    def test_spgi_in_financial_data(self, archetype_map):
        assert "financial_data" in archetype_map.get("SPGI", [])

    def test_spgi_in_quality_compounder(self, archetype_map):
        assert "quality_compounder" in archetype_map.get("SPGI", [])

    def test_ko_in_consumer_staples(self, archetype_map):
        assert "consumer_staples" in archetype_map.get("KO", [])

    def test_ko_in_recession_resilient(self, archetype_map):
        assert "recession_resilient" in archetype_map.get("KO", [])

    def test_amat_in_ai_capex(self, archetype_map):
        assert "AI_capex" in archetype_map.get("AMAT", [])

    def test_amat_in_cyclical_industrial(self, archetype_map):
        assert "cyclical_industrial" in archetype_map.get("AMAT", [])

    def test_cost_in_consumer_staples(self, archetype_map):
        assert "consumer_staples" in archetype_map.get("COST", [])

    def test_multiarchetype_membership(self, archetype_map):
        # V belongs to multiple archetypes — this is the core design
        v_archetypes = archetype_map.get("V", [])
        assert len(v_archetypes) >= 4, f"V should have ≥4 archetypes; got {v_archetypes}"


# ─── Derived characteristic scores ───────────────────────────────────────────

class TestDerivedCharacteristics:
    def test_gd_low_cyclicality(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("GD", archetype_map, taxonomy_cfg, current_universe)
        assert c.cyclicality_score < 0.40, \
            f"GD (defense/recession_resilient) should have low cyclicality; got {c.cyclicality_score}"

    def test_amat_high_cyclicality(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("AMAT", archetype_map, taxonomy_cfg, current_universe)
        assert c.cyclicality_score > 0.70, \
            f"AMAT (AI_capex + cyclical_industrial) should have high cyclicality; got {c.cyclicality_score}"

    def test_ko_high_defensiveness(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("KO", archetype_map, taxonomy_cfg, current_universe)
        assert c.defensiveness_score > 0.70, \
            f"KO (consumer_staples + recession_resilient) should be highly defensive; got {c.defensiveness_score}"

    def test_kmi_high_leverage_sensitivity(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("KMI", archetype_map, taxonomy_cfg, current_universe)
        assert c.leverage_sensitivity > 0.55, \
            f"KMI (leverage_sensitive + energy_infrastructure) should have high leverage sensitivity; got {c.leverage_sensitivity}"

    def test_gd_high_policy_sensitivity(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("GD", archetype_map, taxonomy_cfg, current_universe)
        assert c.policy_sensitivity > 0.55, \
            f"GD (defense + government_spending + policy_sensitive) should have high policy sensitivity; got {c.policy_sensitivity}"

    def test_all_scores_in_range(self, archetype_map, taxonomy_cfg, current_universe):
        for ticker in ["GD", "AMAT", "KO", "V", "KMI", "SPGI", "LMT", "PG"]:
            c = classify_ticker(ticker, archetype_map, taxonomy_cfg, current_universe)
            for attr in CHARACTERISTIC_NAMES:
                val = c.characteristics.get(attr, 0.5)
                assert 0.0 <= val <= 1.0, f"{ticker}.{attr} = {val} out of [0,1]"

    def test_unknown_ticker_returns_neutral(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("UNKN", archetype_map, taxonomy_cfg, current_universe)
        assert c.cyclicality_score == 0.50
        assert c.defensiveness_score == 0.50
        assert c.archetype_memberships == []

    def test_defense_more_defensive_than_cyclical(self, archetype_map, taxonomy_cfg, current_universe):
        gd = classify_ticker("GD", archetype_map, taxonomy_cfg, current_universe)
        amat = classify_ticker("AMAT", archetype_map, taxonomy_cfg, current_universe)
        assert gd.defensiveness_score > amat.defensiveness_score

    def test_consumer_staples_less_cyclical_than_semcap(self, archetype_map, taxonomy_cfg, current_universe):
        ko = classify_ticker("KO", archetype_map, taxonomy_cfg, current_universe)
        amat = classify_ticker("AMAT", archetype_map, taxonomy_cfg, current_universe)
        assert ko.cyclicality_score < amat.cyclicality_score

    def test_ticker_classification_has_required_fields(self, archetype_map, taxonomy_cfg, current_universe):
        c = classify_ticker("V", archetype_map, taxonomy_cfg, current_universe)
        assert hasattr(c, "ticker")
        assert hasattr(c, "archetype_memberships")
        assert hasattr(c, "cyclicality_score")
        assert hasattr(c, "defensiveness_score")
        assert hasattr(c, "recession_sensitivity")
        assert hasattr(c, "policy_sensitivity")
        assert hasattr(c, "leverage_sensitivity")
        assert hasattr(c, "capital_intensity")
        assert hasattr(c, "diversification_contribution")
        assert hasattr(c, "in_current_universe")


# ─── Behavioral similarity ────────────────────────────────────────────────────

class TestBehavioralSimilarity:
    def test_amat_lrcx_highly_similar(self, archetype_map):
        # Both AI_capex + cyclical_industrial → high similarity
        sim = _jaccard_similarity(
            archetype_map.get("AMAT", []),
            archetype_map.get("LRCX", []),
        )
        assert sim > 0.50, f"AMAT and LRCX should be highly similar; got {sim}"

    def test_gd_ko_dissimilar(self, archetype_map):
        # Defense vs consumer_staples → low similarity
        sim = _jaccard_similarity(
            archetype_map.get("GD", []),
            archetype_map.get("KO", []),
        )
        assert sim < 0.35, f"GD and KO should be dissimilar; got {sim}"

    def test_kmi_trgp_similar(self, archetype_map):
        # Both midstream leverage-sensitive
        sim = _jaccard_similarity(
            archetype_map.get("KMI", []),
            archetype_map.get("TRGP", []),
        )
        assert sim > 0.50, f"KMI and TRGP should be similar; got {sim}"

    def test_spgi_mco_similar(self, archetype_map):
        # Both financial data compounders
        sim = _jaccard_similarity(
            archetype_map.get("SPGI", []),
            archetype_map.get("MCO", []),
        )
        assert sim > 0.50, f"SPGI and MCO should be similar; got {sim}"

    def test_v_amat_dissimilar(self, archetype_map):
        # Payments network vs semiconductor capex
        sim = _jaccard_similarity(
            archetype_map.get("V", []),
            archetype_map.get("AMAT", []),
        )
        assert sim < 0.30, f"V and AMAT should be dissimilar; got {sim}"

    def test_behavior_analysis_runs(self, current_universe):
        tickers = current_universe[:20]  # sample
        result = run_behavior_analysis(tickers, _TAXONOMY_PATH)
        assert result.n_tickers == len(tickers)
        assert result.n_behavior_clusters >= 1
        assert 0.0 <= result.max_similarity <= 1.0
        assert result.effective_economic_bets > 0

    def test_classify_universe_returns_all_tickers(self, current_universe):
        sample = current_universe[:15]
        classifications = classify_universe(sample, _TAXONOMY_PATH, _UNIVERSE_PATH)
        assert len(classifications) == len(sample)
        for ticker in sample:
            assert ticker.upper() in classifications
