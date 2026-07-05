"""Legacy Cohort forced-sunset mechanism (protocol §1.2).

Every legacy_pre_fix position force-closes on/after LEGACY_SUNSET_DATE (2026-08-23)
with exit_reason=FORCED_SUNSET, regardless of rating and INDEPENDENT of exit_rules_v2.
cohort_1 is never touched by this check.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import process_screener_results, open_position, LEGACY_SUNSET_DATE

BEFORE = "2026-08-22"    # day before sunset
ON = "2026-08-23"        # sunset date
AFTER = "2026-09-15"     # after sunset


def _legacy(ticker="LEG", pt=130.0, entry=100.0):
    return open_position(ticker, "2026-05-25", entry, "STRONG_BUY", "MED", pt, 500.0,
                         cohort="legacy_pre_fix")


def _c1(ticker="C1", pt=130.0, entry=100.0):
    return open_position(ticker, "2026-05-25", entry, "STRONG_BUY", "MED", pt, 500.0,
                         cohort="cohort_1")


def _result(ticker, rating="STRONG_BUY", price=120.0, status="DUE"):
    return {"ticker": ticker, "rating": rating, "confidence": "MED", "current_price": price,
            "price_target": 130.0, "status": status, "ok": True}


def test_sunset_date_is_named_constant():
    from datetime import date
    assert LEGACY_SUNSET_DATE == date(2026, 8, 23)
    print("  ✓ LEGACY_SUNSET_DATE is a named, auditable constant (2026-08-23)")


def test_legacy_before_sunset_does_not_force_close():
    positions, closed_trades, opened, closed = process_screener_results(
        [_result("LEG")], {"LEG": _legacy("LEG")}, 500.0, BEFORE)
    assert "LEG" in positions and not closed
    print("  ✓ legacy before sunset → not force-closed")


def test_legacy_on_and_after_sunset_force_closes_regardless_of_rating():
    for today in (ON, AFTER):
        for rating in ("STRONG_BUY", "HOLD", "SELL"):   # regardless of rating
            positions, closed_trades, opened, closed = process_screener_results(
                [_result("LEG", rating=rating)], {"LEG": _legacy("LEG")}, 500.0, today)
            assert "LEG" in closed, f"{today}/{rating}"
            assert closed_trades[0]["exit_reason"] == "FORCED_SUNSET", f"{today}/{rating}"
            assert closed_trades[0]["cohort"] == "legacy_pre_fix"
    print("  ✓ legacy on/after sunset → FORCED_SUNSET regardless of rating")


def test_forced_sunset_fires_identically_regardless_of_flag():
    for flag in (False, True):
        positions, closed_trades, opened, closed = process_screener_results(
            [_result("LEG")], {"LEG": _legacy("LEG")}, 500.0, ON,
            exit_rules_v2=flag, exit_v2_params=None)
        assert "LEG" in closed and closed_trades[0]["exit_reason"] == "FORCED_SUNSET"
    print("  ✓ forced sunset fires identically whether exit_rules_v2 is true or false")


def test_cohort1_never_force_closed_by_sunset():
    # even well after the sunset date, a cohort_1 STRONG_BUY position is held, not sunset-closed
    positions, closed_trades, opened, closed = process_screener_results(
        [_result("C1")], {"C1": _c1("C1")}, 500.0, AFTER)
    assert "C1" in positions and not closed
    # and with the flag on too
    positions, closed_trades, opened, closed = process_screener_results(
        [_result("C1")], {"C1": _c1("C1")}, 500.0, AFTER, exit_rules_v2=True)
    assert "C1" in positions and not closed
    print("  ✓ cohort_1 never affected by the sunset check, any date, any flag state")


def test_legacy_sunset_unscreened_uses_price_lookup():
    positions, closed_trades, opened, closed = process_screener_results(
        [], {"LEG": _legacy("LEG")}, 500.0, ON, price_lookup=lambda t: 115.0)
    assert "LEG" in closed
    assert closed_trades[0]["exit_reason"] == "FORCED_SUNSET"
    assert closed_trades[0]["exit_price"] == 115.0
    print("  ✓ unscreened legacy sunset uses price_lookup for the exit price")


def test_legacy_sunset_no_price_holds_until_priced():
    positions, closed_trades, opened, closed = process_screener_results(
        [], {"LEG": _legacy("LEG")}, 500.0, ON, price_lookup=None)
    assert "LEG" in positions and not closed   # no price → WARN + hold
    print("  ✓ legacy sunset with no price available → hold (deferred until priced)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All forced-sunset tests passed.")
