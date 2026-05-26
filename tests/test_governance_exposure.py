"""Tests for portfolio exposure intelligence — Component 2.

Key anti-delusion test:
  - Detect hidden concentration despite ticker diversification
  - A portfolio spanning 4 themes can still violate a single factor limit

Validates:
  - Theme weights sum to 1.0
  - Factor weights correctly identify cross-cutting exposure
  - Warnings generated for violations
  - Correlation cluster detection
  - Unknown tickers handled gracefully
"""
import pytest
from src.governance.exposure import (
    compute_theme_weights,
    compute_factor_weights,
    detect_correlation_clusters,
    generate_exposure_warnings,
    THEME_MEMBERSHIP,
    FACTOR_MEMBERSHIP,
    FACTOR_DESCRIPTIONS,
)


class TestThemeWeights:
    def test_weights_sum_to_one(self):
        tickers = ["ACM", "GD", "AMAT", "KMI", "SPGI", "DHR", "EMR", "VRT",
                   "HUBB", "LDOS", "J", "TRGP"]
        weights = compute_theme_weights(tickers)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_all_tickers_in_paper_portfolio_are_mapped(self):
        paper_tickers = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB",
                         "J", "KMI", "LDOS", "SPGI", "TRGP"]
        weights = compute_theme_weights(paper_tickers)
        assert "unknown" not in weights, (
            f"Unmapped tickers in paper portfolio: check THEME_MEMBERSHIP"
        )

    def test_unknown_ticker_goes_to_unknown_bucket(self):
        weights = compute_theme_weights(["AAPL"])
        assert "unknown" in weights

    def test_empty_portfolio_returns_empty(self):
        assert compute_theme_weights([]) == {}

    def test_single_ticker_gives_100pct_theme(self):
        weights = compute_theme_weights(["GD"])
        assert weights.get("defense_government", 0) == pytest.approx(1.0)

    def test_two_same_theme_gives_100pct(self):
        weights = compute_theme_weights(["GD", "LDOS"])
        assert weights.get("defense_government", 0) == pytest.approx(1.0)

    def test_two_different_themes_gives_50pct_each(self):
        weights = compute_theme_weights(["GD", "AMAT"])
        assert weights.get("defense_government", 0) == pytest.approx(0.5)
        assert weights.get("semicap_equipment", 0) == pytest.approx(0.5)


class TestFactorWeights:
    def test_power_buildout_detected_in_paper_portfolio(self):
        """DY, GNRC, HUBB, EMR all contribute to power_buildout."""
        paper_tickers = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB",
                         "J", "KMI", "LDOS", "SPGI", "TRGP"]
        weights = compute_factor_weights(paper_tickers)
        power = weights.get("power_buildout", 0.0)
        # DY, GNRC, HUBB, EMR = 4 tickers out of 12 = 33%
        assert power >= 0.25, f"Expected power_buildout >= 25%, got {power:.1%}"

    def test_defense_factor_detected(self):
        tickers = ["GD", "LDOS", "LMT", "SPGI", "AMAT", "EMR"]
        weights = compute_factor_weights(tickers)
        defense = weights.get("us_defense_budget", 0.0)
        assert defense > 0.40, f"Expected defense > 40%, got {defense:.1%}"

    def test_empty_returns_empty(self):
        assert compute_factor_weights([]) == {}

    def test_tickers_not_in_any_factor_return_empty(self):
        # A ticker that isn't in any factor definition
        weights = compute_factor_weights(["UNKNOWN_TICKER"])
        assert weights == {}

    def test_ticker_can_appear_in_multiple_factors(self):
        # VRT appears in both power_buildout and ai_capex
        tickers = ["VRT"]
        weights = compute_factor_weights(tickers)
        assert "power_buildout" in weights
        assert "ai_capex_cycle" in weights


class TestHiddenConcentrationAntiDelusion:
    """Core anti-delusion tests: hidden factor concentration despite theme diversity."""

    def test_paper_portfolio_theme_looks_diverse(self):
        """Paper portfolio has 8 different themes — looks diversified."""
        paper_tickers = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB",
                         "J", "KMI", "LDOS", "SPGI", "TRGP"]
        theme_weights = compute_theme_weights(paper_tickers)
        # No single theme should exceed 35%
        max_theme_w = max(theme_weights.values())
        assert max_theme_w <= 0.35, f"Single theme dominates: {theme_weights}"

    def test_paper_portfolio_hides_power_buildout_concentration(self):
        """Same portfolio hides power_buildout exposure across multiple themes."""
        paper_tickers = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB",
                         "J", "KMI", "LDOS", "SPGI", "TRGP"]
        factor_weights = compute_factor_weights(paper_tickers)
        power = factor_weights.get("power_buildout", 0.0)
        # Power buildout spans DY (infra), GNRC (power gen), HUBB (electrical), EMR (industrial)
        assert power > 0.25, (
            f"Hidden power_buildout concentration not detected: {power:.1%}"
        )

    def test_infrastructure_spending_factor_high(self):
        """ACM, DY, J together create infrastructure_spending concentration."""
        paper_tickers = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB",
                         "J", "KMI", "LDOS", "SPGI", "TRGP"]
        factor_weights = compute_factor_weights(paper_tickers)
        infra = factor_weights.get("us_infrastructure_spending", 0.0)
        # ACM, DY, J = 3/12 = 25%
        assert infra >= 0.20, f"Infrastructure factor not detected: {infra:.1%}"


class TestConcentrationWarnings:
    def test_theme_violation_generates_violation_string(self):
        theme_weights = {"infrastructure_epc": 0.35}
        factor_weights = {}
        correlations = {}
        warnings = generate_exposure_warnings(theme_weights, factor_weights, correlations)
        assert any("[VIOLATION]" in w and "infrastructure_epc" in w for w in warnings)

    def test_theme_approaching_limit_generates_watch(self):
        theme_weights = {"defense_government": 0.22}
        warnings = generate_exposure_warnings(theme_weights, {}, {})
        assert any("[WATCH]" in w and "defense_government" in w for w in warnings)

    def test_factor_violation_generates_violation_string(self):
        factor_weights = {"power_buildout": 0.45}
        warnings = generate_exposure_warnings({}, factor_weights, {})
        assert any("[VIOLATION]" in w and "power_buildout" in w for w in warnings)

    def test_compliant_portfolio_generates_no_violations(self):
        theme_weights = {t: 0.10 for t in ["a", "b", "c", "d", "e"]}
        factor_weights = {"power_buildout": 0.20}
        warnings = generate_exposure_warnings(theme_weights, factor_weights, {})
        assert not any("[VIOLATION]" in w for w in warnings)

    def test_unknown_theme_not_flagged(self):
        theme_weights = {"unknown": 0.50}
        warnings = generate_exposure_warnings(theme_weights, {}, {})
        assert not any("[VIOLATION]" in w and "unknown" in w for w in warnings)


class TestCorrelationClusters:
    def test_highly_correlated_pairs_form_cluster(self):
        correlations = {
            "A_B": 0.85,
            "A_C": 0.80,
            "B_C": 0.90,
        }
        clusters = detect_correlation_clusters(correlations, threshold=0.70)
        assert len(clusters) == 1
        assert set(clusters[0]) == {"A", "B", "C"}

    def test_low_correlation_creates_no_cluster(self):
        correlations = {"A_B": 0.30, "C_D": 0.25}
        clusters = detect_correlation_clusters(correlations, threshold=0.70)
        assert clusters == []

    def test_split_clusters_detected_separately(self):
        correlations = {
            "A_B": 0.85,
            "A_C": 0.82,
            "D_E": 0.80,
        }
        clusters = detect_correlation_clusters(correlations, threshold=0.70)
        assert len(clusters) == 2

    def test_large_cluster_flagged_as_warning(self):
        correlations = {
            "A_B": 0.80, "A_C": 0.80, "A_D": 0.80,
            "B_C": 0.80, "B_D": 0.80, "C_D": 0.80,
        }
        clusters = detect_correlation_clusters(correlations, threshold=0.70)
        warnings = generate_exposure_warnings({}, {}, correlations)
        assert any("Correlation cluster" in w for w in warnings)

    def test_empty_correlations_returns_empty(self):
        assert detect_correlation_clusters({}, threshold=0.70) == []


class TestThemeMembershipCoverage:
    def test_all_universe_tickers_are_mapped(self):
        universe = [
            "AGX", "PWR", "MTZ", "PRIM", "EME", "FIX", "IESC", "STRL", "DY",
            "VRT", "MOD", "CAT", "ETN", "TT", "HUBB", "AME", "ROK", "GNRC",
            "LMT", "RTX", "NOC", "GD", "LDOS", "AMAT", "LRCX", "KLAC", "ENTG",
            "DHR", "TMO", "A", "LLY", "ABBV", "WMB", "KMI", "OKE", "TRGP",
            "HON", "GE", "ITW", "EMR", "PH", "DOV", "V", "MA", "SPGI", "MCO",
            "MSCI", "MLM", "VMC", "EXP", "J", "ACM", "FLR", "HII", "KTOS",
            "AVAV", "ISRG", "IDXX", "ZTS", "MTD",
        ]
        unmapped = [t for t in universe if t not in THEME_MEMBERSHIP]
        assert not unmapped, f"Universe tickers not in THEME_MEMBERSHIP: {unmapped}"
