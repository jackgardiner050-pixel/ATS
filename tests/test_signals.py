"""Tests for Phase 2 signal cross-check modules.

Covers:
  - Momentum quintile assignment (synthetic universe)
  - Revision direction thresholds at exact boundaries
  - Confidence escalation rules (aligned, contradicted, mixed, cohort_outlier floor)
  - HOLD + revision triggers force_rescreen
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.signals.momentum import _assign_quintiles
from src.signals.revisions import _compute_direction
from src.signals.escalation import (
    get_signal_alignment,
    apply_confidence_escalation,
    should_force_rescreen,
)


# ─────────────────────────────────────────────────────────────────────────────
# Momentum — quintile assignment
# ─────────────────────────────────────────────────────────────────────────────

def _make_10_ticker_returns():
    """Synthetic 10-ticker universe with evenly spaced returns."""
    return {
        "T01": 0.50,   # rank 9 / 9 → Q1
        "T02": 0.40,   # rank 8 / 9 → Q1
        "T03": 0.30,   # rank 7 / 9 → Q2
        "T04": 0.20,   # rank 6 / 9 → Q2
        "T05": 0.10,   # rank 5 / 9 → Q3
        "T06": 0.00,   # rank 4 / 9 → Q3
        "T07": -0.10,  # rank 3 / 9 → Q4
        "T08": -0.20,  # rank 2 / 9 → Q4
        "T09": -0.30,  # rank 1 / 9 → Q5
        "T10": -0.40,  # rank 0 / 9 → Q5
    }


def test_momentum_top_tickers_are_q1():
    result = _assign_quintiles(_make_10_ticker_returns())
    assert result["T01"]["quintile"] == 1, f"T01 should be Q1, got {result['T01']['quintile']}"
    assert result["T02"]["quintile"] == 1, f"T02 should be Q1, got {result['T02']['quintile']}"
    print("  ✓ Top tickers assigned Q1")


def test_momentum_bottom_tickers_are_q5():
    result = _assign_quintiles(_make_10_ticker_returns())
    assert result["T09"]["quintile"] == 5, f"T09 should be Q5, got {result['T09']['quintile']}"
    assert result["T10"]["quintile"] == 5, f"T10 should be Q5, got {result['T10']['quintile']}"
    print("  ✓ Bottom tickers assigned Q5")


def test_momentum_middle_ticker_is_q3():
    result = _assign_quintiles(_make_10_ticker_returns())
    assert result["T05"]["quintile"] == 3, f"T05 should be Q3, got {result['T05']['quintile']}"
    assert result["T06"]["quintile"] == 3, f"T06 should be Q3, got {result['T06']['quintile']}"
    print("  ✓ Middle tickers assigned Q3")


def test_momentum_q2_q4_correct():
    result = _assign_quintiles(_make_10_ticker_returns())
    assert result["T03"]["quintile"] == 2
    assert result["T04"]["quintile"] == 2
    assert result["T07"]["quintile"] == 4
    assert result["T08"]["quintile"] == 4
    print("  ✓ Q2 and Q4 tickers correct")


def test_momentum_none_returns_none_quintile():
    returns = {"A": 0.20, "B": None, "C": -0.10}
    result = _assign_quintiles(returns)
    assert result["B"]["quintile"] is None
    assert result["B"]["return_12m"] is None
    # A and C should still get valid quintiles
    assert result["A"]["quintile"] is not None
    assert result["C"]["quintile"] is not None
    print("  ✓ None return → None quintile; other tickers still ranked")


def test_momentum_single_ticker():
    """Single ticker with valid return → pctile=0.5, Q3."""
    result = _assign_quintiles({"ONLY": 0.15})
    assert result["ONLY"]["quintile"] == 3  # 5 - min(4, int(0.5*5)) = 5-2 = 3
    print("  ✓ Single ticker → Q3 (centred)")


def test_momentum_pctile_bounds():
    """Best and worst get pctile 1.0 and 0.0."""
    result = _assign_quintiles({"BEST": 1.0, "WORST": -1.0})
    assert result["BEST"]["pctile"] == 1.0
    assert result["WORST"]["pctile"] == 0.0
    print("  ✓ Pctile bounds correct for 2-ticker universe")


# ─────────────────────────────────────────────────────────────────────────────
# Revisions — EPS trend direction thresholds (±2% of 90-day-ago estimate)
# ─────────────────────────────────────────────────────────────────────────────

def test_revision_positive_above_2pct():
    """EPS revised up by >2% → POSITIVE."""
    assert _compute_direction(10.50, 10.00) == "POSITIVE"   # +5%
    assert _compute_direction(10.21, 10.00) == "POSITIVE"   # just above +2%
    print("  ✓ EPS > 90d_ago × 1.02 → POSITIVE")


def test_revision_negative_above_2pct():
    """EPS revised down by >2% → NEGATIVE."""
    assert _compute_direction(9.50, 10.00) == "NEGATIVE"    # -5%
    assert _compute_direction(9.79, 10.00) == "NEGATIVE"    # just below -2%
    print("  ✓ EPS < 90d_ago × 0.98 → NEGATIVE")


def test_revision_flat_within_2pct():
    """EPS change within ±2% → FLAT."""
    assert _compute_direction(10.10, 10.00) == "FLAT"       # +1%
    assert _compute_direction(9.90,  10.00) == "FLAT"       # -1%
    assert _compute_direction(10.00, 10.00) == "FLAT"       # unchanged
    print("  ✓ EPS within ±2% → FLAT")


def test_revision_exactly_2pct_is_flat():
    """Exactly +2% is FLAT — threshold is strict (>2%, not >=2%)."""
    # 10.00 × 1.02 = 10.20; 10.20 > 10.20 is False → FLAT
    assert _compute_direction(10.20, 10.00) == "FLAT"
    print("  ✓ Exactly +2% boundary → FLAT (strict >)")


def test_revision_exactly_minus_2pct_is_flat():
    """Exactly -2% is FLAT — threshold is strict (<-2%, not <=-2%)."""
    # 10.00 × 0.98 = 9.80; 9.80 < 9.80 is False → FLAT
    assert _compute_direction(9.80, 10.00) == "FLAT"
    print("  ✓ Exactly -2% boundary → FLAT (strict <)")


def test_revision_no_coverage_near_zero_base():
    """Near-zero 90daysAgo EPS → NO_COVERAGE (ratio undefined)."""
    assert _compute_direction(1.0, 0.0) == "NO_COVERAGE"
    assert _compute_direction(1.0, 0.0005) == "NO_COVERAGE"
    print("  ✓ Near-zero 90daysAgo → NO_COVERAGE")


def test_revision_no_coverage_none_values():
    """None / NaN inputs → NO_COVERAGE."""
    assert _compute_direction(None, 10.0) == "NO_COVERAGE"
    assert _compute_direction(10.0, None) == "NO_COVERAGE"
    assert _compute_direction(None, None) == "NO_COVERAGE"
    print("  ✓ None inputs → NO_COVERAGE")


def test_revision_negative_eps_improving():
    """Negative EPS trending less negative is POSITIVE (same sign logic)."""
    # ago = -5.00, current = -4.00: -4.00 > -5.00 × 1.02 = -5.10 → POSITIVE
    assert _compute_direction(-4.00, -5.00) == "POSITIVE"
    print("  ✓ Negative EPS improving (less negative) → POSITIVE")


# ─────────────────────────────────────────────────────────────────────────────
# Confidence escalation
# ─────────────────────────────────────────────────────────────────────────────

def test_escalation_two_aligned_bumps_up():
    """2 aligned signals: LOW→MED, MED→HIGH."""
    aligned = ["momentum_q1", "revision_positive"]
    assert apply_confidence_escalation("LOW", aligned, []) == "MED"
    assert apply_confidence_escalation("MED", aligned, []) == "HIGH"
    print("  ✓ 2 aligned signals: LOW→MED, MED→HIGH")


def test_escalation_two_contradicting_bumps_down():
    """2 contradicting signals: HIGH→MED, MED→LOW."""
    contradicting = ["momentum_q5", "revision_negative"]
    assert apply_confidence_escalation("HIGH", [], contradicting) == "MED"
    assert apply_confidence_escalation("MED", [], contradicting) == "LOW"
    print("  ✓ 2 contradicting signals: HIGH→MED, MED→LOW")


def test_escalation_one_signal_no_change():
    """Only 1 aligned or 1 contradicting → no confidence change."""
    assert apply_confidence_escalation("MED", ["momentum_q1"], []) == "MED"
    assert apply_confidence_escalation("MED", [], ["momentum_q5"]) == "MED"
    print("  ✓ 1 signal → no confidence change")


def test_escalation_ceiling_high():
    """Cannot escalate above HIGH."""
    assert apply_confidence_escalation("HIGH", ["a", "b"], []) == "HIGH"
    print("  ✓ Ceiling: HIGH cannot be escalated further")


def test_escalation_floor_low():
    """Cannot degrade below LOW (BROKEN is separate)."""
    assert apply_confidence_escalation("LOW", [], ["a", "b"]) == "LOW"
    print("  ✓ Floor: LOW cannot be degraded further")


def test_escalation_broken_unchanged():
    """BROKEN is never changed by signals."""
    assert apply_confidence_escalation("BROKEN", ["a", "b"], []) == "BROKEN"
    assert apply_confidence_escalation("BROKEN", [], ["a", "b"]) == "BROKEN"
    print("  ✓ BROKEN stays BROKEN regardless of signals")


def test_escalation_cohort_outlier_caps_at_low():
    """cohort_outlier=True prevents escalation above LOW even with 2 aligned."""
    aligned = ["momentum_q1", "revision_positive"]
    assert apply_confidence_escalation("LOW", aligned, [], cohort_outlier=True) == "LOW"
    assert apply_confidence_escalation("MED", aligned, [], cohort_outlier=True) == "LOW"
    assert apply_confidence_escalation("HIGH", aligned, [], cohort_outlier=True) == "LOW"
    print("  ✓ cohort_outlier caps at LOW regardless of aligned signals")


def test_escalation_cohort_outlier_leaves_broken():
    """cohort_outlier does not affect BROKEN."""
    assert apply_confidence_escalation("BROKEN", [], [], cohort_outlier=True) == "BROKEN"
    print("  ✓ cohort_outlier + BROKEN → still BROKEN")


# ─────────────────────────────────────────────────────────────────────────────
# Alignment rules
# ─────────────────────────────────────────────────────────────────────────────

def test_alignment_bullish_q1_now_neutral():
    """Momentum neutralized (item 8): Q1 is observation-only, never aligned."""
    aligned, contradicting, neutral = get_signal_alignment("STRONG_BUY", 1, "FLAT")
    assert "momentum_q1" in neutral        # recorded (observation-only)
    assert "momentum_q1" not in aligned and not contradicting
    print("  ✓ STRONG_BUY + Q1 momentum → NEUTRAL (observation-only)")


def test_alignment_bullish_q5_now_neutral():
    aligned, contradicting, neutral = get_signal_alignment("BUY", 5, "NO_COVERAGE")
    assert "momentum_q5" in neutral
    assert not aligned and not contradicting
    print("  ✓ BUY + Q5 momentum → NEUTRAL (observation-only)")


def test_alignment_bearish_q5_now_neutral():
    aligned, contradicting, neutral = get_signal_alignment("SELL", 5, "FLAT")
    assert "momentum_q5" in neutral
    assert not aligned and not contradicting
    print("  ✓ SELL + Q5 momentum → NEUTRAL (observation-only)")


def test_alignment_bearish_positive_revision_contradicts():
    aligned, contradicting, neutral = get_signal_alignment("STRONG_SELL", None, "POSITIVE")
    assert "revision_positive" in contradicting
    print("  ✓ STRONG_SELL + POSITIVE revision → contradicts")


def test_alignment_hold_all_neutral():
    """All momentum quintiles and both revision directions are neutral for HOLD."""
    for q in (1, 5):
        a, c, n = get_signal_alignment("HOLD", q, "FLAT")
        assert not a and not c
    for rev in ("POSITIVE", "NEGATIVE"):
        a, c, n = get_signal_alignment("HOLD", None, rev)
        assert not a and not c
    print("  ✓ HOLD: all signals are neutral (not aligned/contradicting)")


# ─────────────────────────────────────────────────────────────────────────────
# HOLD + revision → force_rescreen
# ─────────────────────────────────────────────────────────────────────────────

def test_hold_positive_revision_triggers_force_rescreen():
    assert should_force_rescreen("HOLD", "POSITIVE") is True
    print("  ✓ HOLD + POSITIVE revision triggers force_rescreen")


def test_hold_negative_revision_triggers_force_rescreen():
    assert should_force_rescreen("HOLD", "NEGATIVE") is True
    print("  ✓ HOLD + NEGATIVE revision triggers force_rescreen")


def test_hold_flat_revision_does_not_trigger():
    assert should_force_rescreen("HOLD", "FLAT") is False
    assert should_force_rescreen("HOLD", "NO_COVERAGE") is False
    print("  ✓ HOLD + FLAT/NO_COVERAGE → no force_rescreen")


def test_non_hold_rating_does_not_trigger():
    """force_rescreen is only for HOLD, not for other ratings."""
    for rating in ("STRONG_BUY", "BUY", "SELL", "STRONG_SELL"):
        assert should_force_rescreen(rating, "POSITIVE") is False
        assert should_force_rescreen(rating, "NEGATIVE") is False
    print("  ✓ Non-HOLD ratings do not trigger force_rescreen via revision")


if __name__ == "__main__":
    print("Running signal tests...")
    test_momentum_top_tickers_are_q1()
    test_momentum_bottom_tickers_are_q5()
    test_momentum_middle_ticker_is_q3()
    test_momentum_q2_q4_correct()
    test_momentum_none_returns_none_quintile()
    test_momentum_single_ticker()
    test_momentum_pctile_bounds()
    test_revision_positive_above_2pct()
    test_revision_negative_above_2pct()
    test_revision_flat_within_2pct()
    test_revision_exactly_2pct_is_flat()
    test_revision_exactly_minus_2pct_is_flat()
    test_revision_no_coverage_near_zero_base()
    test_revision_no_coverage_none_values()
    test_revision_negative_eps_improving()
    test_escalation_two_aligned_bumps_up()
    test_escalation_two_contradicting_bumps_down()
    test_escalation_one_signal_no_change()
    test_escalation_ceiling_high()
    test_escalation_floor_low()
    test_escalation_broken_unchanged()
    test_escalation_cohort_outlier_caps_at_low()
    test_escalation_cohort_outlier_leaves_broken()
    test_alignment_bullish_q1_now_neutral()
    test_alignment_bullish_q5_now_neutral()
    test_alignment_bearish_q5_now_neutral()
    test_alignment_bearish_positive_revision_contradicts()
    test_alignment_hold_all_neutral()
    test_hold_positive_revision_triggers_force_rescreen()
    test_hold_negative_revision_triggers_force_rescreen()
    test_hold_flat_revision_does_not_trigger()
    test_non_hold_rating_does_not_trigger()
    print("All signal tests passed.")
