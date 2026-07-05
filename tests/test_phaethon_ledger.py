"""Tests for the arm B cash-accounting fix (src/phaethon/ledger.py).

The failure mode: sequential buys exceeding available cash → negative cash / >100%
gross. After the fix, the reconstructed ledger must either bound cash_pct within
[0, 100%] and gross ≤ 100%+tol, OR reject the breaching order (it does the latter).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.phaethon.ledger import reconstruct_ledger, restate_book
from src.phaethon.scorecard import total_value, holdings_view

TOL = 0.5


def test_rejects_buy_that_breaches_available_cash():
    buys = [{"ticker": "A", "shares": 1, "price": 4000},
            {"ticker": "B", "shares": 1, "price": 4000},
            {"ticker": "C", "shares": 1, "price": 4000}]   # 12000 total on 10000
    led = reconstruct_ledger(10000, buys)
    assert [b["ticker"] for b in led["accepted"]] == ["A", "B"]
    assert [b["ticker"] for b in led["rejected"]] == ["C"]      # breaching order rejected
    assert led["cash"] == 2000                                 # never negative
    print("  ✓ over-cash buy is rejected, not executed into negative cash")


def _leveraged_book():
    """Synthetic reproduction of arm B: sequential buys past 100% → cash negative."""
    # start ~10000; buy 3×4000 (two fit, third over-allocates via a stale-NAV size)
    return {
        "cash": -2000.0,   # BUG: went negative (bought 12000 on 10000)
        "holdings": {
            "A": {"shares": 1, "entry_price": 4000, "last_price": 4200, "entry_date": "2026-06-24"},
            "B": {"shares": 1, "entry_price": 4000, "last_price": 3900, "entry_date": "2026-06-24"},
            "C": {"shares": 1, "entry_price": 4000, "last_price": 4100, "entry_date": "2026-06-29"},
        },
    }


def test_restate_book_bounds_cash_and_gross():
    corrected, rejected = restate_book(_leveraged_book())
    # implied starting = cash(-2000) + Σcost(12000) = 10000; C (06-29) rejected
    assert corrected["cash"] >= 0
    assert [r["ticker"] for r in rejected] == ["C"]

    tv = total_value(corrected)
    cash_pct = corrected["cash"] / tv * 100
    gross = sum(h["weight_pct"] for h in holdings_view(corrected, "B", tv))
    assert 0 <= cash_pct <= 100, cash_pct
    assert gross <= 100 + TOL, gross
    print(f"  ✓ restated: cash_pct={cash_pct:.1f}% in [0,100], gross={gross:.1f}% ≤ 100%+tol")


def test_restate_conforming_book_is_unchanged():
    """A book already within cash never rejects anything."""
    book = {"cash": 5000.0, "holdings": {
        "A": {"shares": 1, "entry_price": 3000, "last_price": 3000, "entry_date": "2026-06-24"},
        "B": {"shares": 1, "entry_price": 2000, "last_price": 2000, "entry_date": "2026-06-24"}}}
    corrected, rejected = restate_book(book)
    assert rejected == [] and set(corrected["holdings"]) == {"A", "B"}
    assert corrected["cash"] == 5000.0
    print("  ✓ a within-cash book is left unchanged (no false rejections)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All phaethon ledger tests passed.")
