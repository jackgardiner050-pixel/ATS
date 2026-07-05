"""Tests for exit_rules_v2 (item 4) — pure evaluator + gated process_screener_results.

The flag-OFF characterization test is the most important one: it proves that with
the feature off (the committed default), behavior is identical to the original
RATING_DOWNGRADE-only rule.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import (
    evaluate_exit_v2,
    process_screener_results,
    open_position,
    DEFAULT_EXIT_V2_PARAMS,
)

TODAY = date(2026, 1, 1)


def _pos(ticker="ACM", entry_date="2025-12-15", pt=130.0, entry_price=100.0):
    return open_position(ticker, entry_date, entry_price, "STRONG_BUY", "MED",
                         pt, 500.0, cohort="cohort_1")


def _params(**over):
    return {**DEFAULT_EXIT_V2_PARAMS, **over}


# ─── each reason in isolation ────────────────────────────────────────────────

def test_rating_downgrade():
    assert evaluate_exit_v2(_pos(), 80.0, "HOLD", TODAY, _params()) == (True, "RATING_DOWNGRADE")
    print("  ✓ RATING_DOWNGRADE")


def test_pt_hit():
    # STRONG_BUY (no downgrade), price >= pt * 1.0
    assert evaluate_exit_v2(_pos(pt=130.0), 135.0, "STRONG_BUY", TODAY, _params()) == (True, "PT_HIT")
    # just below target → no PT_HIT
    assert evaluate_exit_v2(_pos(pt=130.0), 129.0, "STRONG_BUY", TODAY, _params())[0] is False
    print("  ✓ PT_HIT at pt_fraction×target")


def test_time_stop():
    old = _pos(entry_date="2024-01-01")   # held ~2y > 365d
    assert evaluate_exit_v2(old, 80.0, "STRONG_BUY", TODAY, _params()) == (True, "TIME_STOP")
    print("  ✓ TIME_STOP after max_hold_days")


def test_stale():
    p = _params(last_screened={"ACM": "2025-11-01"})   # ~61d > 28d
    assert evaluate_exit_v2(_pos(entry_date="2025-12-15"), 80.0, "STRONG_BUY", TODAY, p) == (True, "STALE")
    print("  ✓ STALE after stale_days unscreened")


def test_no_exit_when_all_clear():
    p = _params(last_screened={"ACM": "2025-12-28"})   # fresh
    assert evaluate_exit_v2(_pos(entry_date="2025-12-15"), 80.0, "STRONG_BUY", TODAY, p) == (False, None)
    print("  ✓ no exit when rating ok, below PT, fresh, within hold window")


# ─── precedence: RATING_DOWNGRADE > PT_HIT > TIME_STOP > STALE ────────────────

def test_precedence_full_ladder():
    old_stale = _params(last_screened={"ACM": "2025-01-01"})
    p = _pos(entry_date="2024-01-01", pt=130.0)          # old (TIME_STOP) + stale
    # downgrade beats everything
    assert evaluate_exit_v2(p, 200.0, "SELL", TODAY, old_stale)[1] == "RATING_DOWNGRADE"
    # no downgrade → PT_HIT beats TIME_STOP/STALE
    assert evaluate_exit_v2(p, 200.0, "STRONG_BUY", TODAY, old_stale)[1] == "PT_HIT"
    # no downgrade, below PT → TIME_STOP beats STALE
    assert evaluate_exit_v2(p, 80.0, "STRONG_BUY", TODAY, old_stale)[1] == "TIME_STOP"
    # no downgrade, below PT, recent entry → STALE
    recent = _pos(entry_date="2025-12-15", pt=130.0)
    assert evaluate_exit_v2(recent, 80.0, "STRONG_BUY", TODAY, old_stale)[1] == "STALE"
    print("  ✓ precedence RATING_DOWNGRADE > PT_HIT > TIME_STOP > STALE")


# ─── flag OFF: byte-identical characterization ───────────────────────────────

def _fixture():
    results = [
        {"ticker": "ACM", "rating": "STRONG_BUY", "confidence": "MED", "current_price": 80.0,
         "price_target": 130.0, "status": "DUE", "ok": True},          # held
        {"ticker": "EMR", "rating": "HOLD", "confidence": "MED", "current_price": 90.0,
         "price_target": 100.0, "status": "DUE", "ok": True},          # downgrade → close
        {"ticker": "NEW", "rating": "STRONG_BUY", "confidence": "MED", "current_price": 50.0,
         "price_target": 70.0, "status": "DUE", "ok": True},           # open
        {"ticker": "SKP", "rating": "SELL", "confidence": "MED", "current_price": 40.0,
         "price_target": 45.0, "status": "SKIPPED", "ok": True},        # skipped → untouched
    ]
    existing = {"ACM": _pos("ACM", pt=130.0, entry_price=72.0),
                "EMR": _pos("EMR", pt=100.0, entry_price=80.0),
                "SKP": _pos("SKP", pt=45.0, entry_price=50.0)}
    return results, existing


def test_flag_off_characterization_identical_to_original():
    results, existing = _fixture()
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 500.0, "2026-01-01")   # exit_rules_v2 defaults OFF
    assert opened == ["NEW"]
    assert closed == ["EMR"]                       # only the downgrade closes
    assert set(positions) == {"ACM", "NEW", "SKP"} # SKP untouched, ACM held
    assert all(t.get("exit_reason") is None for t in closed_trades)   # no v2 tagging
    print("  ✓ flag OFF: SKIPPED untouched, downgrade closes, new opens — original behavior")


# ─── flag ON: SKIPPED-ticker STALE path ──────────────────────────────────────

def test_flag_on_skipped_ticker_stale_closes():
    results, existing = _fixture()
    params = _params(last_screened={"SKP": "2025-01-01"})   # very stale
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 500.0, "2026-01-01",
        exit_rules_v2=True, exit_v2_params=params,
        price_lookup=lambda t: 40.0,                # previousClose fallback for SKP
    )
    assert "SKP" in closed                          # evaluated despite SKIPPED status
    skp_trade = next(t for t in closed_trades if t["ticker"] == "SKP")
    assert skp_trade["exit_reason"] == "STALE"
    assert "EMR" in closed                          # downgrade still closes
    print("  ✓ flag ON evaluates SKIPPED positions — STALE closes SKP with exit_reason")


def test_flag_on_missing_price_holds_with_warning():
    existing = {"SKP": _pos("SKP", pt=45.0)}
    results = [{"ticker": "SKP", "rating": "SELL", "confidence": "MED", "current_price": 40.0,
                "price_target": 45.0, "status": "SKIPPED", "ok": True}]
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 500.0, "2026-01-01",
        exit_rules_v2=True, exit_v2_params=_params(last_screened={"SKP": "2025-01-01"}),
        price_lookup=lambda t: None,                # no price available
    )
    assert closed == [] and "SKP" in positions      # WARN + hold on missing price
    print("  ✓ flag ON + missing price → WARN and hold (no close)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All exit_rules_v2 tests passed.")
