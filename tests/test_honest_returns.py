"""Tests for close_position honest accounting (item 10) — pure, synthetic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import open_position, close_position, tr_fields, _paper_cost_bps


def _pos(entry=100.0, spy_entry=500.0):
    return open_position("ACM", "2026-01-01", entry, "STRONG_BUY", "MED",
                         130.0, spy_entry, cohort="cohort_1")


def test_gross_and_net_returns_recorded():
    t = close_position(_pos(100.0), "2026-02-01", 110.0, "HOLD", 510.0, cost_bps=20.0)
    assert t["return_pct"] == round(0.10, 6)               # gross unchanged
    assert t["return_pct_net"] == round(0.10 - 2 * 0.002, 6)   # 0.096
    assert t["cost_bps"] == 20.0
    print("  ✓ gross and net (gross − 2×cost_bps/1e4) both recorded")


def test_net_alpha_applies_round_trip_cost():
    t = close_position(_pos(100.0, 500.0), "2026-02-01", 110.0, "HOLD", 510.0, cost_bps=20.0)
    # gross alpha = 0.10 - 0.02 = 0.08; net alpha = 0.08 - 0.004
    assert t["alpha"] == round(0.08, 6)
    assert t["alpha_net"] == round(0.08 - 0.004, 6)
    print("  ✓ net alpha subtracts the round-trip cost")


def test_default_cost_bps_from_portfolio_yaml():
    t = close_position(_pos(), "2026-02-01", 110.0, "HOLD", 510.0)   # no cost_bps
    assert t["cost_bps"] == _paper_cost_bps() == 20.0   # config/portfolio.yaml
    print("  ✓ default cost_bps reused from config/portfolio.yaml (single source)")


def test_tr_fields_none_without_adjusted_prices():
    t = close_position(_pos(), "2026-02-01", 110.0, "HOLD", 510.0, cost_bps=20.0)
    assert t["return_pct_tr"] is None and t["alpha_tr_net"] is None
    assert t["capture_basis"] == "spot_only"
    print("  ✓ TR fields None + capture_basis spot_only when no adjusted prices")


def test_tr_fields_computed_when_adjusted_provided():
    # dividend-adjusted: stock +12% TR, SPY +3% TR
    t = close_position(
        _pos(100.0, 500.0), "2026-02-01", 110.0, "HOLD", 510.0, cost_bps=20.0,
        entry_price_adj=100.0, exit_price_adj=112.0,
        spy_entry_adj=500.0, spy_exit_adj=515.0,
    )
    assert t["return_pct_tr"] == round(0.12, 6)
    assert t["spy_return_tr"] == round(0.03, 6)
    assert t["alpha_tr"] == round(0.09, 6)
    assert t["return_pct_tr_net"] == round(0.12 - 0.004, 6)
    assert t["alpha_tr_net"] == round(0.12 - 0.004 - 0.03, 6)   # PRIMARY
    assert t["capture_basis"] == "adjusted"
    print("  ✓ TR + net-TR alpha computed from aligned adjusted closes")


def test_tr_fields_helper_matches_close_position():
    f = tr_fields(100.0, 112.0, 500.0, 515.0, 20.0)
    assert f["alpha_tr_net"] == round(0.12 - 0.004 - 0.03, 6)
    print("  ✓ shared tr_fields() helper matches (single math home)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All honest-return tests passed.")
