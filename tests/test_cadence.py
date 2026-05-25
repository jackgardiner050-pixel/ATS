"""Unit tests for src/cadence.py.

All tests are offline — no yfinance or EDGAR calls. The _earnings_override
parameter on is_due() is used to inject True/False without hitting the network.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.cadence import (
    apply_force,
    compute_next_due,
    is_due,
    load_state,
    save_state,
    update_state,
)


# ---------------------------------------------------------------------------
# compute_next_due — exhaustive cadence table coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rating,confidence,expected_days", [
    ("STRONG_BUY",  "HIGH",    7),
    ("STRONG_BUY",  "MED",     7),
    ("STRONG_BUY",  "LOW",     7),
    ("STRONG_BUY",  "UNKNOWN", 7),
    ("BUY",         "HIGH",    7),
    ("BUY",         "MED",     7),
    ("BUY",         "LOW",     7),
    ("BUY",         "UNKNOWN", 7),
    ("HOLD",        "HIGH",   28),
    ("HOLD",        "MED",    14),
    ("HOLD",        "LOW",    14),
    ("HOLD",        "UNKNOWN",14),
    ("SELL",        "HIGH",   28),
    ("SELL",        "MED",    28),
    ("SELL",        "LOW",    28),
    ("SELL",        "UNKNOWN",28),
    ("STRONG_SELL", "HIGH",   56),
    ("STRONG_SELL", "MED",    42),
    ("STRONG_SELL", "LOW",    14),
    ("STRONG_SELL", "UNKNOWN",42),
    ("BROKEN",      "HIGH",   28),
    ("BROKEN",      "MED",    28),
    ("BROKEN",      "LOW",    28),
    ("BROKEN",      "UNKNOWN",28),
])
def test_compute_next_due(rating, confidence, expected_days):
    base = date(2026, 5, 25)
    result = compute_next_due(rating, confidence, base)
    assert result == base + timedelta(days=expected_days), (
        f"{rating}/{confidence}: expected +{expected_days}d, got {(result - base).days}d"
    )


def test_compute_next_due_unknown_rating_defaults_to_28():
    base = date(2026, 5, 25)
    result = compute_next_due("GIBBERISH", "HIGH", base)
    assert result == base + timedelta(days=28)


# ---------------------------------------------------------------------------
# is_due — no prior record
# ---------------------------------------------------------------------------

def test_no_prior_record_is_due():
    assert is_due("NEWT", date.today(), state={})


# ---------------------------------------------------------------------------
# is_due — due by date
# ---------------------------------------------------------------------------

def test_due_when_past_next_due_date():
    today = date(2026, 7, 30)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": "2026-05-25",
        "last_rating": "HOLD",
        "last_confidence": "HIGH",
        "next_due_date": "2026-06-22",   # 28 days after 2026-05-25
        "force_rescreen": False,
    }}
    assert is_due("AGX", today, state=state, _earnings_override=False)


def test_not_due_before_next_due_date():
    today = date(2026, 5, 26)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": "2026-05-25",
        "last_rating": "HOLD",
        "last_confidence": "HIGH",
        "next_due_date": "2026-06-22",
        "force_rescreen": False,
    }}
    assert not is_due("AGX", today, state=state, _earnings_override=False)


def test_due_on_exact_next_due_date():
    today = date(2026, 6, 22)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": "2026-05-25",
        "last_rating": "HOLD",
        "last_confidence": "HIGH",
        "next_due_date": "2026-06-22",
        "force_rescreen": False,
    }}
    assert is_due("AGX", today, state=state, _earnings_override=False)


# ---------------------------------------------------------------------------
# is_due — force flags
# ---------------------------------------------------------------------------

def test_force_rescreen_flag_overrides_cadence():
    today = date(2026, 5, 26)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": "2026-05-25",
        "last_rating": "STRONG_SELL",
        "last_confidence": "HIGH",
        "next_due_date": "2026-07-20",   # 8 weeks out
        "force_rescreen": True,
    }}
    assert is_due("AGX", today, state=state)


def test_no_next_due_date_is_due():
    today = date(2026, 5, 26)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": "2026-05-25",
        "last_rating": "HOLD",
        "last_confidence": "HIGH",
        "next_due_date": None,
        "force_rescreen": False,
    }}
    assert is_due("AGX", today, state=state, _earnings_override=False)


# ---------------------------------------------------------------------------
# is_due — earnings override
# ---------------------------------------------------------------------------

def test_earnings_override_true_triggers_due():
    today = date(2026, 5, 26)
    state = {"LMT": {
        "ticker": "LMT",
        "last_screen_date": "2026-05-25",
        "last_rating": "STRONG_SELL",
        "last_confidence": "HIGH",
        "next_due_date": "2026-07-20",
        "force_rescreen": False,
    }}
    assert is_due("LMT", today, state=state, _earnings_override=True)


def test_earnings_override_false_respects_cadence():
    today = date(2026, 5, 26)
    state = {"LMT": {
        "ticker": "LMT",
        "last_screen_date": "2026-05-25",
        "last_rating": "STRONG_SELL",
        "last_confidence": "HIGH",
        "next_due_date": "2026-07-20",
        "force_rescreen": False,
    }}
    assert not is_due("LMT", today, state=state, _earnings_override=False)


# ---------------------------------------------------------------------------
# is_due — BROKEN rating cadence
# ---------------------------------------------------------------------------

def test_broken_rating_4_week_cadence():
    base = date(2026, 5, 25)
    next_due = compute_next_due("BROKEN", "UNKNOWN", base)
    assert next_due == base + timedelta(days=28)

    today_before = base + timedelta(days=27)
    today_on = base + timedelta(days=28)
    state = {"XFAIL": {
        "ticker": "XFAIL",
        "last_screen_date": str(base),
        "last_rating": "BROKEN",
        "last_confidence": "UNKNOWN",
        "next_due_date": str(next_due),
        "force_rescreen": False,
    }}
    assert not is_due("XFAIL", today_before, state=state, _earnings_override=False)
    assert is_due("XFAIL", today_on, state=state, _earnings_override=False)


# ---------------------------------------------------------------------------
# apply_force
# ---------------------------------------------------------------------------

def test_apply_force_existing_ticker():
    today = date(2026, 5, 25)
    state = {"AGX": {
        "ticker": "AGX",
        "last_screen_date": str(today),
        "last_rating": "HOLD",
        "last_confidence": "HIGH",
        "next_due_date": "2026-12-31",
        "force_rescreen": False,
    }}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = apply_force(["AGX"], state=state, path=path)
        assert updated["AGX"]["force_rescreen"] is True
        assert is_due("AGX", today, state=updated)


def test_apply_force_new_ticker_creates_record():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = apply_force(["NEWT"], state={}, path=path)
        assert "NEWT" in updated
        assert updated["NEWT"]["force_rescreen"] is True
        assert is_due("NEWT", date.today(), state=updated)


def test_apply_force_empty_list_forces_all():
    state = {
        "A": {"ticker": "A", "force_rescreen": False, "next_due_date": "2026-12-31",
              "last_screen_date": "2026-05-25", "last_rating": "HOLD", "last_confidence": "HIGH"},
        "B": {"ticker": "B", "force_rescreen": False, "next_due_date": "2026-12-31",
              "last_screen_date": "2026-05-25", "last_rating": "BUY", "last_confidence": "MED"},
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = apply_force([], state=state, path=path)
        assert updated["A"]["force_rescreen"] is True
        assert updated["B"]["force_rescreen"] is True


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------

def test_update_state_buy_sets_7_day_cadence():
    today = date(2026, 5, 25)
    result = {"rating": "BUY", "confidence": "HIGH", "price_target_12m": 150.0, "expected_return": 0.20}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = update_state("AAPL", result, state={}, path=path, today=today)
        rec = updated["AAPL"]
        assert rec["last_rating"] == "BUY"
        assert rec["next_due_date"] == str(today + timedelta(days=7))
        assert rec["force_rescreen"] is False


def test_update_state_strong_sell_high_sets_56_day_cadence():
    today = date(2026, 5, 25)
    result = {"rating": "STRONG_SELL", "confidence": "HIGH", "price_target_12m": 50.0, "expected_return": -0.70}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = update_state("SELL1", result, state={}, path=path, today=today)
        assert updated["SELL1"]["next_due_date"] == str(today + timedelta(days=56))


def test_update_state_clears_force_flag():
    today = date(2026, 5, 25)
    state = {"AGX": {
        "ticker": "AGX", "last_screen_date": "2026-05-10",
        "last_rating": "HOLD", "last_confidence": "HIGH",
        "next_due_date": "2026-05-24", "force_rescreen": True,
    }}
    result = {"rating": "HOLD", "confidence": "HIGH", "price_target_12m": 200.0, "expected_return": 0.05}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        updated = update_state("AGX", result, state=state, path=path, today=today)
        assert updated["AGX"]["force_rescreen"] is False


# ---------------------------------------------------------------------------
# load_state / save_state round-trip
# ---------------------------------------------------------------------------

def test_load_save_roundtrip():
    state = {
        "AGX": {
            "ticker": "AGX", "last_rating": "BUY", "last_confidence": "HIGH",
            "last_screen_date": "2026-05-25", "next_due_date": "2026-06-01",
            "force_rescreen": False, "notes": "",
        },
        "PWR": {
            "ticker": "PWR", "last_rating": "HOLD", "last_confidence": "MED",
            "last_screen_date": "2026-05-25", "next_due_date": "2026-06-08",
            "force_rescreen": False, "notes": "",
        },
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "state.yaml"
        save_state(state, path)
        loaded = load_state(path)
        assert set(loaded.keys()) == {"AGX", "PWR"}
        assert loaded["AGX"]["last_rating"] == "BUY"
        assert loaded["PWR"]["next_due_date"] == "2026-06-08"


def test_load_state_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "nonexistent.yaml"
        assert load_state(path) == {}


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call(["python3", "-m", "pytest", __file__, "-v"]))
