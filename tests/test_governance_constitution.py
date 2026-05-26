"""Tests for constitutional risk layer — Component 6.

Validates that:
  - Hard prohibitions are enforced and cannot be bypassed
  - Concentration limits are correctly detected
  - Diversified tickers can still trigger theme/factor violations (anti-delusion)
  - Constitutional report accumulates violations without raising
"""
import pytest
from pathlib import Path
import tempfile
import yaml

from src.governance.constitution import (
    ConstitutionalViolation,
    ConstitutionalReport,
    load_constitution,
    check_position_concentration,
    check_theme_concentration,
    check_factor_concentration,
    check_confidence_quality,
    check_satellite_capital,
    run_all_checks,
    _validate_hard_booleans,
    _HARD_BOOLEANS,
)


def _write_constitution(data: dict, tmp_path: Path) -> Path:
    p = tmp_path / "constitution.yaml"
    with open(p, "w") as f:
        yaml.dump(data, f)
    return p


def _valid_constitution(**overrides) -> dict:
    base = {k: True for k in _HARD_BOOLEANS}
    base.update({
        "MAX_SINGLE_POSITION": 0.10,
        "MAX_SINGLE_THEME_EXPOSURE": 0.25,
        "MAX_SINGLE_FACTOR_EXPOSURE": 0.40,
        "MAX_SATELLITE_CAPITAL": 0.30,
        "WARN_CONFIDENCE_LOW_FRACTION": 0.50,
        "MIN_SIGNAL_QUALITY_THRESHOLD": 0.45,
        "SIGNAL_DECAY_LOOKBACK_WEEKS": 8,
        "MIN_OBSERVATIONS_FOR_CALIBRATION": 20,
    })
    base.update(overrides)
    return base


class TestHardBooleans:
    def test_valid_constitution_loads(self, tmp_path):
        cfg = _valid_constitution()
        p = _write_constitution(cfg, tmp_path)
        loaded = load_constitution(p)
        assert loaded["NO_LEVERAGE"] is True

    def test_no_leverage_false_raises(self, tmp_path):
        cfg = _valid_constitution(NO_LEVERAGE=False)
        p = _write_constitution(cfg, tmp_path)
        with pytest.raises(ConstitutionalViolation, match="NO_LEVERAGE"):
            load_constitution(p)

    def test_autonomous_execution_false_raises(self, tmp_path):
        cfg = _valid_constitution(NO_AUTONOMOUS_EXECUTION=False)
        p = _write_constitution(cfg, tmp_path)
        with pytest.raises(ConstitutionalViolation, match="NO_AUTONOMOUS_EXECUTION"):
            load_constitution(p)

    def test_broker_integration_false_raises(self, tmp_path):
        cfg = _valid_constitution(NO_BROKER_INTEGRATION=False)
        p = _write_constitution(cfg, tmp_path)
        with pytest.raises(ConstitutionalViolation, match="NO_BROKER_INTEGRATION"):
            load_constitution(p)

    def test_self_modifying_rules_false_raises(self, tmp_path):
        cfg = _valid_constitution(NO_SELF_MODIFYING_RISK_RULES=False)
        p = _write_constitution(cfg, tmp_path)
        with pytest.raises(ConstitutionalViolation, match="NO_SELF_MODIFYING_RISK_RULES"):
            load_constitution(p)

    def test_missing_hard_boolean_raises(self):
        cfg = {k: True for k in _HARD_BOOLEANS if k != "NO_LEVERAGE"}
        with pytest.raises(ConstitutionalViolation, match="Missing"):
            _validate_hard_booleans(cfg)

    def test_all_booleans_present_passes(self):
        cfg = {k: True for k in _HARD_BOOLEANS}
        _validate_hard_booleans(cfg)  # should not raise

    def test_empty_constitution_raises(self, tmp_path):
        p = tmp_path / "constitution.yaml"
        p.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_constitution(p)

    def test_nonexistent_constitution_raises(self, tmp_path):
        p = tmp_path / "does_not_exist.yaml"
        with pytest.raises(FileNotFoundError):
            load_constitution(p)


class TestPositionConcentration:
    def test_equal_weight_12_positions_passes(self):
        weights = {t: 1 / 12 for t in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]}
        cfg = _valid_constitution()
        violations = check_position_concentration(weights, cfg)
        assert violations == []

    def test_single_position_over_limit_detected(self):
        weights = {"AAPL": 0.15, "MSFT": 0.085}
        cfg = _valid_constitution()
        violations = check_position_concentration(weights, cfg)
        assert any("AAPL" in v for v in violations)
        assert not any("MSFT" in v for v in violations)

    def test_position_exactly_at_limit_passes(self):
        weights = {"AAPL": 0.10}
        cfg = _valid_constitution()
        assert check_position_concentration(weights, cfg) == []

    def test_empty_portfolio_returns_no_violations(self):
        assert check_position_concentration({}, _valid_constitution()) == []


class TestThemeConcentration:
    def test_infrastructure_epc_exceeds_limit(self):
        # 4/12 positions = 33% — exceeds 25% limit
        theme_weights = {
            "infrastructure_epc": 4 / 12,  # 33%
            "defense_government": 2 / 12,
            "electrical_industrial": 2 / 12,
            "financial_data": 2 / 12,
            "energy_midstream": 2 / 12,
        }
        cfg = _valid_constitution()
        violations = check_theme_concentration(theme_weights, cfg)
        assert any("infrastructure_epc" in v for v in violations)

    def test_balanced_portfolio_passes(self):
        theme_weights = {t: 0.10 for t in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]}
        cfg = _valid_constitution()
        assert check_theme_concentration(theme_weights, cfg) == []

    def test_exactly_at_limit_passes(self):
        cfg = _valid_constitution()
        assert check_theme_concentration({"theme_a": 0.25}, cfg) == []

    def test_just_over_limit_detected(self):
        cfg = _valid_constitution()
        violations = check_theme_concentration({"theme_a": 0.251}, cfg)
        assert len(violations) == 1


class TestConcentrationAntiDelusion:
    """Key anti-delusion tests: hidden concentration despite ticker diversification."""

    def test_power_buildout_hidden_in_diverse_tickers(self):
        """Portfolio with DY, GNRC, HUBB, EMR spans 4 themes but shares power_buildout factor."""
        from src.governance.exposure import compute_theme_weights, compute_factor_weights

        tickers = ["DY", "GNRC", "HUBB", "EMR", "GD", "LDOS", "SPGI", "AMAT",
                   "ACM", "J", "KMI", "TRGP"]
        theme_weights = compute_theme_weights(tickers)
        factor_weights = compute_factor_weights(tickers)

        # Themes look diverse — no single theme exceeds 33%
        max_theme = max(theme_weights.values())
        assert max_theme <= 0.34, f"Unexpected theme dominance: {max_theme}"

        # But power_buildout factor is concentrated
        power_buildout_frac = factor_weights.get("power_buildout", 0.0)
        assert power_buildout_frac > 0.25, (
            f"power_buildout should be flagged but got {power_buildout_frac}"
        )

    def test_defense_factor_detected(self):
        from src.governance.exposure import compute_factor_weights

        # 3 defense tickers out of 6 = 50% — exceeds factor limit
        tickers = ["GD", "LDOS", "LMT", "SPGI", "AMAT", "EMR"]
        factor_weights = compute_factor_weights(tickers)
        cfg = _valid_constitution()
        violations = check_factor_concentration(factor_weights, cfg)
        assert any("us_defense_budget" in v for v in violations), (
            f"Expected us_defense_budget violation, got: {violations}"
        )


class TestConstitutionalReport:
    def test_report_is_compliant_when_no_violations(self):
        report = ConstitutionalReport()
        assert report.is_compliant
        assert not report.has_warnings

    def test_report_not_compliant_with_violations(self):
        report = ConstitutionalReport(violations=["test violation"])
        assert not report.is_compliant

    def test_run_all_checks_never_raises(self):
        # Even with extreme concentrations, run_all_checks returns a report
        position_weights = {"AAPL": 0.90}
        theme_weights = {"tech": 0.90}
        factor_weights = {"ai_capex": 0.90}
        confidence_counts = {"LOW": 10, "MED": 1}
        report = run_all_checks(
            position_weights=position_weights,
            theme_weights=theme_weights,
            factor_weights=factor_weights,
            confidence_counts=confidence_counts,
        )
        assert not report.is_compliant
        assert len(report.violations) >= 2  # position + theme violation

    def test_satellite_capital_violation_detected(self):
        violations = check_satellite_capital(0.55, _valid_constitution())
        assert len(violations) == 1

    def test_satellite_capital_within_limit_passes(self):
        violations = check_satellite_capital(0.25, _valid_constitution())
        assert violations == []


class TestConfidenceQuality:
    def test_high_low_fraction_warns(self):
        counts = {"LOW": 6, "MED": 3, "HIGH": 1}
        cfg = _valid_constitution()
        warnings = check_confidence_quality(counts, cfg)
        assert len(warnings) == 1

    def test_low_fraction_below_threshold_passes(self):
        counts = {"LOW": 3, "MED": 5, "HIGH": 2}
        cfg = _valid_constitution()
        warnings = check_confidence_quality(counts, cfg)
        assert warnings == []

    def test_empty_counts_returns_no_warnings(self):
        assert check_confidence_quality({}, _valid_constitution()) == []
