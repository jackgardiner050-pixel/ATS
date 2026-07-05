"""Cross-check: trade-level net return (close_position, item 10) vs the NAV ledger's
portfolio-level per-position net contribution (build_snapshot).

RESULT (see also docs/BATCH_AUDIT): the two RECONCILE within a documented tolerance
of  cost_bps/1e4 × |gross_return|  (a few bps). They are NOT byte-equal by design,
and the reason is precise: both apply a per-side cost haircut using the SAME
config/portfolio.yaml paper_cost_bps, but they apply the EXIT-side haircut to
different notionals —
  * trade-level: net = gross − 2·c            (both sides on the ENTRY notional, flat)
  * NAV ledger : net = (exit/entry)(1−c) − (1+c)   (exit side on the EXIT notional)
The difference is exactly c·gross. Dividends do NOT cause divergence: both use
yfinance auto_adjust closes, so the dividend component is identical by construction;
only the exit-haircut basis differs. So the two reports can never contradict each
other by more than c·|gross| for the same position/period.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import open_position, close_position
from src.portfolio.nav_ledger import build_snapshot

ENTRY, EXIT, COST_BPS = 100.0, 110.0, 20.0
NAV_START, N_TARGET = 100_000, 20


def _trade_level_net_return():
    pos = open_position("ACM", "2026-01-01", ENTRY, "STRONG_BUY", "MED", 130.0, 500.0,
                        cohort="cohort_1")
    t = close_position(pos, "2026-02-01", EXIT, "HOLD", 500.0, cost_bps=COST_BPS)
    return t["return_pct_net"]


def _nav_level_net_return():
    snap = build_snapshot(
        date="2026-02-01", cohort="cohort_1",
        open_positions=[],
        closed_trades=[{"ticker": "ACM", "entry_price": ENTRY, "exit_price": EXIT}],
        prices={}, spy_tr_index=500.0, spy_inception_price=500.0,
        nav_start=NAV_START, n_target_positions=N_TARGET, cost_bps=COST_BPS,
    )
    realized = snap["nav"] - NAV_START           # only realized P&L (no open positions)
    allocation = NAV_START / N_TARGET            # units·entry
    return realized / allocation


def test_trade_and_nav_net_returns_reconcile_within_tolerance():
    trade_net = _trade_level_net_return()
    nav_net = _nav_level_net_return()
    gross = EXIT / ENTRY - 1.0
    tolerance = (COST_BPS / 1e4) * abs(gross)    # c·gross — documented above

    diff = abs(trade_net - nav_net)
    assert diff <= tolerance + 1e-9, (
        f"trade_net={trade_net}, nav_net={nav_net}, diff={diff} > tol={tolerance}")
    # and the difference is EXACTLY c·gross — proving the reason, not a coincidence
    assert abs(diff - tolerance) < 1e-9
    print(f"  ✓ reconciled: trade_net={trade_net:.6f} nav_net={nav_net:.6f} "
          f"diff={diff:.6f} == c·gross={tolerance:.6f}")


if __name__ == "__main__":
    test_trade_and_nav_net_returns_reconcile_within_tolerance()
    print("Reconciliation test passed.")
