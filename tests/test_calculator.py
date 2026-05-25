"""Smoke tests for the deterministic calculator.

These verify that the math reproduces the AGX outputs from the prior session
within tight tolerances. They run without network access.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.calculator import build_fixed_numbers, classify_rating


def test_agx_recommendation():
    """AGX at $700 should be STRONG_SELL with PT ~$225."""
    fixed = build_fixed_numbers(
        ticker="AGX",
        current_price=700.0,
        diluted_shares_mm=14.0,
        ufcf_stream=[95, 123, 129, 133, 133],
        terminal_year_fcf=133,
        terminal_year_ebitda=176,
        wacc=0.11,
        terminal_growth=0.025,
        exit_multiple=15.0,
        cash_plus_investments=895.0,
        debt=0.0,
        target_ebitda=165,
        target_net_income=128,
        peer_median_ev_ebitda=14.8,
        peer_75th_ev_ebitda=21.2,
        peer_median_pe=27.9,
        consensus_low=220,
        consensus_high=321,
    )
    assert fixed.rating == "STRONG_SELL", f"Expected STRONG_SELL, got {fixed.rating}"
    assert 200 < fixed.price_target_12m < 260, f"PT {fixed.price_target_12m} out of expected range $200-260"
    assert fixed.expected_return < -0.60, f"Expected return {fixed.expected_return} not deep enough downside"
    print(f"  ✓ AGX: rating={fixed.rating}, PT=${fixed.price_target_12m:.0f}, ret={fixed.expected_return*100:+.1f}%")


def test_classify_rating_bands():
    bands = {"strong_buy": 0.20, "buy": 0.10, "hold": -0.05, "sell": -0.20}
    assert classify_rating(0.25, bands) == "STRONG_BUY"
    assert classify_rating(0.15, bands) == "BUY"
    assert classify_rating(0.05, bands) == "HOLD"
    assert classify_rating(-0.02, bands) == "HOLD"
    assert classify_rating(-0.10, bands) == "SELL"
    assert classify_rating(-0.25, bands) == "STRONG_SELL"
    print("  ✓ Rating bands correct")


def test_zero_debt_zero_cash():
    """Sanity: no balance-sheet adjustments → DCF equals enterprise value directly."""
    fixed = build_fixed_numbers(
        ticker="TEST",
        current_price=100.0,
        diluted_shares_mm=10.0,
        ufcf_stream=[10, 11, 12, 13, 14],
        terminal_year_fcf=14,
        terminal_year_ebitda=20,
        wacc=0.10,
        terminal_growth=0.025,
        exit_multiple=10.0,
        cash_plus_investments=0.0,
        debt=0.0,
        target_ebitda=20,
        target_net_income=10,
        peer_median_ev_ebitda=10,
        peer_75th_ev_ebitda=12,
        peer_median_pe=15,
    )
    assert fixed.dcf_price_gordon > 0
    assert fixed.dcf_price_exit > 0
    assert fixed.rating in {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}
    print(f"  ✓ Zero-debt/zero-cash sanity: rating={fixed.rating}")


# ---------------------------------------------------------------------------
# resolve_exit_multiple — peer-median selection and 8x/30x clamping
# ---------------------------------------------------------------------------

from src.orchestrator import resolve_exit_multiple


def test_exit_multiple_uses_peer_median_when_enough_peers():
    multiple, source = resolve_exit_multiple(20.0, n_peers_resolved=3)
    assert multiple == 20.0
    assert "peer_median" in source


def test_exit_multiple_boundary_exactly_3_peers():
    multiple, source = resolve_exit_multiple(18.0, n_peers_resolved=3)
    assert multiple == 18.0
    assert "peer_median" in source


def test_exit_multiple_falls_back_when_thin_cohort():
    multiple, source = resolve_exit_multiple(20.0, n_peers_resolved=2, default=12.0)
    assert multiple == 12.0
    assert source == "default"


def test_exit_multiple_falls_back_when_zero_peers():
    multiple, source = resolve_exit_multiple(25.0, n_peers_resolved=0, default=12.0)
    assert multiple == 12.0
    assert source == "default"


def test_exit_multiple_floor_clamp():
    """Peer median below 8x is floored to 8x."""
    multiple, source = resolve_exit_multiple(5.0, n_peers_resolved=4)
    assert multiple == 8.0
    assert "peer_median" in source


def test_exit_multiple_cap_clamp():
    """Peer median above 30x is capped at 30x."""
    multiple, source = resolve_exit_multiple(50.0, n_peers_resolved=5)
    assert multiple == 30.0
    assert "peer_median" in source


def test_exit_multiple_within_band_unchanged():
    """Value inside [8, 30] passes through unmodified."""
    multiple, source = resolve_exit_multiple(27.0, n_peers_resolved=8)
    assert multiple == 27.0


def test_exit_multiple_affects_dcf_exit_price():
    """Higher exit multiple should produce a higher DCF exit price."""
    base = dict(
        ticker="TEST", current_price=100.0, diluted_shares_mm=10.0,
        ufcf_stream=[10, 11, 12, 13, 14], terminal_year_fcf=14,
        terminal_year_ebitda=20, wacc=0.10, terminal_growth=0.025,
        cash_plus_investments=0.0, debt=0.0,
        target_ebitda=20, target_net_income=10,
        peer_median_ev_ebitda=10, peer_75th_ev_ebitda=12, peer_median_pe=15,
    )
    from src.engine.calculator import build_fixed_numbers
    low = build_fixed_numbers(**base, exit_multiple=8.0)
    high = build_fixed_numbers(**base, exit_multiple=30.0)
    assert high.dcf_price_exit > low.dcf_price_exit
    print(f"  ✓ exit 8x → PT ${low.dcf_price_exit:.0f}  |  exit 30x → PT ${high.dcf_price_exit:.0f}")


# ---------------------------------------------------------------------------
# cohort_outlier — confidence capping and flag injection
# ---------------------------------------------------------------------------

def test_cohort_outlier_caps_confidence_at_low():
    """cohort_outlier=True forces confidence to LOW regardless of model quality."""
    from src.engine.calculator import build_fixed_numbers
    base = dict(
        ticker="LLY", current_price=800.0, diluted_shares_mm=900.0,
        ufcf_stream=[10_000, 11_000, 12_000, 13_000, 14_000],
        terminal_year_fcf=14_000, terminal_year_ebitda=20_000,
        wacc=0.09, terminal_growth=0.025, exit_multiple=20.0,
        cash_plus_investments=5_000.0, debt=15_000.0,
        target_ebitda=20_000, target_net_income=15_000,
        peer_median_ev_ebitda=13.0, peer_75th_ev_ebitda=16.0, peer_median_pe=15.0,
        n_peers_resolved=5,
    )
    no_flag = build_fixed_numbers(**base, cohort_outlier=False)
    with_flag = build_fixed_numbers(**base, cohort_outlier=True)
    assert with_flag.confidence == "LOW", f"Expected LOW, got {with_flag.confidence}"
    assert "target_ev_ebitda_2x_peer_median" in with_flag.confidence_flags
    assert "target_ev_ebitda_2x_peer_median" not in (no_flag.confidence_flags or [])
    print(f"  ✓ cohort_outlier: no_flag conf={no_flag.confidence}, with_flag conf={with_flag.confidence}")


def test_cohort_outlier_does_not_change_rating():
    """cohort_outlier must not alter the rating — only confidence."""
    from src.engine.calculator import build_fixed_numbers
    base = dict(
        ticker="LLY", current_price=800.0, diluted_shares_mm=900.0,
        ufcf_stream=[10_000, 11_000, 12_000, 13_000, 14_000],
        terminal_year_fcf=14_000, terminal_year_ebitda=20_000,
        wacc=0.09, terminal_growth=0.025, exit_multiple=20.0,
        cash_plus_investments=5_000.0, debt=15_000.0,
        target_ebitda=20_000, target_net_income=15_000,
        peer_median_ev_ebitda=13.0, peer_75th_ev_ebitda=16.0, peer_median_pe=15.0,
        n_peers_resolved=5,
    )
    no_flag = build_fixed_numbers(**base, cohort_outlier=False)
    with_flag = build_fixed_numbers(**base, cohort_outlier=True)
    assert no_flag.rating == with_flag.rating, (
        f"Rating changed: {no_flag.rating} → {with_flag.rating}")
    print(f"  ✓ cohort_outlier: rating unchanged at {with_flag.rating}")


def test_cohort_outlier_preserves_broken():
    """cohort_outlier on a BROKEN output stays BROKEN (does not downgrade to LOW)."""
    from src.engine.calculator import build_fixed_numbers
    # Zero shares → NaN price target → BROKEN
    fixed = build_fixed_numbers(
        ticker="BRK", current_price=500.0, diluted_shares_mm=0.0,
        ufcf_stream=[10, 10, 10, 10, 10], terminal_year_fcf=10,
        terminal_year_ebitda=20, wacc=0.10, terminal_growth=0.025,
        exit_multiple=12.0, cash_plus_investments=0.0, debt=0.0,
        target_ebitda=20, target_net_income=10,
        peer_median_ev_ebitda=12.0, peer_75th_ev_ebitda=15.0, peer_median_pe=15.0,
        cohort_outlier=True,
    )
    assert fixed.confidence == "BROKEN", f"Expected BROKEN, got {fixed.confidence}"
    print(f"  ✓ cohort_outlier on BROKEN stays BROKEN")


if __name__ == "__main__":
    print("Running calculator tests...")
    test_classify_rating_bands()
    test_agx_recommendation()
    test_zero_debt_zero_cash()
    print("All tests passed.")
