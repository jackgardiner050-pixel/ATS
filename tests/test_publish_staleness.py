"""Phaethon data staleness detection and STALE banner rendering tests.

Tests ensure:
  - Source date comes from scorecard_public.json (as_of field or mtime)
  - Staleness is correctly computed (trading days since source_as_of)
  - data_status ∈ {FRESH, STALE} is rendered in arm JSON
  - stale_days counter is accurate
  - evaluated_as_of is ALWAYS today (evaluation time), not source date
  - stale_days_effective accounts for per-arm expected lag
  - Fresh sources produce byte-identical output (additive keys only)
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.phaethon.publish import (
    _source_as_of, _staleness, assemble_arm, _load_state
)
from src.phaethon.scorecard import render_arm

ROOT = Path(__file__).parent.parent
CONSTITUTION = {"MAX_SINGLE_POSITION": 0.10}
SCREENER = {"min_market_cap_usd": 500_000_000, "max_market_cap_usd": 200_000_000_000}


def _book(cash, holds):
    """Helper to construct a minimal book dict."""
    return {"cash": cash, "holdings": {t: {"shares": s, "last_price": lp, "cost_basis": cb}
                                       for t, (s, lp, cb) in holds.items()}}


def test_source_as_of_reads_from_scorecard_json(tmp_path):
    """_source_as_of should read as_of from scorecard_public.json if present."""
    scorecard_date = "2026-08-25"
    sc = {"as_of": scorecard_date, "n_positions": 1}
    bk = _book(100.0, {"X": (1.0, 50.0, 40.0)})

    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))
    (tmp_path / "book.json").write_text(json.dumps(bk))

    result = _source_as_of(tmp_path)
    assert result == scorecard_date
    print(f"  ✓ _source_as_of extracted date from scorecard: {result}")


def test_source_as_of_falls_back_to_mtime(tmp_path):
    """_source_as_of should fall back to file mtime when as_of is absent."""
    sc = {"n_positions": 1}  # no as_of field
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    # Result should be a valid ISO date string
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of fell back to mtime: {result}")


def test_source_as_of_validates_iso_datetime_with_trailing_z(tmp_path):
    """_source_as_of should extract leading date from ISO datetime like '2026-09-01T22:45:01Z'."""
    sc = {"as_of": "2026-09-01T22:45:01Z", "n_positions": 1}
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    assert result == "2026-09-01", f"Expected 2026-09-01, got {result}"
    # Verify it's a valid ISO date
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of extracted date from ISO datetime: {result}")


def test_source_as_of_validates_iso_datetime_without_z(tmp_path):
    """_source_as_of should extract leading date from ISO datetime like '2026-09-01T22:30:00'."""
    sc = {"as_of": "2026-09-01T22:30:00", "n_positions": 1}
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    assert result == "2026-09-01"
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of extracted date from ISO datetime (no Z): {result}")


def test_source_as_of_falls_back_on_bad_date_format(tmp_path):
    """_source_as_of should fall back to mtime for unparseable formats like '31/08/2026'."""
    sc = {"as_of": "31/08/2026", "n_positions": 1}
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    # Result should be a valid ISO date string (mtime fallback)
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of fell back to mtime for bad format: {result}")


def test_source_as_of_falls_back_on_unknown_string(tmp_path):
    """_source_as_of should fall back to mtime for 'unknown' or other non-date strings."""
    sc = {"as_of": "unknown", "n_positions": 1}
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of fell back to mtime for 'unknown': {result}")


def test_source_as_of_falls_back_on_empty_string(tmp_path):
    """_source_as_of should fall back to mtime for empty as_of string."""
    sc = {"as_of": "", "n_positions": 1}
    (tmp_path / "scorecard_public.json").write_text(json.dumps(sc))

    result = _source_as_of(tmp_path)
    d = date.fromisoformat(result)
    assert isinstance(d, date)
    print(f"  ✓ _source_as_of fell back to mtime for empty string: {result}")


def test_staleness_fresh_when_source_is_today():
    """Data is FRESH when source_as_of is today or the most recent trading day."""
    today = date.today()
    # Find the most recent trading day on/before today
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    status, days, effective = _staleness(last_trading_day.isoformat(), today=today)
    assert status == "FRESH" and days == 0
    print(f"  ✓ source as of last trading day: FRESH, stale_days=0")


def test_staleness_fresh_when_source_is_yesterday_trading_day():
    """Data is FRESH when yesterday trading day source is used with Arm B lag (1 day)."""
    today = date.today()
    # Find the most recent trading day on/before today
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    # Source 1 trading day back with lag=0 should be STALE
    status_no_lag, days_no_lag, effective_no_lag = _staleness(
        (last_trading_day - timedelta(days=1)).isoformat(), today=today, expected_lag_days=0
    )
    assert status_no_lag == "STALE", "1 trading day back without lag should be STALE"

    # Same source with lag=1 should be FRESH
    status_with_lag, days_with_lag, effective_with_lag = _staleness(
        (last_trading_day - timedelta(days=1)).isoformat(), today=today, expected_lag_days=1
    )
    assert status_with_lag == "FRESH", "1 trading day back with lag=1 should be FRESH"
    print(f"  ✓ lag=0: STALE, lag=1: FRESH (for 1 trading day old source)")


def test_staleness_stale_when_1_plus_trading_days_elapsed():
    """Data is STALE when 1 or more trading days have elapsed since source."""
    # Use a fixed reference date for deterministic test
    # Source was 2026-08-28 (Friday), today is 2026-09-02 (Wednesday)
    # Trading days strictly after 2026-08-28: 2026-08-29 (Sat-skip), 2026-08-30 (Sun-skip),
    # 2026-08-31 (Mon), 2026-09-01 (Tue), 2026-09-02 (Wed) = 3 trading days
    source_date = "2026-08-28"  # Friday
    today = date(2026, 9, 2)    # Wednesday
    status, days, effective = _staleness(source_date, today=today)
    assert status == "STALE" and days >= 1
    print(f"  ✓ source Fri to Wed (3 trading days): STALE, stale_days={days}")


def test_staleness_counts_weekdays_only():
    """_staleness should count only weekdays (Mon-Fri)."""
    # Use actual calendar dates that are what we think they are:
    # Friday 2026-08-28, Monday 2026-08-31 -> last trading day is Mon 2026-08-31
    # Days strictly after Fri 2026-08-28: Sat 2026-08-29 (skip), Sun 2026-08-30 (skip),
    # Mon 2026-08-31 (count) = 1 trading day
    source_date = "2026-08-28"  # Friday
    today = date(2026, 8, 31)   # Monday
    status, days, effective = _staleness(source_date, today=today)
    assert days == 1
    # Days strictly after Fri 2026-08-28 up to last trading day (Mon 2026-08-31) = 1 (Mon only)
    # So source_date Friday -> today Monday = 1 trading day elapsed (Monday itself)
    print(f"  ✓ Fri to Mon counts {days} trading day(s)")


def test_staleness_10_calendar_days_back(tmp_path):
    """A fixture scorecard 10 calendar days back should be STALE with ~7 trading days."""
    # 10 calendar days back from today includes ~7 weekdays
    today = date.today()
    source_date = today - timedelta(days=10)

    status, days, effective = _staleness(source_date.isoformat(), today=today)
    assert status == "STALE"
    # 10 calendar days typically spans 7-8 trading days (2 weekends = 4 weekend days max)
    assert days >= 6 and days <= 8
    print(f"  ✓ source 10 calendar days back: STALE, stale_days={days}")


def test_fresh_source_renders_fresh(tmp_path):
    """Fresh scorecard renders with data_status=FRESH and stale_days=0, evaluated_as_of=today."""
    today = date.today()
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    sc = {
        "as_of": last_trading_day.isoformat(),
        "n_positions": 1,
        "active_return_pct": 2.5,
        "vs_qqq_pp": 1.0,
        "trend": "IMPROVING",
        "n_marks": 5,
        "drawdown_pct": 0.0,
        "halted": False,
    }
    bk = _book(100.0, {"ACM": (1.0, 50.0, 40.0)})

    out = assemble_arm(sc, bk, "A", SCREENER, CONSTITUTION, check_mcap=False,
                       as_of=sc["as_of"], data_status="FRESH", stale_days=0, stale_days_effective=0)

    assert out["data_status"] == "FRESH"
    assert out["stale_days"] == 0
    assert out["stale_days_effective"] == 0
    assert out["as_of"] == sc["as_of"]
    assert "evaluated_as_of" in out
    # evaluated_as_of is ALWAYS today (when governance runs), not the source date
    assert out["governance"]["evaluated_as_of"] == today.isoformat()
    assert out["evaluated_as_of"] == today.isoformat()
    print(f"  ✓ fresh render: data_status=FRESH, as_of={out['as_of']}, evaluated_as_of={out['evaluated_as_of']}")


def test_stale_source_renders_stale_with_banner_fields(tmp_path):
    """Scorecard 10 days old renders with data_status=STALE, stale_days>=6, old as_of."""
    today = date.today()
    source_date = today - timedelta(days=10)

    sc = {
        "as_of": source_date.isoformat(),
        "n_positions": 1,
        "active_return_pct": 2.5,
        "vs_qqq_pp": 1.0,
        "trend": "IMPROVING",
        "n_marks": 5,
        "drawdown_pct": 0.0,
        "halted": False,
    }
    bk = _book(100.0, {"ACM": (1.0, 50.0, 40.0)})

    status, stale_days, stale_days_effective = _staleness(sc["as_of"], today=today)
    out = assemble_arm(sc, bk, "A", SCREENER, CONSTITUTION, check_mcap=False,
                       as_of=sc["as_of"], data_status=status, stale_days=stale_days,
                       stale_days_effective=stale_days_effective)

    assert out["data_status"] == "STALE"
    assert out["stale_days"] >= 6
    assert out["as_of"] == source_date.isoformat()
    # evaluated_as_of is ALWAYS today, not the source date
    assert out["governance"]["evaluated_as_of"] == today.isoformat()
    assert out["evaluated_as_of"] == today.isoformat()
    print(f"  ✓ stale render (10 days old): as_of={out['as_of']}, evaluated_as_of={out['evaluated_as_of']} (they differ)")


def test_fresh_output_numeric_fields_unchanged():
    """For a fresh source, numeric/holdings fields are unchanged from non-staleness render."""
    today = date.today()
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    sc = {
        "as_of": last_trading_day.isoformat(),
        "n_positions": 1,
        "active_return_pct": 2.5,
        "vs_qqq_pp": 1.0,
        "trend": "IMPROVING",
        "n_marks": 5,
        "drawdown_pct": 0.0,
        "halted": False,
    }
    bk = _book(100.0, {"ACM": (1.0, 50.0, 40.0)})

    # Render with FRESH staleness
    out_fresh = assemble_arm(sc, bk, "A", SCREENER, CONSTITUTION, check_mcap=False,
                             as_of=sc["as_of"], data_status="FRESH", stale_days=0, stale_days_effective=0)

    # Render with STALE staleness (but same book)
    out_stale = assemble_arm(sc, bk, "A", SCREENER, CONSTITUTION, check_mcap=False,
                             as_of=sc["as_of"], data_status="STALE", stale_days=1, stale_days_effective=1)

    # Key numeric fields should be identical
    key_fields = ["holdings", "cash_pct", "active_return_pct", "vs_qqq_pp",
                  "n_positions", "n_marks", "drawdown_pct"]
    for field in key_fields:
        assert out_fresh[field] == out_stale[field], f"Field {field} differs"

    # Only the staleness-specific fields should differ
    assert out_fresh["data_status"] == "FRESH"
    assert out_stale["data_status"] == "STALE"
    assert out_fresh["stale_days"] == 0
    assert out_stale["stale_days"] == 1
    # evaluated_as_of should be the same (today) in both
    assert out_fresh["evaluated_as_of"] == out_stale["evaluated_as_of"] == today.isoformat()

    print(f"  ✓ numeric/holdings fields identical regardless of staleness")


def test_governance_evaluated_as_of_always_today():
    """evaluated_as_of should always be today (evaluation time), not source date."""
    sc = {"n_positions": 1, "active_return_pct": 1.0}
    bk = _book(100.0, {"X": (1.0, 50.0, 40.0)})

    as_of_date = "2026-08-25"  # Some old date
    out = assemble_arm(sc, bk, "A", SCREENER, CONSTITUTION, check_mcap=False,
                       as_of=as_of_date)

    today = date.today().isoformat()
    assert "evaluated_as_of" in out["governance"]
    assert out["governance"]["evaluated_as_of"] == today, f"Expected {today}, got {out['governance']['evaluated_as_of']}"
    assert out["evaluated_as_of"] == today, f"Expected {today}, got {out['evaluated_as_of']}"
    # as_of should still be the source date
    assert out["as_of"] == as_of_date
    print(f"  ✓ evaluated_as_of is today ({today}), as_of is source ({as_of_date})")


def test_arm_b_lag_1_makes_yesterday_trading_day_fresh():
    """Arm B with 1-day lag should show FRESH for yesterday trading day source."""
    today = date.today()
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    # Find previous trading day
    prev_trading_day = last_trading_day - timedelta(days=1)
    while prev_trading_day.weekday() >= 5:
        prev_trading_day -= timedelta(days=1)

    sc = {
        "as_of": prev_trading_day.isoformat(),
        "n_positions": 1,
        "active_return_pct": 2.5,
        "vs_qqq_pp": 1.0,
        "trend": "IMPROVING",
        "n_marks": 5,
        "drawdown_pct": 0.0,
        "halted": False,
    }
    bk = _book(100.0, {"X": (1.0, 50.0, 40.0)})

    # With lag=1 (Arm B), a 1-trading-day-old source should be FRESH
    status, stale_days, effective = _staleness(sc["as_of"], today=today, expected_lag_days=1)
    assert status == "FRESH", f"Arm B lag=1 with 1-day-old source should be FRESH, got {status}"
    assert stale_days == 1, f"Raw stale_days should be 1, got {stale_days}"
    assert effective == 0, f"Effective should be 0 after lag adjustment, got {effective}"
    print(f"  ✓ Arm B (lag=1): 1-day-old source is FRESH (stale_days={stale_days}, effective={effective})")


def test_arm_b_lag_1_makes_3_day_old_source_stale():
    """Arm B with 1-day lag should show STALE for 3-day-old source, with effective days visible."""
    today = date.today()
    source_date = today - timedelta(days=7)  # Rough 3-trading-day offset

    status, stale_days, effective = _staleness(source_date.isoformat(), today=today, expected_lag_days=1)
    assert status == "STALE", f"3-day-old source should be STALE even with lag=1"
    # Raw stale_days should be approximately 3 trading days
    # Effective should be raw - 1
    assert effective == max(0, stale_days - 1)
    print(f"  ✓ Arm B (lag=1): 3-day-old source is STALE (stale_days={stale_days}, effective={effective})")


def test_arm_a_lag_0_makes_1_day_old_source_stale():
    """Arm A with 0-day lag should show STALE for 1-day-old source."""
    today = date.today()
    last_trading_day = today
    while last_trading_day.weekday() >= 5:
        last_trading_day -= timedelta(days=1)

    prev_trading_day = last_trading_day - timedelta(days=1)
    while prev_trading_day.weekday() >= 5:
        prev_trading_day -= timedelta(days=1)

    # With lag=0 (Arm A), a 1-trading-day-old source should be STALE
    status, stale_days, effective = _staleness(prev_trading_day.isoformat(), today=today, expected_lag_days=0)
    assert status == "STALE", f"Arm A lag=0 with 1-day-old source should be STALE, got {status}"
    assert stale_days == 1
    assert effective == 1
    print(f"  ✓ Arm A (lag=0): 1-day-old source is STALE (stale_days={stale_days}, effective={effective})")


if __name__ == "__main__":
    import tempfile
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            varnames = fn.__code__.co_varnames
            if "tmp_path" in varnames:
                with tempfile.TemporaryDirectory() as tmpdir:
                    fn(Path(tmpdir))
            else:
                fn()
    print("All staleness tests passed.")
