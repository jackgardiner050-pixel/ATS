"""Tests for the paper trading layer (src/paper_trading.py).

All tests are pure — no I/O, no yfinance calls.
"""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import (
    should_enter,
    should_exit,
    open_position,
    close_position,
    process_screener_results,
    load_positions,
    save_positions,
    load_trades,
    append_trade,
    validate_position,
    validate_trade,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_result(ticker, rating, confidence, price=100.0, pt=120.0, status="DUE", ok=True):
    return {
        "ticker": ticker,
        "rating": rating,
        "confidence": confidence,
        "current_price": price,
        "price_target": pt,
        "status": status,
        "ok": ok,
    }


def _make_position(ticker, entry_price=100.0, spy_entry=500.0):
    return open_position(
        ticker=ticker,
        entry_date="2025-01-01",
        entry_price=entry_price,
        entry_rating="STRONG_BUY",
        entry_confidence="MED",
        price_target=130.0,
        spy_entry_price=spy_entry,
    )


# ─────────────────────────────────────────────────────────────────────────────
# open_position / close_position — record structure
# ─────────────────────────────────────────────────────────────────────────────

def test_open_position_creates_correct_entry_record():
    pos = open_position(
        ticker="ACM",
        entry_date="2025-03-01",
        entry_price=72.04,
        entry_rating="STRONG_BUY",
        entry_confidence="MED",
        price_target=95.0,
        spy_entry_price=503.12,
    )
    assert pos["ticker"] == "ACM"
    assert pos["direction"] == "LONG"
    assert pos["entry_price"] == 72.04
    assert pos["entry_date"] == "2025-03-01"
    assert pos["entry_rating"] == "STRONG_BUY"
    assert pos["entry_confidence"] == "MED"
    assert pos["price_target"] == 95.0
    assert pos["spy_entry_price"] == 503.12
    assert pos["constraints"]["no_real_orders"] is True
    assert pos["constraints"]["no_live_pnl_learning"] is True
    print("  ✓ open_position creates correct entry record")


def test_close_position_correctly_computes_return_and_spy_alpha():
    pos = _make_position("ACM", entry_price=100.0, spy_entry=500.0)

    trade = close_position(
        position=pos,
        exit_date="2025-04-01",
        exit_price=110.0,   # +10%
        exit_rating="HOLD",
        spy_exit_price=510.0,  # +2%
    )

    assert trade["return_pct"] == round(0.10, 6)
    assert trade["spy_return_pct"] == round(0.02, 6)
    assert trade["alpha"] == round(0.08, 6)
    assert trade["exit_date"] == "2025-04-01"
    assert trade["exit_rating"] == "HOLD"
    assert trade["constraints"]["no_real_orders"] is True
    print("  ✓ close_position computes return, SPY return, and alpha correctly")


def test_close_position_negative_return():
    pos = _make_position("XYZ", entry_price=100.0, spy_entry=500.0)
    trade = close_position(pos, "2025-04-01", 85.0, "SELL", 510.0)
    assert trade["return_pct"] == round(-0.15, 6)
    assert trade["spy_return_pct"] == round(0.02, 6)
    assert trade["alpha"] == round(-0.17, 6)
    print("  ✓ close_position handles negative return correctly")


# ─────────────────────────────────────────────────────────────────────────────
# Entry gate
# ─────────────────────────────────────────────────────────────────────────────

def test_entry_rule_strong_buy_med_opens():
    assert should_enter("STRONG_BUY", "MED") is True
    print("  ✓ STRONG_BUY + MED → opens")


def test_entry_rule_strong_buy_high_opens():
    assert should_enter("STRONG_BUY", "HIGH") is True
    print("  ✓ STRONG_BUY + HIGH → opens")


def test_entry_rule_strong_buy_low_does_not_open():
    """Low-confidence STRONG_BUY is deliberately excluded."""
    assert should_enter("STRONG_BUY", "LOW") is False
    print("  ✓ STRONG_BUY + LOW → does NOT open (model uncertainty too high)")


def test_entry_rule_buy_does_not_open():
    assert should_enter("BUY", "HIGH") is False
    assert should_enter("BUY", "MED") is False
    print("  ✓ BUY (any confidence) → does NOT open")


def test_entry_rule_hold_does_not_open():
    assert should_enter("HOLD", "HIGH") is False
    print("  ✓ HOLD → does NOT open")


# ─────────────────────────────────────────────────────────────────────────────
# Exit gate
# ─────────────────────────────────────────────────────────────────────────────

def test_exit_rule_strong_buy_holds():
    assert should_exit("STRONG_BUY") is False
    print("  ✓ STRONG_BUY → hold (do not exit)")


def test_exit_rule_buy_holds():
    assert should_exit("BUY") is False
    print("  ✓ BUY → hold (do not exit)")


def test_exit_rule_hold_closes():
    assert should_exit("HOLD") is True
    print("  ✓ HOLD → exit")


def test_exit_rule_sell_closes():
    assert should_exit("SELL") is True
    print("  ✓ SELL → exit")


def test_exit_rule_strong_sell_closes():
    assert should_exit("STRONG_SELL") is True
    print("  ✓ STRONG_SELL → exit")


def test_exit_rule_broken_closes():
    assert should_exit("BROKEN") is True
    print("  ✓ BROKEN → exit")


def test_exit_rule_error_closes():
    assert should_exit("ERROR") is True
    assert should_exit("?") is True
    print("  ✓ ERROR / unknown → exit")


# ─────────────────────────────────────────────────────────────────────────────
# process_screener_results — core logic
# ─────────────────────────────────────────────────────────────────────────────

def test_process_opens_eligible_tickers():
    results = [
        _make_result("ACM", "STRONG_BUY", "MED", price=72.0),
        _make_result("ZTS", "STRONG_BUY", "LOW", price=81.0),   # LOW → should not open
        _make_result("BUY_TICKER", "BUY", "HIGH", price=50.0),  # BUY → should not open
    ]
    positions, closed, opened, closed_t = process_screener_results(results, {}, 500.0, "2025-04-01")
    assert "ACM" in positions
    assert "ZTS" not in positions
    assert "BUY_TICKER" not in positions
    assert opened == ["ACM"]
    assert closed == []
    print("  ✓ process_screener_results opens only STRONG_BUY + MED/HIGH")


def test_process_closes_on_exit_signal():
    existing = {"ACM": _make_position("ACM", entry_price=72.0, spy_entry=500.0)}
    results = [_make_result("ACM", "HOLD", "MED", price=80.0)]  # downgrade → close
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 510.0, "2025-05-01"
    )
    assert "ACM" not in positions
    assert "ACM" in closed
    assert len(closed_trades) == 1
    trade = closed_trades[0]
    assert trade["ticker"] == "ACM"
    assert trade["exit_rating"] == "HOLD"
    assert abs(trade["return_pct"] - (80.0 / 72.0 - 1)) < 1e-6
    print("  ✓ process_screener_results closes positions on exit signal")


def test_process_holds_strong_buy_position():
    existing = {"ACM": _make_position("ACM", entry_price=72.0)}
    results = [_make_result("ACM", "STRONG_BUY", "MED", price=80.0)]
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 510.0, "2025-05-01"
    )
    assert "ACM" in positions          # still open
    assert positions["ACM"]["entry_price"] == 72.0   # unchanged
    assert not closed_trades
    assert not opened
    assert not closed
    print("  ✓ process_screener_results holds existing STRONG_BUY without modification")


def test_process_holds_buy_position():
    existing = {"ACM": _make_position("ACM", entry_price=72.0)}
    results = [_make_result("ACM", "BUY", "MED", price=80.0)]
    positions, closed_trades, _, _ = process_screener_results(
        results, existing, 510.0, "2025-05-01"
    )
    assert "ACM" in positions          # BUY → still hold
    assert not closed_trades
    print("  ✓ process_screener_results holds existing position on BUY rating")


def test_process_skips_skipped_tickers():
    """SKIPPED tickers must not trigger entry or exit."""
    existing = {"ACM": _make_position("ACM")}
    results = [
        _make_result("ACM", "SELL", "MED", status="SKIPPED", ok=True),   # skip → no close
        _make_result("NEW", "STRONG_BUY", "MED", status="SKIPPED", ok=True),  # skip → no open
    ]
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 510.0, "2025-05-01"
    )
    assert "ACM" in positions      # not closed despite SELL rating
    assert "NEW" not in positions  # not opened despite STRONG_BUY
    assert not closed_trades
    print("  ✓ SKIPPED tickers leave positions undisturbed")


def test_process_skips_error_tickers():
    results = [_make_result("BAD", "STRONG_BUY", "MED", status="ERROR", ok=False)]
    positions, closed_trades, opened, closed = process_screener_results(
        results, {}, 500.0, "2025-04-01"
    )
    assert not positions
    print("  ✓ ERROR tickers do not open positions")


def test_process_skips_none_price():
    results = [{"ticker": "ACM", "rating": "STRONG_BUY", "confidence": "MED",
                "current_price": None, "price_target": 90.0, "status": "DUE", "ok": True}]
    positions, _, opened, _ = process_screener_results(results, {}, 500.0, "2025-04-01")
    assert not positions
    assert not opened
    print("  ✓ None current_price is skipped (no open)")


def test_idempotency_paper_run_twice_no_changes():
    """Running process_screener_results twice with same input must be idempotent."""
    results = [_make_result("ACM", "STRONG_BUY", "MED", price=72.0)]

    positions1, _, opened1, _ = process_screener_results(results, {}, 500.0, "2025-04-01")
    positions2, closed2, opened2, closed_t2 = process_screener_results(
        results, positions1, 500.0, "2025-04-01"
    )

    assert opened1 == ["ACM"]
    assert opened2 == []        # second run: already in positions, STRONG_BUY → hold
    assert not closed2
    assert positions1.keys() == positions2.keys()
    print("  ✓ Idempotent: running twice with same screener output makes no changes")


# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers (uses tmp files)
# ─────────────────────────────────────────────────────────────────────────────

def test_save_and_load_positions(tmp_path):
    pos = {"ACM": _make_position("ACM"), "EMR": _make_position("EMR")}
    p = tmp_path / "positions.yaml"
    save_positions(pos, path=p)
    loaded = load_positions(path=p)
    assert set(loaded.keys()) == {"ACM", "EMR"}
    assert loaded["ACM"]["entry_price"] == pos["ACM"]["entry_price"]
    print("  ✓ save/load positions round-trips correctly")


def test_append_and_load_trades(tmp_path):
    pos = _make_position("ACM", entry_price=100.0, spy_entry=500.0)
    from src.paper_trading import close_position
    trade = close_position(pos, "2025-05-01", 115.0, "HOLD", 510.0)
    p = tmp_path / "trades.jsonl"
    append_trade(trade, path=p)
    append_trade(trade, path=p)   # append twice
    loaded = load_trades(path=p)
    assert len(loaded) == 2
    assert loaded[0]["ticker"] == "ACM"
    assert loaded[0]["return_pct"] == round(0.15, 6)
    print("  ✓ append_trade / load_trades round-trips correctly")


def test_load_positions_missing_file(tmp_path):
    result = load_positions(path=tmp_path / "does_not_exist.yaml")
    assert result == {}
    print("  ✓ load_positions returns empty dict for missing file")


def test_load_trades_missing_file(tmp_path):
    result = load_trades(path=tmp_path / "does_not_exist.jsonl")
    assert result == []
    print("  ✓ load_trades returns empty list for missing file")


# ─────────────────────────────────────────────────────────────────────────────
# Coverage gaps — NaN, SKIPPED-hold, duplicate rows, empty input, precision
# ─────────────────────────────────────────────────────────────────────────────

def test_process_skips_nan_price():
    """A NaN current_price must be skipped (no open), like None."""
    results = [_make_result("ACM", "STRONG_BUY", "MED", price=float("nan"))]
    positions, closed, opened, _ = process_screener_results(results, {}, 500.0, "2025-04-01")
    assert positions == {}
    assert opened == []
    print("  ✓ NaN current_price is skipped (no open)")


def test_skipped_status_holds_existing_position():
    """A SKIPPED row for an existing position holds it — no close, unchanged."""
    existing = {"ACM": _make_position("ACM", entry_price=72.0)}
    results = [_make_result("ACM", "STRONG_SELL", "HIGH", price=60.0, status="SKIPPED")]
    positions, closed_trades, opened, closed = process_screener_results(
        results, existing, 500.0, "2025-05-01"
    )
    assert "ACM" in positions
    assert positions["ACM"]["entry_price"] == 72.0   # untouched
    assert not closed_trades and not opened and not closed
    print("  ✓ SKIPPED row holds an existing position (no close even on STRONG_SELL)")


def test_process_duplicate_ticker_first_opens_rest_hold():
    """Duplicate STRONG_BUY rows → one position; first occurrence sets entry data.

    Defined behavior: positions is keyed by ticker, so a ticker can never open
    twice. The first eligible row opens it; a later same-ticker STRONG_BUY row
    finds it already open and holds (idempotent), so the FIRST row's entry_price
    is the one retained.
    """
    results = [
        _make_result("ACM", "STRONG_BUY", "MED", price=72.0),
        _make_result("ACM", "STRONG_BUY", "MED", price=99.0),   # duplicate
    ]
    positions, closed_trades, opened, closed = process_screener_results(
        results, {}, 500.0, "2025-04-01"
    )
    assert list(positions.keys()) == ["ACM"]
    assert opened == ["ACM"]                 # opened exactly once
    assert positions["ACM"]["entry_price"] == 72.0   # first row wins
    assert not closed_trades
    print("  ✓ duplicate STRONG_BUY rows → single position, first row's entry retained")


def test_process_duplicate_ticker_downgrade_after_open_closes():
    """Rows apply in order: an open followed by a same-ticker downgrade closes it."""
    results = [
        _make_result("ACM", "STRONG_BUY", "MED", price=72.0),   # opens
        _make_result("ACM", "HOLD", "MED", price=80.0),         # then downgrades → close
    ]
    positions, closed_trades, opened, closed = process_screener_results(
        results, {}, 500.0, "2025-04-01"
    )
    assert "ACM" not in positions
    assert opened == ["ACM"]
    assert closed == ["ACM"]
    assert len(closed_trades) == 1
    assert closed_trades[0]["entry_price"] == 72.0   # entry from the opening row
    print("  ✓ duplicate rows apply in order: open then downgrade → closed")


def test_process_empty_screener_results_noop():
    """Empty screener output leaves existing positions untouched, opens/closes nothing."""
    existing = {"ACM": _make_position("ACM", entry_price=72.0)}
    positions, closed_trades, opened, closed = process_screener_results(
        [], existing, 500.0, "2025-04-01"
    )
    assert positions == existing
    assert not closed_trades and not opened and not closed
    print("  ✓ empty screener results → no-op")


def test_yaml_roundtrip_preserves_price_target_precision(tmp_path):
    """price_target float precision survives a save → load round-trip."""
    p = tmp_path / "positions.yaml"
    pos = open_position(
        ticker="ACM", entry_date="2025-01-01", entry_price=100.0,
        entry_rating="STRONG_BUY", entry_confidence="MED",
        price_target=123.456789012345, spy_entry_price=503.121314,
    )
    save_positions({"ACM": pos}, path=p)
    loaded = load_positions(path=p)
    assert loaded["ACM"]["price_target"] == 123.456789012345
    assert loaded["ACM"]["spy_entry_price"] == 503.121314
    print("  ✓ YAML round-trip preserves price_target float precision")


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation + malformed-record resilience
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_position_accepts_valid_record():
    validate_position(_make_position("ACM"))   # must not raise
    print("  ✓ validate_position accepts a well-formed record")


def test_validate_position_rejects_missing_key_and_bad_type():
    import pytest
    with pytest.raises(ValueError):
        validate_position({"ticker": "ACM"})                     # missing keys
    bad = _make_position("ACM")
    bad["entry_price"] = "cheap"                                  # wrong type
    with pytest.raises(ValueError):
        validate_position(bad)
    with pytest.raises(ValueError):
        validate_position("not a dict")
    print("  ✓ validate_position rejects missing keys / wrong types / non-dict")


def test_validate_position_requires_valid_cohort():
    import pytest
    # accepts both valid cohorts
    validate_position(open_position("ACM", "2026-05-25", 100.0, "STRONG_BUY", "MED",
                                    130.0, 500.0, cohort="legacy_pre_fix"))
    validate_position(open_position("ACM", "2026-06-01", 100.0, "STRONG_BUY", "MED",
                                    130.0, 500.0, cohort="cohort_1"))
    # missing cohort → fail (do not default it in)
    no_cohort = _make_position("ACM")
    del no_cohort["cohort"]
    with pytest.raises(ValueError):
        validate_position(no_cohort)
    # unknown cohort string → fail
    bad = _make_position("ACM")
    bad["cohort"] = "cohort_99"
    with pytest.raises(ValueError):
        validate_position(bad)
    print("  ✓ validate_position requires a cohort in the allowed set")


def test_validate_trade_requires_valid_cohort():
    import pytest
    pos = _make_position("ACM")
    trade = close_position(pos, "2026-06-01", 115.0, "HOLD", 510.0)
    validate_trade(trade)                      # inherits cohort_1 from the position
    del trade["cohort"]
    with pytest.raises(ValueError):
        validate_trade(trade)
    trade["cohort"] = "not_a_cohort"
    with pytest.raises(ValueError):
        validate_trade(trade)
    print("  ✓ validate_trade requires a cohort in the allowed set")


def test_new_position_defaults_to_cohort_1():
    pos = open_position("ACM", "2026-06-01", 100.0, "STRONG_BUY", "MED", 130.0, 500.0)
    assert pos["cohort"] == "cohort_1"
    print("  ✓ open_position tags new positions cohort_1 by default")


def test_validate_trade_accepts_and_rejects():
    import pytest
    pos = _make_position("ACM", entry_price=100.0, spy_entry=500.0)
    trade = close_position(pos, "2025-05-01", 115.0, "HOLD", 510.0)
    validate_trade(trade)                                        # must not raise
    del trade["alpha"]
    with pytest.raises(ValueError):
        validate_trade(trade)
    print("  ✓ validate_trade accepts a real trade, rejects a missing field")


def test_load_trades_skips_malformed_lines(tmp_path):
    """Bad JSON and schema-invalid lines are skipped, not fatal; line numbers logged."""
    pos = _make_position("ACM", entry_price=100.0, spy_entry=500.0)
    import json
    good = json.dumps(close_position(pos, "2025-05-01", 115.0, "HOLD", 510.0))
    p = tmp_path / "trades.jsonl"
    p.write_text(good + "\n" + "{ this is not json\n" + '{"ticker": "X"}\n' + good + "\n")
    loaded = load_trades(path=p)
    assert len(loaded) == 2                     # only the two valid lines survive
    assert all(t["ticker"] == "ACM" for t in loaded)
    print("  ✓ load_trades skips malformed lines, never crashes")


def test_load_positions_skips_invalid_record(tmp_path):
    import yaml
    good = _make_position("GOOD")
    p = tmp_path / "positions.yaml"
    p.write_text(yaml.dump({"positions": [good, {"ticker": "BAD"}]}))
    loaded = load_positions(path=p)
    assert set(loaded.keys()) == {"GOOD"}       # BAD (missing keys) dropped
    print("  ✓ load_positions skips schema-invalid records")


def test_save_positions_crash_between_tmp_and_replace_keeps_valid_file(tmp_path, monkeypatch):
    """Simulate kill -9 after the tmp write but before os.replace.

    The target positions file must remain the previous *valid* content — never a
    truncated half-write — and the incomplete write must live in the .tmp sidecar.
    """
    import src.io_utils as io_utils
    p = tmp_path / "positions.yaml"
    save_positions({"ACM": _make_position("ACM", entry_price=100.0)}, path=p)
    original = p.read_text()

    def _boom(src, dst):
        raise OSError("simulated crash mid-save")

    monkeypatch.setattr(io_utils.os, "replace", _boom)
    try:
        save_positions({"ACM": _make_position("ACM", entry_price=999.0)}, path=p)
    except OSError:
        pass  # the crash we simulated

    # Target untouched and still loads as the OLD, valid book.
    assert p.read_text() == original
    loaded = load_positions(path=p)
    assert loaded["ACM"]["entry_price"] == 100.0
    # The partial write went to the sidecar, not the live file.
    assert (tmp_path / "positions.yaml.tmp").exists()
    print("  ✓ crash between tmp-write and replace never truncates the live file")


if __name__ == "__main__":
    import tempfile, pathlib

    print("Running paper trading tests...")
    test_open_position_creates_correct_entry_record()
    test_close_position_correctly_computes_return_and_spy_alpha()
    test_close_position_negative_return()
    test_entry_rule_strong_buy_med_opens()
    test_entry_rule_strong_buy_high_opens()
    test_entry_rule_strong_buy_low_does_not_open()
    test_entry_rule_buy_does_not_open()
    test_entry_rule_hold_does_not_open()
    test_exit_rule_strong_buy_holds()
    test_exit_rule_buy_holds()
    test_exit_rule_hold_closes()
    test_exit_rule_sell_closes()
    test_exit_rule_strong_sell_closes()
    test_exit_rule_broken_closes()
    test_exit_rule_error_closes()
    test_process_opens_eligible_tickers()
    test_process_closes_on_exit_signal()
    test_process_holds_strong_buy_position()
    test_process_holds_buy_position()
    test_process_skips_skipped_tickers()
    test_process_skips_error_tickers()
    test_process_skips_none_price()
    test_idempotency_paper_run_twice_no_changes()
    test_process_skips_nan_price()
    test_skipped_status_holds_existing_position()
    test_process_duplicate_ticker_first_opens_rest_hold()
    test_process_duplicate_ticker_downgrade_after_open_closes()
    test_process_empty_screener_results_noop()
    test_validate_position_accepts_valid_record()
    test_validate_position_rejects_missing_key_and_bad_type()
    test_validate_position_requires_valid_cohort()
    test_validate_trade_requires_valid_cohort()
    test_new_position_defaults_to_cohort_1()
    test_validate_trade_accepts_and_rejects()

    with tempfile.TemporaryDirectory() as td:
        tp = pathlib.Path(td)
        test_save_and_load_positions(tp)
        test_append_and_load_trades(tp)
        test_load_positions_missing_file(tp)
        test_load_trades_missing_file(tp)
        test_yaml_roundtrip_preserves_price_target_precision(tp)
        test_load_trades_skips_malformed_lines(tp)
        test_load_positions_skips_invalid_record(tp)

    # Note: test_save_positions_crash_between_tmp_and_replace_keeps_valid_file
    # uses pytest's monkeypatch fixture — run it via `pytest` (not this __main__).
    print("All paper trading tests passed.")
