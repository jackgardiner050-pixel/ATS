"""Unit tests for src/portfolio/nav_ledger.py — pure, synthetic series only."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.portfolio.nav_ledger import (
    compute_units,
    max_drawdown,
    build_snapshot,
    upsert_snapshots,
    compute_performance,
)

NAV_START = 100_000
N_TARGET = 20
COST_BPS = 20


# ─── sizing ──────────────────────────────────────────────────────────────────

def test_compute_units():
    # (100000 / 20) / 50 = 100 units
    assert compute_units(NAV_START, N_TARGET, 50.0) == 100.0
    import pytest
    with pytest.raises(ValueError):
        compute_units(NAV_START, N_TARGET, 0.0)
    print("  ✓ compute_units: 5000 notional / price")


# ─── drawdown exactness ──────────────────────────────────────────────────────

def test_max_drawdown_exact():
    assert max_drawdown([100, 120, 80, 110]) == (120 - 80) / 120   # exactly 1/3
    assert max_drawdown([100, 100, 100]) == 0.0
    assert max_drawdown([100, 90, 80, 70]) == (100 - 70) / 100     # 0.30
    print("  ✓ max_drawdown is exact (peak-to-trough)")


# ─── snapshot construction ───────────────────────────────────────────────────

def _pos(ticker, entry_price, units=None):
    r = {"ticker": ticker, "entry_price": entry_price}
    if units is not None:
        r["units"] = units
    return r


def test_build_snapshot_open_only_costs_drag_nav_below_start():
    # one position, close == entry → NAV = start minus the entry haircut only
    snap = build_snapshot(
        date="2026-07-06", cohort="cohort_1",
        open_positions=[_pos("ACM", 50.0)],
        closed_trades=[],
        prices={"ACM": 50.0},
        spy_tr_index=500.0, spy_inception_price=500.0,
        nav_start=NAV_START, n_target_positions=N_TARGET, cost_bps=COST_BPS,
    )
    units = 5000 / 50.0                       # 100
    cost = COST_BPS / 10_000                   # 0.002
    expected_nav = NAV_START - units * 50.0 * cost   # start - 5000*0.002 = 99990
    assert snap["n_positions"] == 1
    assert snap["positions"]["ACM"]["units"] == units
    assert abs(snap["nav"] - round(expected_nav, 2)) < 1e-6
    assert snap["benchmark_nav"] == NAV_START           # spy flat at inception
    print("  ✓ build_snapshot: entry cost drags NAV below start; benchmark starts at NAV")


def test_build_snapshot_uses_persisted_units_and_marks_to_market():
    snap = build_snapshot(
        date="2026-07-07", cohort="cohort_1",
        open_positions=[_pos("ACM", 50.0, units=100.0)],
        closed_trades=[],
        prices={"ACM": 55.0},                  # +10%
        spy_tr_index=505.0, spy_inception_price=500.0,
        nav_start=NAV_START, n_target_positions=N_TARGET, cost_bps=COST_BPS,
    )
    assert snap["positions"]["ACM"]["value"] == round(100.0 * 55.0, 2)
    assert snap["benchmark_nav"] == round(NAV_START * (505.0 / 500.0), 2)
    print("  ✓ build_snapshot: persisted units marked to market; benchmark tracks SPY TR")


def test_build_snapshot_realized_pnl_from_closed_trades():
    snap = build_snapshot(
        date="2026-07-08", cohort="cohort_1",
        open_positions=[],
        closed_trades=[{"ticker": "X", "entry_price": 50.0, "exit_price": 60.0}],
        prices={},
        spy_tr_index=500.0, spy_inception_price=500.0,
        nav_start=NAV_START, n_target_positions=N_TARGET, cost_bps=COST_BPS,
    )
    units = 5000 / 50.0
    cost = COST_BPS / 10_000
    realized = units * 60.0 * (1 - cost) - units * 50.0 * (1 + cost)
    assert abs(snap["nav"] - round(NAV_START + realized, 2)) < 1e-6
    assert snap["n_positions"] == 0
    print("  ✓ build_snapshot: realized P&L from closed trades flows to NAV")


def test_missing_price_marks_flat_not_zero():
    snap = build_snapshot(
        date="2026-07-09", cohort="cohort_1",
        open_positions=[_pos("ACM", 50.0, units=100.0)],
        closed_trades=[], prices={},           # no price for ACM
        spy_tr_index=500.0, spy_inception_price=500.0,
        nav_start=NAV_START, n_target_positions=N_TARGET, cost_bps=COST_BPS,
    )
    assert snap["positions"]["ACM"]["close"] == 50.0   # flat fallback at entry price
    print("  ✓ missing price marks the sleeve flat, never zero")


# ─── idempotent upsert ───────────────────────────────────────────────────────

def test_upsert_replaces_same_date_and_cohort():
    existing = [
        {"date": "2026-07-06", "cohort": "cohort_1", "nav": 100.0},
        {"date": "2026-07-06", "cohort": "legacy_pre_fix", "nav": 200.0},
    ]
    new = [{"date": "2026-07-06", "cohort": "cohort_1", "nav": 999.0}]
    merged = upsert_snapshots(existing, new)
    c1 = [r for r in merged if r["cohort"] == "cohort_1"]
    legacy = [r for r in merged if r["cohort"] == "legacy_pre_fix"]
    assert len(c1) == 1 and c1[0]["nav"] == 999.0       # replaced, not duplicated
    assert len(legacy) == 1 and legacy[0]["nav"] == 200.0  # other cohort untouched
    print("  ✓ upsert replaces same (date, cohort), leaves others intact")


def test_upsert_appends_new_date():
    existing = [{"date": "2026-07-06", "cohort": "cohort_1", "nav": 100.0}]
    new = [{"date": "2026-07-07", "cohort": "cohort_1", "nav": 101.0}]
    merged = upsert_snapshots(existing, new)
    assert [r["date"] for r in merged] == ["2026-07-06", "2026-07-07"]
    print("  ✓ upsert appends a genuinely new date")


# ─── performance: synthetic series ───────────────────────────────────────────

def _series(cohort, navs, benches):
    return [
        {"date": f"2026-07-{i+1:02d}", "cohort": cohort, "nav": nav, "benchmark_nav": b}
        for i, (nav, b) in enumerate(zip(navs, benches))
    ]


def test_performance_flat_series():
    hist = _series("cohort_1", [100_000] * 6, [100_000] * 6)
    perf = compute_performance(hist, "cohort_1")
    assert perf["twr"] == 0.0
    assert perf["excess"] == 0.0
    assert perf["max_dd"] == 0.0
    assert perf["information_ratio"] is None   # zero tracking error → undefined
    print("  ✓ flat series: twr=0, excess=0, max_dd=0, IR undefined")


def test_performance_linear_up_positive_ir_and_sharpe():
    navs = [100_000 + 2_000 * i for i in range(6)]   # +10% linear over the window
    bench = [100_000] * 6                              # SPY flat
    perf = compute_performance(_series("cohort_1", navs, bench), "cohort_1")
    assert abs(perf["twr"] - 0.10) < 1e-9
    assert perf["spy_twr"] == 0.0
    assert perf["excess"] > 0
    assert perf["information_ratio"] is not None and perf["information_ratio"] > 0  # sign
    assert perf["sharpe"] is not None and perf["sharpe"] > 0
    assert perf["max_dd"] == 0.0
    print("  ✓ linear-up vs flat SPY: excess>0, IR>0, sharpe>0")


def test_performance_underperformance_negative_ir():
    navs = [100_000 - 1_000 * i for i in range(6)]     # book falls
    bench = [100_000 + 1_000 * i for i in range(6)]    # SPY rises
    perf = compute_performance(_series("cohort_1", navs, bench), "cohort_1")
    assert perf["excess"] < 0
    assert perf["information_ratio"] is not None and perf["information_ratio"] < 0  # sign
    print("  ✓ underperformance vs rising SPY: excess<0, IR<0")


def test_performance_crash_recover_max_dd_exact():
    navs = [100_000, 120_000, 80_000, 110_000]
    bench = [100_000, 100_000, 100_000, 100_000]
    perf = compute_performance(_series("cohort_1", navs, bench), "cohort_1")
    assert abs(perf["max_dd"] - (120_000 - 80_000) / 120_000) < 1e-12   # exactly 1/3
    print("  ✓ crash-recover: max_dd is exact (1/3)")


def test_performance_insufficient_history():
    perf = compute_performance(_series("cohort_1", [100_000], [100_000]), "cohort_1")
    assert perf["n_days"] == 1
    assert perf["twr"] is None and perf["information_ratio"] is None
    print("  ✓ single snapshot: return metrics are None, never extrapolated")


def test_performance_cohorts_are_separated():
    hist = (_series("cohort_1", [100_000, 110_000], [100_000, 100_000])
            + _series("legacy_pre_fix", [100_000, 90_000], [100_000, 100_000]))
    c1 = compute_performance(hist, "cohort_1")
    legacy = compute_performance(hist, "legacy_pre_fix")
    assert c1["twr"] > 0 and legacy["twr"] < 0     # never blended
    print("  ✓ compute_performance filters strictly by cohort")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All nav_ledger tests passed.")
