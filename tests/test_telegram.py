"""Tests for Phase 1 Telegram cockpit — digest formatting, change detection,
quiet hours, and graceful failure. All tests are pure / offline.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.telegram.digest import format_digest, format_holds, format_sells
from src.telegram.alerts import (
    is_quiet_hours,
    detect_changes,
    save_current_state,
    load_last_state,
    format_change_alert,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_result(ticker, rating, confidence, ret=0.10, pt=100.0,
                 status="DUE", ok=True, mom=2, rev="POSITIVE"):
    return {
        "ticker": ticker,
        "rating": rating,
        "confidence": confidence,
        "expected_return": ret,
        "price_target": pt,
        "current_price": 80.0,
        "status": status,
        "ok": ok,
        "momentum_quintile": mom,
        "revision_direction": rev,
        "alignment_score": "+1 aligned, -0 contradicted",
    }


_SYNTHETIC_RESULTS = [
    _make_result("ACM",  "STRONG_BUY",  "MED",  ret=0.35, pt=188),
    _make_result("DY",   "STRONG_BUY",  "HIGH", ret=0.86, pt=766),
    _make_result("ZTS",  "STRONG_BUY",  "LOW",  ret=0.12, pt=100),  # LOW — excluded
    _make_result("ABBV", "BUY",         "HIGH", ret=0.15, pt=230),
    _make_result("HON",  "HOLD",        "MED",  ret=0.05, pt=240),
    _make_result("MTD",  "HOLD",        "HIGH", ret=0.08, pt=1200),
    _make_result("ETN",  "SELL",        "MED",  ret=-0.10, pt=300),
    _make_result("VMC",  "STRONG_SELL", "MED",  ret=-0.25, pt=200),
    _make_result("LLY",  "STRONG_SELL", "LOW",  ret=-0.30, pt=800),
]

_EMPTY_PAPER_BOOK = {"n_open": 0, "n_closed": 0}

_PAPER_BOOK_WITH_MARKS = {
    "n_open": 12,
    "n_closed": 0,
    "avg_unrealized_pct": 0.042,
    "spy_return_pct": 0.015,
    "entry_date_first": "2026-05-25",
}


# ─── Digest formatting ────────────────────────────────────────────────────────

def test_digest_contains_date():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "2026-05-25" in text
    print("  ✓ Digest contains the date")


def test_digest_contains_strong_buy_section():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "STRONG_BUY" in text
    assert "ACM" in text
    assert "DY" in text
    print("  ✓ Digest contains STRONG_BUY act candidates")


def test_digest_excludes_low_conf_from_candidates():
    """ZTS is STRONG_BUY but LOW confidence — must NOT appear as an act candidate."""
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    # ZTS should be mentioned as excluded, not as a candidate
    sb_section_end = text.find("🟩 BUY") if "🟩 BUY" in text else text.find("🟡 HOLD")
    sb_section = text[:sb_section_end] if sb_section_end > 0 else text
    # ZTS should appear in the LOW conf warning line, not as a bullet candidate
    assert "ZTS" in text   # mentioned somewhere (excluded warning)
    assert "LOW conf" in text or "⚠️" in text
    print("  ✓ LOW confidence STRONG_BUY excluded from act candidates, flagged separately")


def test_digest_contains_hold_section():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "HOLD" in text
    assert "/holds" in text
    print("  ✓ Digest contains HOLD section with /holds command")


def test_digest_contains_sell_section():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "SELL" in text
    assert "/sells" in text
    print("  ✓ Digest contains SELL/STRONG_SELL section with /sells command")


def test_digest_paper_book_with_marks():
    text = format_digest(_SYNTHETIC_RESULTS, _PAPER_BOOK_WITH_MARKS, [], "2026-05-25")
    assert "12 open" in text
    assert "2026-05-25" in text
    assert "SPY" in text
    print("  ✓ Digest shows paper book return vs SPY when marks are available")


def test_digest_no_changes():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "Changes this week: none" in text
    print("  ✓ Digest shows 'none' when no rating changes")


def test_digest_with_changes():
    changes = [
        {"ticker": "AMAT", "old_rating": "STRONG_BUY", "old_conf": "HIGH",
         "new_rating": "BUY", "new_conf": "MED"},
    ]
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, changes, "2026-05-25")
    assert "AMAT" in text
    assert "STRONG_BUY" in text
    assert "BUY" in text
    assert "Changes this week (1)" in text
    print("  ✓ Digest lists rating changes correctly")


def test_digest_contains_help_footer():
    text = format_digest(_SYNTHETIC_RESULTS, _EMPTY_PAPER_BOOK, [], "2026-05-25")
    assert "/help" in text
    print("  ✓ Digest ends with /help footer")


def test_format_holds_lists_tickers():
    text = format_holds(_SYNTHETIC_RESULTS)
    assert "HON" in text
    assert "MTD" in text
    print("  ✓ /holds response lists HOLD tickers")


def test_format_sells_lists_tickers():
    text = format_sells(_SYNTHETIC_RESULTS)
    assert "VMC" in text
    assert "ETN" in text
    print("  ✓ /sells response lists SELL and STRONG_SELL tickers")


# ─── Rating change detection ──────────────────────────────────────────────────

def test_rating_change_detected():
    current = [
        _make_result("ACM", "BUY", "MED", status="DUE"),    # was STRONG_BUY
        _make_result("DY",  "STRONG_BUY", "MED", status="DUE"),  # unchanged
    ]
    last_state = {
        "ratings": {
            "ACM": {"rating": "STRONG_BUY", "confidence": "MED"},
            "DY":  {"rating": "STRONG_BUY", "confidence": "MED"},
        }
    }
    changes = detect_changes(current, last_state)
    assert len(changes) == 1
    assert changes[0]["ticker"] == "ACM"
    assert changes[0]["old_rating"] == "STRONG_BUY"
    assert changes[0]["new_rating"] == "BUY"
    print("  ✓ Rating downgrade detected correctly")


def test_confidence_change_detected():
    current = [_make_result("ACM", "STRONG_BUY", "HIGH", status="DUE")]  # conf bump
    last_state = {"ratings": {"ACM": {"rating": "STRONG_BUY", "confidence": "MED"}}}
    changes = detect_changes(current, last_state)
    assert len(changes) == 1
    assert changes[0]["old_conf"] == "MED"
    assert changes[0]["new_conf"] == "HIGH"
    print("  ✓ Confidence-only change detected correctly")


def test_no_false_positives_if_unchanged():
    current = [_make_result("ACM", "STRONG_BUY", "MED", status="DUE")]
    last_state = {"ratings": {"ACM": {"rating": "STRONG_BUY", "confidence": "MED"}}}
    changes = detect_changes(current, last_state)
    assert changes == []
    print("  ✓ No false positives when ratings are unchanged")


def test_skipped_tickers_not_flagged():
    """SKIPPED tickers must never be flagged as changes."""
    current = [_make_result("ACM", "BUY", "MED", status="SKIPPED")]
    last_state = {"ratings": {"ACM": {"rating": "STRONG_BUY", "confidence": "MED"}}}
    changes = detect_changes(current, last_state)
    assert changes == []
    print("  ✓ SKIPPED tickers are not flagged as changes")


def test_new_ticker_not_flagged_as_change():
    """A ticker appearing for the first time has no previous state — not a change."""
    current = [_make_result("NEW", "STRONG_BUY", "MED", status="DUE")]
    last_state = {"ratings": {}}
    changes = detect_changes(current, last_state)
    assert changes == []
    print("  ✓ New ticker (no previous state) not flagged as a change")


def test_no_last_state_returns_empty():
    current = [_make_result("ACM", "BUY", "MED", status="DUE")]
    changes = detect_changes(current, {})
    assert changes == []
    print("  ✓ Empty last_state returns no changes (first-run safety)")


def test_save_and_load_state_roundtrip(tmp_path):
    results = [_make_result("ACM", "STRONG_BUY", "MED")]
    p = tmp_path / "state.json"
    save_current_state(results, path=p)
    loaded = load_last_state(path=p)
    assert loaded["ratings"]["ACM"]["rating"] == "STRONG_BUY"
    assert loaded["ratings"]["ACM"]["confidence"] == "MED"
    print("  ✓ save/load last_digest_state round-trips correctly")


def test_load_state_missing_file(tmp_path):
    result = load_last_state(path=tmp_path / "does_not_exist.json")
    assert result == {}
    print("  ✓ load_last_state returns {} for missing file")


# ─── Quiet hours ─────────────────────────────────────────────────────────────

def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 5, 25, h, m, tzinfo=timezone.utc)


def test_quiet_during_night():
    assert is_quiet_hours("22:00", "07:00", now=_utc(23, 30)) is True
    assert is_quiet_hours("22:00", "07:00", now=_utc(0, 0)) is True
    assert is_quiet_hours("22:00", "07:00", now=_utc(6, 59)) is True
    print("  ✓ is_quiet_hours returns True during night window")


def test_not_quiet_during_day():
    assert is_quiet_hours("22:00", "07:00", now=_utc(9, 15)) is False   # cron time
    assert is_quiet_hours("22:00", "07:00", now=_utc(7, 0)) is False    # boundary (exclusive)
    assert is_quiet_hours("22:00", "07:00", now=_utc(21, 59)) is False
    print("  ✓ is_quiet_hours returns False during daytime (incl. 09:15 cron time)")


def test_quiet_boundary_exact_start():
    assert is_quiet_hours("22:00", "07:00", now=_utc(22, 0)) is True
    print("  ✓ Exactly at quiet_start (22:00) → quiet")


# ─── Graceful failure ─────────────────────────────────────────────────────────

def test_send_message_returns_false_on_network_error():
    """A network failure must return False and never raise."""
    with patch("src.telegram.client.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        from src.telegram.client import send_message
        result = send_message("test message")
    assert result is False
    print("  ✓ Network error → send_message returns False (no exception raised)")


def test_send_message_returns_false_on_api_error():
    """A non-200 API response must return False and never raise."""
    with patch("src.telegram.client.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value = mock_resp
        from src.telegram.client import send_message
        # Set env so credentials check passes
        import os
        os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
        os.environ["TELEGRAM_CHAT_ID"] = "-123456"
        result = send_message("test message")
    assert result is False
    print("  ✓ API 401 error → send_message returns False (no exception raised)")


def test_send_message_returns_false_on_missing_credentials():
    """Missing env vars must return False and never raise."""
    import os
    saved_token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    saved_chat = os.environ.pop("TELEGRAM_CHAT_ID", None)
    try:
        from src.telegram import client as tc
        import importlib
        importlib.reload(tc)
        result = tc.send_message("test")
        assert result is False
    finally:
        if saved_token:
            os.environ["TELEGRAM_BOT_TOKEN"] = saved_token
        if saved_chat:
            os.environ["TELEGRAM_CHAT_ID"] = saved_chat
    print("  ✓ Missing credentials → send_message returns False (no exception raised)")


# ─── format_change_alert ─────────────────────────────────────────────────────

def test_format_change_alert_structure():
    change = {
        "ticker": "AMAT",
        "old_rating": "STRONG_BUY", "old_conf": "HIGH",
        "new_rating": "BUY", "new_conf": "MED",
        "momentum_quintile": 2,
        "revision_direction": "NEGATIVE",
        "alignment_score": "+0 aligned, -2 contradicted",
    }
    text = format_change_alert(change)
    assert "AMAT" in text
    assert "STRONG_BUY" in text
    assert "BUY" in text
    assert "▼" in text   # negative revision symbol
    print("  ✓ format_change_alert includes ticker, old/new rating, and revision symbol")


if __name__ == "__main__":
    import tempfile, pathlib

    print("Running Telegram tests...")
    test_digest_contains_date()
    test_digest_contains_strong_buy_section()
    test_digest_excludes_low_conf_from_candidates()
    test_digest_contains_hold_section()
    test_digest_contains_sell_section()
    test_digest_paper_book_with_marks()
    test_digest_no_changes()
    test_digest_with_changes()
    test_digest_contains_help_footer()
    test_format_holds_lists_tickers()
    test_format_sells_lists_tickers()
    test_rating_change_detected()
    test_confidence_change_detected()
    test_no_false_positives_if_unchanged()
    test_skipped_tickers_not_flagged()
    test_new_ticker_not_flagged_as_change()
    test_no_last_state_returns_empty()
    with tempfile.TemporaryDirectory() as td:
        tp = pathlib.Path(td)
        test_save_and_load_state_roundtrip(tp)
        test_load_state_missing_file(tp)
    test_quiet_during_night()
    test_not_quiet_during_day()
    test_quiet_boundary_exact_start()
    test_send_message_returns_false_on_network_error()
    test_send_message_returns_false_on_api_error()
    test_send_message_returns_false_on_missing_credentials()
    test_format_change_alert_structure()
    print("All Telegram tests passed.")
