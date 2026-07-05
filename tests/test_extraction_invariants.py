"""Tests for src/data/extraction_invariants.py — pure, synthetic values."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.extraction_invariants import (
    run_invariants, SEV_HIGH, SEV_MED,
)


def _clean_extracted():
    # revenue 10B, gp 3.5B (35% GM), oi 1.5B (15% OM), 100M shares, net_debt 2B
    return {
        "revenue": 10_000_000_000, "cost_of_revenue": 6_500_000_000,
        "gross_profit": 3_500_000_000, "operating_income": 1_500_000_000,
        "sga": 2_000_000_000, "net_debt": 2_000_000_000, "shares": 100_000_000,
        "price_target": 120.0, "current_price": 100.0,
    }


def _clean_reference():
    return {
        "totalRevenue": 10_100_000_000, "grossMargins": 0.35,
        "operatingMargins": 0.15, "totalDebt": 3_000_000_000,
        "totalCash": 1_100_000_000, "sharesOutstanding": 101_000_000,
    }


def _checks(viols):
    return {v["check"] for v in viols}


def _sev(viols, check):
    return next(v["severity"] for v in viols if v["check"] == check)


def test_clean_extraction_no_violations():
    assert run_invariants("OK", _clean_extracted(), _clean_reference()) == []
    print("  ✓ clean extraction → no violations")


def test_revenue_drift_high():
    ext = _clean_extracted(); ext["revenue"] = 5_000_000_000   # ~50% below ref 10.1B
    viols = run_invariants("REV", ext, _clean_reference())
    assert "revenue_vs_yfinance" in _checks(viols)
    assert _sev(viols, "revenue_vs_yfinance") == SEV_HIGH
    print("  ✓ revenue >15% off → SEV_HIGH")


def test_gross_margin_out_of_range_high():
    ext = _clean_extracted(); ext["gross_profit"] = 9_500_000_000   # 95% GM
    viols = run_invariants("GM", ext, _clean_reference())
    assert _sev(viols, "gross_margin_out_of_range") == SEV_HIGH
    print("  ✓ gross_margin > 0.90 → SEV_HIGH")


def test_op_margin_exceeds_gross_margin():
    ext = _clean_extracted()
    ext["operating_income"] = 4_000_000_000   # OM 40% > GM 35%
    viols = run_invariants("OM", ext, _clean_reference())
    assert _sev(viols, "op_margin_ge_gross_margin") == SEV_MED
    print("  ✓ op_margin >= gross_margin → SEV_MED")


def test_op_margin_vs_yfinance_gt_10pp():
    ext = _clean_extracted()
    ext["operating_income"] = 800_000_000   # OM 8% vs yfinance 15% → 7pp ok
    ref = _clean_reference(); ref["operatingMargins"] = 0.30   # now 22pp apart
    viols = run_invariants("OMY", ext, ref)
    assert "op_margin_vs_yfinance" in _checks(viols)
    print("  ✓ op_margin vs yfinance > 10pp → SEV_MED")


def test_shares_drift_high():
    ext = _clean_extracted(); ext["shares"] = 130_000_000   # +30% vs 101M
    viols = run_invariants("SH", ext, _clean_reference())
    assert _sev(viols, "shares_vs_yfinance") == SEV_HIGH
    print("  ✓ shares > 10% off → SEV_HIGH")


def test_net_debt_drift_med():
    ext = _clean_extracted(); ext["net_debt"] = 5_000_000_000   # vs ref 1.9B (>25%)
    viols = run_invariants("ND", ext, _clean_reference())
    assert _sev(viols, "net_debt_vs_yfinance") == SEV_MED
    print("  ✓ net_debt > 25% off → SEV_MED")


def test_unit_magnitude_high():
    ext = _clean_extracted(); ext["revenue"] = 500.0   # dollars-vs-$mm error
    # note: revenue also trips revenue_vs_yfinance; assert the magnitude one is present
    viols = run_invariants("UNIT", ext, _clean_reference())
    assert _sev(viols, "unit_magnitude_revenue") == SEV_HIGH
    print("  ✓ monetary field outside [1e6,1e13] → SEV_HIGH")


def test_price_target_ratio_high_both_directions():
    ext = _clean_extracted(); ext["price_target"] = 500.0   # 5x current → high
    assert _sev(run_invariants("PT", ext, _clean_reference()),
                "price_target_vs_price_ratio") == SEV_HIGH
    ext2 = _clean_extracted(); ext2["price_target"] = 5.0   # 0.05x → high
    assert _sev(run_invariants("PT2", ext2, _clean_reference()),
                "price_target_vs_price_ratio") == SEV_HIGH
    print("  ✓ |PT/price| outside [0.2,3.0] → SEV_HIGH (both directions)")


def test_missing_fields_are_skipped_not_fabricated():
    ext = {"revenue": None, "gross_profit": None, "shares": None,
           "net_debt": None, "price_target": None, "current_price": None}
    assert run_invariants("MISS", ext, {}) == []
    print("  ✓ missing fields skipped, never fabricated into violations")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All extraction-invariant tests passed.")
