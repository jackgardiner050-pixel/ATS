"""Unit tests for assess_confidence_v2() in src/engine/calculator.py

Tests run without network access. Verifies:
  - 5-tier dispersion (not uniform MED)
  - BROKEN override
  - Penalty accumulation under stress conditions
  - Expected calibration for reference tickers
  - Backward compatibility (legacy parameters only → reasonable output)
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.calculator import assess_confidence_v2


# ─── Helpers ─────────────────────────────────────────────────────────────────

TIERS = ["HIGH", "MED_HIGH", "MED", "MED_LOW", "LOW", "BROKEN"]

def _tier_rank(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else len(TIERS)


def _assert_tier_at_least(actual: str, minimum: str, msg: str = ""):
    assert _tier_rank(actual) <= _tier_rank(minimum), (
        f"{msg}: expected ≥{minimum}, got {actual}"
    )


def _assert_tier_at_most(actual: str, maximum: str, msg: str = ""):
    assert _tier_rank(actual) >= _tier_rank(maximum), (
        f"{msg}: expected ≤{maximum}, got {actual}"
    )


# ─── BROKEN override ─────────────────────────────────────────────────────────

def test_broken_on_zero_price_target():
    tier, flags = assess_confidence_v2(
        expected_return=0.50, n_peers_resolved=5,
        dcf_gordon=120.0, dcf_exit=125.0, comps_median=118.0,
        price_target=0.0,
    )
    assert tier == "BROKEN"
    assert "price_target_non_positive" in flags


def test_broken_on_nan_price_target():
    tier, flags = assess_confidence_v2(
        expected_return=0.30, n_peers_resolved=5,
        dcf_gordon=120.0, dcf_exit=125.0, comps_median=118.0,
        price_target=float("nan"),
    )
    assert tier == "BROKEN"


def test_broken_on_negative_price_target():
    tier, flags = assess_confidence_v2(
        expected_return=-0.50, n_peers_resolved=3,
        dcf_gordon=80.0, dcf_exit=85.0, comps_median=78.0,
        price_target=-10.0,
    )
    assert tier == "BROKEN"


# ─── Peer resolution penalties ────────────────────────────────────────────────

def test_no_peers_applies_large_penalty():
    tier_no_peers, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=0,
        dcf_gordon=120.0, dcf_exit=125.0, comps_median=118.0,
        price_target=125.0,
    )
    tier_good_peers, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=5,
        dcf_gordon=120.0, dcf_exit=125.0, comps_median=118.0,
        price_target=125.0,
    )
    assert _tier_rank(tier_no_peers) > _tier_rank(tier_good_peers), (
        f"No peers ({tier_no_peers}) should be ≤ good peers ({tier_good_peers})"
    )


def test_strong_peer_cohort_bonus():
    tier_5, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=5,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=119.0,
        price_target=125.0,
    )
    tier_2, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=2,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=119.0,
        price_target=125.0,
    )
    assert _tier_rank(tier_5) <= _tier_rank(tier_2), "5 peers should be >= 2 peers"


# ─── Method convergence ───────────────────────────────────────────────────────

def test_method_divergence_penalised():
    tier_converge, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=4,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=121.0,   # CV ≈ 0.008
        price_target=121.0,
    )
    tier_diverge, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=4,
        dcf_gordon=80.0, dcf_exit=150.0, comps_median=200.0,    # CV ≈ 0.43
        price_target=143.0,
    )
    assert _tier_rank(tier_converge) <= _tier_rank(tier_diverge), (
        f"Converging methods ({tier_converge}) should be ≥ diverging ({tier_diverge})"
    )


# ─── Leverage penalties ───────────────────────────────────────────────────────

def test_high_leverage_penalised():
    tier_low, _ = assess_confidence_v2(
        expected_return=0.30, n_peers_resolved=4,
        dcf_gordon=125.0, dcf_exit=128.0, comps_median=126.0,
        price_target=126.0,
        net_debt_ebitda=0.2,
    )
    tier_high, _ = assess_confidence_v2(
        expected_return=0.30, n_peers_resolved=4,
        dcf_gordon=125.0, dcf_exit=128.0, comps_median=126.0,
        price_target=126.0,
        net_debt_ebitda=4.5,
    )
    assert _tier_rank(tier_low) <= _tier_rank(tier_high), (
        f"Low leverage ({tier_low}) should be ≥ high leverage ({tier_high})"
    )


def test_net_cash_position_bonus():
    tier_net_cash, _ = assess_confidence_v2(
        expected_return=0.20, n_peers_resolved=5,
        dcf_gordon=118.0, dcf_exit=120.0, comps_median=119.0,
        price_target=119.0,
        net_debt_ebitda=-0.5,   # net-cash
    )
    tier_levered, _ = assess_confidence_v2(
        expected_return=0.20, n_peers_resolved=5,
        dcf_gordon=118.0, dcf_exit=120.0, comps_median=119.0,
        price_target=119.0,
        net_debt_ebitda=2.0,
    )
    assert _tier_rank(tier_net_cash) <= _tier_rank(tier_levered)


# ─── Upside gate penalties ────────────────────────────────────────────────────

def test_ok_gate_no_penalty():
    tier_ok, flags = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=4,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=121.0,
        price_target=121.0,
        upside_gate="OK",
    )
    assert "upside_gate_ok" not in flags or tier_ok in ("HIGH", "MED_HIGH", "MED")


def test_extreme_upside_anomaly_degrades_confidence():
    tier_ok, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=4,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=121.0,
        price_target=121.0,
        upside_gate="OK",
    )
    tier_anomaly, flags = assess_confidence_v2(
        expected_return=1.50, n_peers_resolved=4,
        dcf_gordon=250.0, dcf_exit=255.0, comps_median=248.0,
        price_target=250.0,
        upside_gate="EXTREME_UPSIDE_ANOMALY",
    )
    assert _tier_rank(tier_anomaly) > _tier_rank(tier_ok), (
        f"Anomaly ({tier_anomaly}) should be < OK ({tier_ok})"
    )
    assert "upside_gate_extreme_upside_anomaly" in flags


def test_high_upside_review_intermediate_penalty():
    tier_review, _ = assess_confidence_v2(
        expected_return=0.90, n_peers_resolved=3,
        dcf_gordon=190.0, dcf_exit=195.0, comps_median=188.0,
        price_target=190.0,
        upside_gate="HIGH_UPSIDE_REVIEW_REQUIRED",
    )
    tier_ok, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=3,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=121.0,
        price_target=121.0,
        upside_gate="OK",
    )
    assert _tier_rank(tier_review) >= _tier_rank(tier_ok)


# ─── Cyclicality penalties ────────────────────────────────────────────────────

def test_cyclical_peak_detected_penalised():
    tier_no_peak, _ = assess_confidence_v2(
        expected_return=0.40, n_peers_resolved=4,
        dcf_gordon=140.0, dcf_exit=142.0, comps_median=138.0,
        price_target=140.0,
        is_cyclical=False,
        cyclical_peak_detected=False,
    )
    tier_peak, _ = assess_confidence_v2(
        expected_return=0.40, n_peers_resolved=4,
        dcf_gordon=140.0, dcf_exit=142.0, comps_median=138.0,
        price_target=140.0,
        is_cyclical=True,
        cyclical_peak_detected=True,
    )
    assert _tier_rank(tier_peak) >= _tier_rank(tier_no_peak), (
        f"Cyclical peak ({tier_peak}) should be ≤ no peak ({tier_no_peak})"
    )


def test_cyclical_without_peak_mild_penalty():
    tier_non_cyclical, _ = assess_confidence_v2(
        expected_return=0.30, n_peers_resolved=4,
        dcf_gordon=130.0, dcf_exit=132.0, comps_median=129.0,
        price_target=130.0,
        is_cyclical=False,
    )
    tier_cyclical, _ = assess_confidence_v2(
        expected_return=0.30, n_peers_resolved=4,
        dcf_gordon=130.0, dcf_exit=132.0, comps_median=129.0,
        price_target=130.0,
        is_cyclical=True,
        cyclical_peak_detected=False,
    )
    # Cyclical without peak should be at most one tier below non-cyclical
    rank_diff = _tier_rank(tier_cyclical) - _tier_rank(tier_non_cyclical)
    assert rank_diff <= 1, f"Cyclical without peak should not degrade by more than 1 tier: diff={rank_diff}"


# ─── Combined stress penalties ────────────────────────────────────────────────

def test_wacc_destroys_upside_penalised():
    tier_stable, _ = assess_confidence_v2(
        expected_return=0.40, n_peers_resolved=4,
        dcf_gordon=140.0, dcf_exit=142.0, comps_median=138.0,
        price_target=140.0,
        wacc_destroys_upside=False,
    )
    tier_fragile, _ = assess_confidence_v2(
        expected_return=0.40, n_peers_resolved=4,
        dcf_gordon=140.0, dcf_exit=142.0, comps_median=138.0,
        price_target=140.0,
        wacc_destroys_upside=True,
    )
    assert _tier_rank(tier_fragile) >= _tier_rank(tier_stable)


def test_multiple_stress_factors_compound():
    # All adverse: cyclical peak + WACC kills upside + extreme gate + high leverage + thin peers
    tier_clean, _ = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=5,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=121.0,
        price_target=121.0,
        upside_gate="OK",
        is_cyclical=False,
        net_debt_ebitda=0.5,
        wacc_destroys_upside=False,
    )
    tier_stressed, _ = assess_confidence_v2(
        expected_return=1.40, n_peers_resolved=1,
        dcf_gordon=240.0, dcf_exit=245.0, comps_median=238.0,
        price_target=240.0,
        upside_gate="EXTREME_UPSIDE_ANOMALY",
        is_cyclical=True,
        cyclical_peak_detected=True,
        net_debt_ebitda=4.0,
        wacc_destroys_upside=True,
        multiple_fragility_warning=True,
        fragility_score=0.85,
    )
    assert _tier_rank(tier_stressed) > _tier_rank(tier_clean), (
        f"Stressed ({tier_stressed}) should be < clean ({tier_clean})"
    )
    assert tier_stressed in ("MED_LOW", "LOW"), (
        f"Full adverse profile should yield MED_LOW or LOW, got {tier_stressed}"
    )


# ─── Reference calibration tests ─────────────────────────────────────────────

def test_spgi_like_achieves_high_or_med_high():
    """SPGI: financial data moat, stable earnings, low cyclicality, OK upside gate."""
    tier, flags = assess_confidence_v2(
        expected_return=0.30,
        n_peers_resolved=4,        # MCO, MSCI, FDS, ICE
        dcf_gordon=116.0,
        dcf_exit=118.0,
        comps_median=115.0,        # tight convergence
        price_target=116.0,
        upside_gate="OK",          # stress-adjusted upside ≈ 16% → OK
        is_cyclical=False,
        cyclical_peak_detected=False,
        wacc_destroys_upside=False,
        net_debt_ebitda=2.0,
        multiple_fragility_warning=False,
        fragility_score=0.20,
    )
    assert tier in ("HIGH", "MED_HIGH"), (
        f"SPGI-like should be HIGH or MED_HIGH, got {tier} ({flags})"
    )


def test_gd_like_achieves_high_or_med_high():
    """GD: defense, stable government contracts, low cyclicality."""
    tier, flags = assess_confidence_v2(
        expected_return=0.25,
        n_peers_resolved=4,        # LMT, NOC, RTX, HII
        dcf_gordon=270.0,
        dcf_exit=275.0,
        comps_median=268.0,
        price_target=271.0,
        upside_gate="OK",
        is_cyclical=False,
        cyclical_peak_detected=False,
        wacc_destroys_upside=False,
        net_debt_ebitda=1.5,
        fragility_score=0.18,
    )
    assert tier in ("HIGH", "MED_HIGH"), (
        f"GD-like should be HIGH or MED_HIGH, got {tier} ({flags})"
    )


def test_amat_like_achieves_med_low():
    """AMAT: semicap equipment, cyclical peak EBITDA, high upside in raw DCF."""
    tier, flags = assess_confidence_v2(
        expected_return=0.90,
        n_peers_resolved=3,
        dcf_gordon=190.0,
        dcf_exit=195.0,
        comps_median=185.0,
        price_target=190.0,
        upside_gate="HIGH_UPSIDE_REVIEW_REQUIRED",
        is_cyclical=True,
        cyclical_peak_detected=True,
        wacc_destroys_upside=True,
        net_debt_ebitda=0.3,       # AMAT is not levered
        multiple_fragility_warning=True,
        fragility_score=0.65,
    )
    assert tier in ("MED_LOW", "LOW"), (
        f"AMAT-like should be MED_LOW or LOW, got {tier} ({flags})"
    )


def test_gnrc_like_achieves_low():
    """GNRC: high leverage, post-COVID cyclical peak, thin peers, extreme upside."""
    tier, flags = assess_confidence_v2(
        expected_return=1.20,
        n_peers_resolved=1,        # thin peer set
        dcf_gordon=180.0,
        dcf_exit=190.0,
        comps_median=160.0,        # wide divergence
        price_target=177.0,
        upside_gate="EXTREME_UPSIDE_ANOMALY",
        is_cyclical=True,
        cyclical_peak_detected=True,
        wacc_destroys_upside=True,
        net_debt_ebitda=3.5,
        multiple_fragility_warning=True,
        fragility_score=0.80,
    )
    assert tier == "LOW", (
        f"GNRC-like should be LOW, got {tier} ({flags})"
    )


# ─── Backward compatibility ───────────────────────────────────────────────────

def test_legacy_only_params_return_valid_tier():
    """Calling with only v1 params should return a valid non-BROKEN tier."""
    tier, flags = assess_confidence_v2(
        expected_return=0.25,
        n_peers_resolved=3,
        dcf_gordon=120.0,
        dcf_exit=122.0,
        comps_median=119.0,
        price_target=120.0,
    )
    assert tier in TIERS
    assert tier != "BROKEN"


def test_output_always_contains_score_flag():
    tier, flags = assess_confidence_v2(
        expected_return=0.25, n_peers_resolved=3,
        dcf_gordon=120.0, dcf_exit=122.0, comps_median=119.0,
        price_target=120.0,
    )
    score_flags = [f for f in flags if f.startswith("confidence_v2_score_")]
    assert len(score_flags) == 1, f"Expected one score flag, got: {score_flags}"


# ─── Dispersion property test ─────────────────────────────────────────────────

def test_genuine_dispersion_across_profiles():
    """Run 6 distinct input profiles and assert they do NOT all land in the same tier."""
    profiles = [
        # (label, inputs_kwargs)
        ("quality_moat", dict(expected_return=0.20, n_peers_resolved=5,
                               dcf_gordon=118.0, dcf_exit=120.0, comps_median=119.0,
                               price_target=119.0, upside_gate="OK",
                               is_cyclical=False, net_debt_ebitda=0.3)),
        ("moderate_upside", dict(expected_return=0.35, n_peers_resolved=3,
                                  dcf_gordon=130.0, dcf_exit=135.0, comps_median=128.0,
                                  price_target=131.0, upside_gate="AGGRESSIVE_UPSIDE",
                                  is_cyclical=False, net_debt_ebitda=1.5)),
        ("cyclical_no_peak", dict(expected_return=0.45, n_peers_resolved=4,
                                   dcf_gordon=140.0, dcf_exit=145.0, comps_median=138.0,
                                   price_target=141.0, upside_gate="AGGRESSIVE_UPSIDE",
                                   is_cyclical=True, cyclical_peak_detected=False,
                                   net_debt_ebitda=1.0)),
        ("levered_yield", dict(expected_return=0.40, n_peers_resolved=3,
                                dcf_gordon=138.0, dcf_exit=140.0, comps_median=136.0,
                                price_target=138.0, upside_gate="AGGRESSIVE_UPSIDE",
                                is_cyclical=False, net_debt_ebitda=4.0)),
        ("cyclical_peak_high_upside", dict(expected_return=0.90, n_peers_resolved=2,
                                            dcf_gordon=190.0, dcf_exit=195.0, comps_median=185.0,
                                            price_target=190.0,
                                            upside_gate="HIGH_UPSIDE_REVIEW_REQUIRED",
                                            is_cyclical=True, cyclical_peak_detected=True,
                                            wacc_destroys_upside=True, net_debt_ebitda=0.5,
                                            fragility_score=0.65)),
        ("gnrc_worst_case", dict(expected_return=1.20, n_peers_resolved=1,
                                  dcf_gordon=180.0, dcf_exit=190.0, comps_median=160.0,
                                  price_target=177.0,
                                  upside_gate="EXTREME_UPSIDE_ANOMALY",
                                  is_cyclical=True, cyclical_peak_detected=True,
                                  wacc_destroys_upside=True, net_debt_ebitda=3.5,
                                  multiple_fragility_warning=True, fragility_score=0.80)),
    ]

    tiers_obtained = set()
    for label, kwargs in profiles:
        tier, _ = assess_confidence_v2(**kwargs)
        tiers_obtained.add(tier)
        print(f"  {label}: {tier}")

    assert len(tiers_obtained) >= 3, (
        f"Expected at least 3 distinct tiers across 6 profiles, got {tiers_obtained}"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
