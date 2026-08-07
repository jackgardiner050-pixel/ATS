"""Tests for src/phaethon/rebalance.py — constitutional MAX_SINGLE_POSITION trim.

Mechanical trim of an EXISTING book: any holding over `cap` is reduced to exactly
cap, the excess becomes released cash (not redistributed — that's a separate,
later feature). Pure function, synthetic fixtures only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.phaethon.rebalance import trim_to_cap


def test_trims_two_over_cap_positions_to_exactly_cap():
    holdings = [
        {"ticker": "CEG", "weight_pct": 13.4},
        {"ticker": "AMZN", "weight_pct": 11.5},
        {"ticker": "JPM", "weight_pct": 7.1},   # under cap
    ]
    trimmed, released, log = trim_to_cap(holdings, cap=0.10)
    by_ticker = {h["ticker"]: h["weight_pct"] for h in trimmed}
    assert by_ticker["CEG"] == 10.0
    assert by_ticker["AMZN"] == 10.0
    assert by_ticker["JPM"] == 7.1                        # untouched
    # released cash sums the two excesses: (13.4-10) + (11.5-10) = 3.4 + 1.5 = 4.9
    assert abs(released - 4.9) < 1e-9
    assert {e["ticker"] for e in log} == {"CEG", "AMZN"}
    print("  ✓ two over-cap positions trimmed to exactly 10%, released cash sums correctly")


def test_under_cap_position_untouched():
    holdings = [{"ticker": "JPM", "weight_pct": 7.1}]
    trimmed, released, log = trim_to_cap(holdings, cap=0.10)
    assert trimmed == [{"ticker": "JPM", "weight_pct": 7.1}]
    assert released == 0.0
    assert log == []
    print("  ✓ a position already under cap is left unchanged")


def test_trim_never_pushes_another_position_over_cap():
    """Trimming only ever reduces the trimmed position's own weight — by construction
    it can never increase (and therefore never breach) any OTHER holding's weight.
    Asserted directly, not just assumed."""
    holdings = [
        {"ticker": "CEG", "weight_pct": 13.4},
        {"ticker": "AMZN", "weight_pct": 11.5},
        {"ticker": "JPM", "weight_pct": 7.1},
    ]
    before = {h["ticker"]: h["weight_pct"] for h in holdings}
    trimmed, _, _ = trim_to_cap(holdings, cap=0.10)
    for h in trimmed:
        assert h["weight_pct"] <= before[h["ticker"]] + 1e-9   # never increases
    assert all(h["weight_pct"] <= 10.0 + 1e-9 for h in trimmed)  # nothing left over cap
    print("  ✓ trimming never pushes another position over cap (weights only ever decrease)")


def test_pure_function_does_not_mutate_input():
    holdings = [{"ticker": "CEG", "weight_pct": 13.4}]
    original = [dict(h) for h in holdings]
    trim_to_cap(holdings, cap=0.10)
    assert holdings == original
    print("  ✓ input list/dicts are not mutated")


def test_other_keys_carried_through_unchanged():
    holdings = [{"ticker": "CEG", "weight_pct": 13.4, "bought_at": 254.83, "last": 261.1}]
    trimmed, _, _ = trim_to_cap(holdings, cap=0.10)
    assert trimmed[0]["bought_at"] == 254.83
    assert trimmed[0]["last"] == 261.1
    assert trimmed[0]["weight_pct"] == 10.0
    print("  ✓ non-weight keys (bought_at, last, ...) survive the trim unchanged")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All phaethon rebalance tests passed.")
