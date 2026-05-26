"""Tests for src/portfolio/exposure_engine.py

Validates that multi-theme exposure detection:
- Correctly maps tickers to multiple themes simultaneously
- Exposes concentration violations the single-theme model would miss
- Estimates effective diversification correctly
- Surfaces hidden cluster dependencies
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.portfolio.exposure_engine import (
    load_themes,
    build_ticker_theme_map,
    compute_theme_exposure,
    get_cluster_tickers,
    estimate_effective_bets,
    analyze_clusters,
    generate_exposure_warnings,
    run_portfolio_exposure,
    get_theme_limits,
)

# Full paper portfolio
PAPER_TICKERS = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]

_THEMES_PATH = Path(__file__).parent.parent / "config" / "themes.yaml"


# ─── Theme loading ────────────────────────────────────────────────────────────

class TestThemeLoading:
    def test_themes_yaml_loads(self):
        cfg = load_themes(_THEMES_PATH)
        assert "themes" in cfg

    def test_themes_yaml_has_limits(self):
        cfg = load_themes(_THEMES_PATH)
        limits = get_theme_limits(cfg)
        assert limits.get("max_single_theme", 0) > 0

    def test_build_ticker_theme_map(self):
        cfg = load_themes(_THEMES_PATH)
        ttm = build_ticker_theme_map(cfg)
        # All paper portfolio tickers should be in the map
        for ticker in PAPER_TICKERS:
            assert ticker in ttm, f"{ticker} not in themes.yaml"
            assert len(ttm[ticker]) >= 1

    def test_multi_theme_membership(self):
        cfg = load_themes(_THEMES_PATH)
        ttm = build_ticker_theme_map(cfg)
        # KMI should be in at least leverage_sensitive and energy_infrastructure
        assert "leverage_sensitive" in ttm.get("KMI", [])
        assert "energy_infrastructure" in ttm.get("KMI", [])

    def test_trgp_matches_kmi_themes(self):
        cfg = load_themes(_THEMES_PATH)
        ttm = build_ticker_theme_map(cfg)
        kmi_themes = set(ttm.get("KMI", []))
        trgp_themes = set(ttm.get("TRGP", []))
        overlap = kmi_themes & trgp_themes
        assert len(overlap) >= 2, f"KMI/TRGP should share ≥2 themes; shared: {overlap}"

    def test_gd_and_ldos_share_defense_and_govt(self):
        cfg = load_themes(_THEMES_PATH)
        ttm = build_ticker_theme_map(cfg)
        gd_themes = set(ttm.get("GD", []))
        ldos_themes = set(ttm.get("LDOS", []))
        assert "defense" in gd_themes & ldos_themes
        assert "government_spending" in gd_themes & ldos_themes

    def test_missing_file_returns_empty_dict(self):
        cfg = load_themes(Path("/nonexistent/path/themes.yaml"))
        assert cfg == {}


# ─── Theme exposure computation ───────────────────────────────────────────────

class TestThemeExposure:
    def setup_method(self):
        cfg = load_themes(_THEMES_PATH)
        self.ttm = build_ticker_theme_map(cfg)

    def test_exposure_sums_above_one_for_multi_theme(self):
        # With multi-theme membership, total exposure sums >1.0 by design
        exposure = compute_theme_exposure(PAPER_TICKERS, self.ttm)
        total = sum(exposure.values())
        assert total > 1.0, "Multi-theme exposure must sum >1.0 for a real portfolio"

    def test_single_ticker_exposure_is_100pct_per_theme(self):
        exposure = compute_theme_exposure(["KMI"], self.ttm)
        # Each theme KMI belongs to should show 100%
        kmi_themes = self.ttm.get("KMI", [])
        for t in kmi_themes:
            assert abs(exposure.get(t, 0) - 1.0) < 0.01, f"KMI's theme {t} should be 100%"

    def test_government_spending_exceeds_25pct(self):
        # GD, LDOS, ACM, J, DY all share government_spending → should exceed 25%
        exposure = compute_theme_exposure(PAPER_TICKERS, self.ttm)
        assert exposure.get("government_spending", 0) > 0.25, (
            "government_spending must exceed 25% limit to trigger governance alert"
        )

    def test_leverage_cluster_detected(self):
        leverage_tickers = get_cluster_tickers(PAPER_TICKERS, "leverage_sensitive", self.ttm)
        assert len(leverage_tickers) >= 2, "KMI and TRGP should be in leverage cluster"
        assert "KMI" in leverage_tickers
        assert "TRGP" in leverage_tickers

    def test_cyclical_cluster_detected(self):
        cyclical = get_cluster_tickers(PAPER_TICKERS, "cyclical_industrial", self.ttm)
        assert len(cyclical) >= 3, "At least ACM, AMAT, EMR, DY, J should be cyclical"

    def test_empty_portfolio_returns_empty(self):
        assert compute_theme_exposure([], self.ttm) == {}


# ─── Effective diversification ───────────────────────────────────────────────

class TestEffectiveDiversification:
    def setup_method(self):
        cfg = load_themes(_THEMES_PATH)
        self.ttm = build_ticker_theme_map(cfg)

    def test_effective_bets_less_than_position_count(self):
        eff, clusters = estimate_effective_bets(PAPER_TICKERS, self.ttm)
        assert eff < len(PAPER_TICKERS), (
            f"Effective bets ({eff}) should be < 12 positions due to thematic overlap"
        )

    def test_kmi_trgp_cluster_together(self):
        eff, clusters = estimate_effective_bets(["KMI", "TRGP"], self.ttm)
        # Should be less than 2 (they're the same macro bet)
        assert eff < 2.0, f"KMI and TRGP are one macro bet, not two; got effective={eff}"

    def test_gd_ldos_cluster_together(self):
        eff, clusters = estimate_effective_bets(["GD", "LDOS"], self.ttm)
        assert eff < 2.0, f"GD and LDOS are one macro bet; got effective={eff}"

    def test_fully_diverse_portfolio_has_higher_eff(self):
        # Portfolio with no theme overlap should have higher effective bets
        diverse = ["GD", "AMAT", "KMI", "SPGI"]
        concentrated = ["ACM", "DY", "J", "EMR"]  # all infra/cyclical
        eff_diverse, _ = estimate_effective_bets(diverse, self.ttm)
        eff_concentrated, _ = estimate_effective_bets(concentrated, self.ttm)
        assert eff_diverse > eff_concentrated, (
            f"Diverse portfolio ({eff_diverse}) should have more effective bets "
            f"than concentrated ({eff_concentrated})"
        )

    def test_clusters_returned(self):
        _, clusters = estimate_effective_bets(PAPER_TICKERS, self.ttm)
        assert isinstance(clusters, list)
        assert len(clusters) >= 1
        # All tickers should appear in exactly one cluster
        all_in_clusters = [t for c in clusters for t in c]
        assert set(all_in_clusters) == {t.upper() for t in PAPER_TICKERS}


# ─── Cluster analysis ─────────────────────────────────────────────────────────

class TestClusterAnalysis:
    def setup_method(self):
        cfg = load_themes(_THEMES_PATH)
        self.ttm = build_ticker_theme_map(cfg)
        self.limits = get_theme_limits(cfg)

    def test_leverage_cluster_breached(self):
        clusters = analyze_clusters(PAPER_TICKERS, self.ttm, self.limits)
        lev = clusters["leverage_cluster"]
        assert lev["breached"], (
            f"Leverage cluster is {lev['exposure']:.0%} for paper portfolio "
            f"(KMI, TRGP, GNRC) — should breach {lev['limit']:.0%} limit"
        )

    def test_policy_cluster_breached(self):
        clusters = analyze_clusters(PAPER_TICKERS, self.ttm, self.limits)
        pol = clusters["policy_cluster"]
        assert pol["breached"], (
            f"Policy cluster {pol['exposure']:.0%} should breach {pol['limit']:.0%} limit"
        )

    def test_cyclical_cluster_breached(self):
        clusters = analyze_clusters(PAPER_TICKERS, self.ttm, self.limits)
        cyc = clusters["cyclical_cluster"]
        assert cyc["breached"], (
            f"Cyclical cluster {cyc['exposure']:.0%} should breach {cyc['limit']:.0%} limit"
        )

    def test_clean_portfolio_no_breach(self):
        # GD + SPGI + KMI = different clusters, modest concentration
        clean = ["GD", "SPGI", "KMI"]
        clusters = analyze_clusters(clean, self.ttm, self.limits)
        # None of these should breach limits with only 3 carefully chosen tickers
        assert not clusters["cyclical_cluster"]["breached"]


# ─── Full portfolio run ───────────────────────────────────────────────────────

class TestRunPortfolioExposure:
    def test_returns_expected_keys(self):
        result = run_portfolio_exposure(PAPER_TICKERS, _THEMES_PATH)
        for key in ("tickers", "n_positions", "effective_bets", "theme_exposure",
                    "leverage_cluster", "policy_cluster", "cyclical_cluster",
                    "macro_clusters", "hidden_dependencies", "warnings", "narrative"):
            assert key in result, f"Missing key: {key}"

    def test_n_positions_correct(self):
        result = run_portfolio_exposure(PAPER_TICKERS, _THEMES_PATH)
        assert result["n_positions"] == 12

    def test_warnings_include_blocks(self):
        result = run_portfolio_exposure(PAPER_TICKERS, _THEMES_PATH)
        blocks = [w for w in result["warnings"] if "[BLOCK]" in w]
        assert len(blocks) >= 1, "Paper portfolio should produce at least 1 BLOCK warning"

    def test_hidden_dependencies_populated(self):
        result = run_portfolio_exposure(PAPER_TICKERS, _THEMES_PATH)
        assert len(result["hidden_dependencies"]) >= 1

    def test_narrative_mentions_effective_bets(self):
        result = run_portfolio_exposure(PAPER_TICKERS, _THEMES_PATH)
        narrative = result["narrative"]
        assert "effective" in narrative.lower() or "macro" in narrative.lower()

    def test_empty_portfolio(self):
        result = run_portfolio_exposure([], _THEMES_PATH)
        assert result["n_positions"] == 0
        assert result["theme_exposure"] == {}
