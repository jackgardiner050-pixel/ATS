"""Tests for heartbeat staleness detection in generate_dashboard.py."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_dashboard import _heartbeat_state, _most_recent_expected_run_utc

UTC = timezone.utc


# ─── _most_recent_expected_run_utc ───────────────────────────────────────────

class TestMostRecentExpectedRun:
    def test_weekday_before_21_returns_previous_weekday_21(self):
        # Friday 20:00 UTC — today's 21:00 run hasn't fired yet, so previous run = Thursday
        now = datetime(2026, 5, 29, 20, 0, 0, tzinfo=UTC)
        result = _most_recent_expected_run_utc(now)
        assert result == datetime(2026, 5, 28, 21, 0, 0, tzinfo=UTC)

    def test_weekday_after_21_returns_today_21(self):
        now = datetime(2026, 5, 29, 22, 0, 0, tzinfo=UTC)  # Friday 22:00 UTC
        result = _most_recent_expected_run_utc(now)
        assert result == datetime(2026, 5, 29, 21, 0, 0, tzinfo=UTC)

    def test_saturday_returns_friday_21(self):
        now = datetime(2026, 5, 30, 10, 0, 0, tzinfo=UTC)  # Saturday
        result = _most_recent_expected_run_utc(now)
        assert result == datetime(2026, 5, 29, 21, 0, 0, tzinfo=UTC)

    def test_sunday_returns_friday_21(self):
        now = datetime(2026, 5, 31, 10, 0, 0, tzinfo=UTC)  # Sunday
        result = _most_recent_expected_run_utc(now)
        assert result == datetime(2026, 5, 29, 21, 0, 0, tzinfo=UTC)

    def test_monday_before_21_returns_friday_21(self):
        now = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)  # Monday 10:00 UTC
        result = _most_recent_expected_run_utc(now)
        assert result == datetime(2026, 5, 29, 21, 0, 0, tzinfo=UTC)


# ─── _heartbeat_state ────────────────────────────────────────────────────────

class TestHeartbeatState:
    def test_missing_file_returns_never_run(self, tmp_path):
        state = _heartbeat_state(tmp_path / "heartbeat.json")
        assert state["status"] == "never_run"
        assert state["last_run_utc"] is None
        assert state["commit"] == ""

    def test_fresh_heartbeat_returns_ok(self, tmp_path):
        now = datetime(2026, 5, 29, 22, 30, 0, tzinfo=UTC)
        hb_ts = "2026-05-29T21:05:00Z"
        hb = tmp_path / "heartbeat.json"
        hb.write_text(json.dumps({"last_run_utc": hb_ts, "commit": "abc1234", "status": "ok"}))
        state = _heartbeat_state(hb, now=now)
        assert state["status"] == "ok"
        assert state["commit"] == "abc1234"
        assert state["last_run_utc"] == datetime(2026, 5, 29, 21, 5, 0, tzinfo=UTC)

    def test_stale_heartbeat_returns_stale(self, tmp_path):
        # now is Tuesday morning; last run was Monday; expected was Monday 21:00
        # heartbeat says it ran Monday at 15:00 (before the expected 21:00 run)
        now = datetime(2026, 6, 2, 10, 0, 0, tzinfo=UTC)   # Tuesday 10:00
        hb_ts = "2026-06-01T15:00:00Z"                     # Monday 15:00 — before Mon 21:00
        hb = tmp_path / "heartbeat.json"
        hb.write_text(json.dumps({"last_run_utc": hb_ts, "commit": "old1234", "status": "ok"}))
        state = _heartbeat_state(hb, now=now)
        assert state["status"] == "stale"

    def test_missed_run_shows_stale(self, tmp_path):
        # Weekend gap: Friday run is fine, but Monday checks that Friday 21:00 is expected
        # and heartbeat shows Thursday — stale
        now = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)   # Monday 10:00 UTC
        hb_ts = "2026-05-28T21:03:00Z"                      # Thursday — before Friday 21:00
        hb = tmp_path / "heartbeat.json"
        hb.write_text(json.dumps({"last_run_utc": hb_ts, "commit": "old", "status": "ok"}))
        state = _heartbeat_state(hb, now=now)
        assert state["status"] == "stale"

    def test_corrupt_file_returns_unreadable(self, tmp_path):
        hb = tmp_path / "heartbeat.json"
        hb.write_text("not valid json {{{{")
        state = _heartbeat_state(hb)
        assert state["status"] == "unreadable"

    def test_missing_ts_field_returns_unreadable(self, tmp_path):
        hb = tmp_path / "heartbeat.json"
        hb.write_text(json.dumps({"commit": "abc", "status": "ok"}))
        state = _heartbeat_state(hb)
        assert state["status"] == "unreadable"

    def test_expected_utc_always_set(self, tmp_path):
        state = _heartbeat_state(tmp_path / "missing.json")
        assert state["expected_utc"] is not None
        assert state["expected_utc"].tzinfo is not None
