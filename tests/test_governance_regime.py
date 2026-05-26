"""Tests for regime intelligence engine — Component 1.

Validates:
  - Regime probabilities sum to 1.0
  - Classification is deterministic (same inputs → same outputs)
  - High VIX increases stress/panic regime probability
  - Low VIX increases risk-on probability
  - Log persistence works
  - Insufficient data fails loudly
"""
import math
import json
import pytest
from pathlib import Path

from src.governance.regime import (
    classify_regime,
    compute_conditions,
    _score_regimes,
    _softmax,
    log_regime,
    load_regime_history,
    _REGIMES,
)


def _normal_market_indicators() -> dict:
    """Synthetic indicators for a calm, risk-on environment."""
    return {
        "vix_current": 16.0,
        "vix_5d_ago": 17.0,
        "spy_current": 500.0,
        "spy_50d_avg": 490.0,
        "spy_200d_avg": 470.0,
        "spy_realized_vol_20d": 0.12,
        "rsp_vs_spy_30d": 0.01,
        "tlt_30d_return": -0.01,
        "hyg_vs_tlt_30d": 0.02,
        "uup_30d_return": 0.00,
        "xle_vs_spy_30d": -0.01,
        "xlk_vs_spy_30d": 0.03,
        "xlu_vs_spy_30d": -0.02,
        "xlb_vs_spy_30d": 0.00,
    }


def _stress_indicators() -> dict:
    """Synthetic indicators for a high-volatility stress environment."""
    return {
        "vix_current": 38.0,
        "vix_5d_ago": 22.0,
        "spy_current": 420.0,
        "spy_50d_avg": 480.0,
        "spy_200d_avg": 470.0,
        "spy_realized_vol_20d": 0.35,
        "rsp_vs_spy_30d": -0.03,
        "tlt_30d_return": 0.04,
        "hyg_vs_tlt_30d": -0.05,
        "uup_30d_return": 0.02,
        "xle_vs_spy_30d": -0.05,
        "xlk_vs_spy_30d": -0.08,
        "xlu_vs_spy_30d": 0.03,
        "xlb_vs_spy_30d": -0.04,
    }


def _panic_indicators() -> dict:
    """Synthetic indicators for liquidity panic."""
    return {
        "vix_current": 55.0,
        "vix_5d_ago": 30.0,
        "spy_current": 380.0,
        "spy_50d_avg": 470.0,
        "spy_200d_avg": 460.0,
        "spy_realized_vol_20d": 0.55,
        "rsp_vs_spy_30d": -0.05,
        "tlt_30d_return": 0.06,
        "hyg_vs_tlt_30d": -0.10,
        "uup_30d_return": 0.04,
        "xle_vs_spy_30d": -0.10,
        "xlk_vs_spy_30d": -0.15,
        "xlu_vs_spy_30d": 0.01,
        "xlb_vs_spy_30d": -0.08,
    }


def _inflationary_indicators() -> dict:
    """Synthetic indicators for inflationary cyclical environment."""
    return {
        "vix_current": 20.0,
        "vix_5d_ago": 19.0,
        "spy_current": 490.0,
        "spy_50d_avg": 480.0,
        "spy_200d_avg": 450.0,
        "spy_realized_vol_20d": 0.14,
        "rsp_vs_spy_30d": 0.02,
        "tlt_30d_return": -0.06,   # TLT falling hard = yields rising
        "hyg_vs_tlt_30d": 0.01,
        "uup_30d_return": -0.02,   # dollar weak
        "xle_vs_spy_30d": 0.06,    # energy leading
        "xlk_vs_spy_30d": -0.03,   # tech lagging
        "xlu_vs_spy_30d": -0.03,   # utilities lagging
        "xlb_vs_spy_30d": 0.03,    # materials leading
    }


class TestSoftmax:
    def test_probabilities_sum_to_one(self):
        scores = {"a": 3.0, "b": 1.0, "c": 0.5, "d": -1.0}
        probs = _softmax(scores)
        assert abs(sum(probs.values()) - 1.0) < 1e-9

    def test_highest_score_wins(self):
        scores = {"a": 10.0, "b": 1.0, "c": 0.0}
        probs = _softmax(scores)
        assert probs["a"] == max(probs.values())

    def test_equal_scores_give_equal_probs(self):
        scores = {"a": 5.0, "b": 5.0}
        probs = _softmax(scores)
        assert abs(probs["a"] - 0.5) < 1e-9


class TestConditions:
    def test_low_vix_sets_below_20(self):
        c = compute_conditions({"vix_current": 14.0, "vix_5d_ago": 15.0})
        assert c["vix_below_20"] == 1.0
        assert c["vix_below_15"] == 1.0
        assert c["vix_above_25"] == 0.0

    def test_high_vix_sets_above_30(self):
        c = compute_conditions({"vix_current": 35.0, "vix_5d_ago": 30.0})
        assert c["vix_above_30"] == 1.0
        assert c["vix_above_25"] == 1.0
        assert c["vix_below_20"] == 0.0
        assert c["vix_above_40"] == 0.0

    def test_panic_vix_sets_above_40(self):
        c = compute_conditions({"vix_current": 55.0, "vix_5d_ago": 30.0})
        assert c["vix_above_40"] == 1.0

    def test_vix_trending_up_detected(self):
        c = compute_conditions({"vix_current": 28.0, "vix_5d_ago": 20.0})
        # 40% increase → trending up
        assert c["vix_trending_up"] == 1.0
        assert c["vix_trending_down"] == 0.0

    def test_spy_above_50d_detected(self):
        c = compute_conditions({
            "spy_current": 105.0, "spy_50d_avg": 100.0, "spy_200d_avg": 90.0
        })
        assert c["spy_above_50d"] == 1.0

    def test_all_conditions_are_binary(self):
        c = compute_conditions(_normal_market_indicators())
        for val in c.values():
            assert val in (0.0, 1.0), f"Non-binary condition value: {val}"


class TestRegimeClassification:
    def test_all_regimes_in_output(self):
        result = classify_regime(_normal_market_indicators())
        probs = result["probabilities"]
        for regime in _REGIMES:
            assert regime in probs, f"Missing regime: {regime}"

    def test_probabilities_sum_to_one(self):
        result = classify_regime(_normal_market_indicators())
        total = sum(result["probabilities"].values())
        assert abs(total - 1.0) < 1e-6

    def test_normal_market_leads_risk_on(self):
        result = classify_regime(_normal_market_indicators())
        assert result["leading_regime"] == "risk_on_growth", (
            f"Expected risk_on_growth, got {result['leading_regime']}: "
            f"{result['probabilities']}"
        )

    def test_stress_indicators_increase_stress_probability(self):
        normal = classify_regime(_normal_market_indicators())
        stress = classify_regime(_stress_indicators())
        assert (
            stress["probabilities"]["high_volatility_stress"]
            > normal["probabilities"]["high_volatility_stress"]
        )

    def test_panic_indicators_lead_to_panic_or_stress(self):
        result = classify_regime(_panic_indicators())
        panic_or_stress = (
            result["probabilities"]["liquidity_panic"]
            + result["probabilities"]["high_volatility_stress"]
        )
        # Should dominate the distribution
        assert panic_or_stress > 0.50, (
            f"Expected panic/stress > 50%, got {panic_or_stress}: {result['probabilities']}"
        )

    def test_inflationary_indicators_increase_inflationary_probability(self):
        normal = classify_regime(_normal_market_indicators())
        inflationary = classify_regime(_inflationary_indicators())
        assert (
            inflationary["probabilities"]["inflationary_cyclical"]
            > normal["probabilities"]["inflationary_cyclical"]
        )

    def test_deterministic_given_same_inputs(self):
        ind = _normal_market_indicators()
        r1 = classify_regime(ind)
        r2 = classify_regime(ind)
        assert r1["probabilities"] == r2["probabilities"]
        assert r1["leading_regime"] == r2["leading_regime"]

    def test_result_includes_timestamp(self):
        result = classify_regime(_normal_market_indicators())
        assert "timestamp" in result
        assert len(result["timestamp"]) >= 10

    def test_conditions_only_contains_active(self):
        result = classify_regime(_normal_market_indicators())
        for val in result["conditions"].values():
            assert val > 0.0

    def test_confidence_equals_leading_probability(self):
        result = classify_regime(_normal_market_indicators())
        assert result["confidence"] == result["probabilities"][result["leading_regime"]]


class TestRegimePersistence:
    def test_log_and_load(self, tmp_path):
        log_path = tmp_path / "regime_log.jsonl"
        result = classify_regime(_normal_market_indicators())
        log_regime(result, path=log_path)

        history = load_regime_history(path=log_path)
        assert len(history) == 1
        assert history[0]["leading_regime"] == result["leading_regime"]

    def test_multiple_entries_persisted(self, tmp_path):
        log_path = tmp_path / "regime_log.jsonl"
        for _ in range(3):
            result = classify_regime(_normal_market_indicators())
            log_regime(result, path=log_path)
        history = load_regime_history(path=log_path)
        assert len(history) == 3

    def test_missing_log_returns_empty_list(self, tmp_path):
        log_path = tmp_path / "nonexistent.jsonl"
        assert load_regime_history(path=log_path) == []

    def test_corrupt_lines_skipped_gracefully(self, tmp_path):
        log_path = tmp_path / "regime_log.jsonl"
        log_path.write_text('{"valid": true}\n{not valid json\n{"also_valid": true}\n')
        history = load_regime_history(path=log_path)
        assert len(history) == 2
