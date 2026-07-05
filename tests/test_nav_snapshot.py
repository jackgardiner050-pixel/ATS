"""Tests for scripts/nav_snapshot.py — idempotency + units persistence (no network)."""
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.nav_snapshot as ns


def _rec(ticker, cohort, entry_date, entry_price):
    return {
        "ticker": ticker, "cohort": cohort, "direction": "LONG",
        "entry_date": entry_date, "entry_price": entry_price,
        "entry_rating": "STRONG_BUY", "entry_confidence": "MED",
        "price_target": entry_price * 1.3, "spy_entry_price": 500.0,
    }


def _setup(tmp_path, monkeypatch, prices):
    monkeypatch.setattr(ns, "_last_adj_close", lambda t: prices.get(t))
    monkeypatch.setattr(ns, "_adj_close_on", lambda t, d: prices.get("SPY_INCEPTION", 500.0))
    pos = tmp_path / "paper_positions.yaml"
    hist = tmp_path / "nav_history.jsonl"
    pos.write_text(yaml.dump({"positions": [
        _rec("ACM", "cohort_1", "2026-07-06", 50.0),
        _rec("EMR", "legacy_pre_fix", "2026-05-25", 100.0),
    ]}, sort_keys=False))
    return pos, hist


def _history(hist):
    return [json.loads(l) for l in hist.read_text().splitlines() if l.strip()]


def test_snapshot_same_day_is_idempotent(tmp_path, monkeypatch):
    pos, hist = _setup(tmp_path, monkeypatch, {"SPY": 500.0, "ACM": 55.0, "EMR": 110.0})
    cfg = ns.load_portfolio_config()
    today = date(2026, 7, 6)

    assert ns.run(today, hist, pos, cfg, dry_run=False) == 0
    assert ns.run(today, hist, pos, cfg, dry_run=False) == 0   # same day again

    rows = _history(hist)
    keys = [(r["date"], r["cohort"]) for r in rows]
    assert len(keys) == len(set(keys)) == 2      # one per cohort, not duplicated
    assert set(keys) == {("2026-07-06", "cohort_1"), ("2026-07-06", "legacy_pre_fix")}
    print("  ✓ same-day re-run replaces each cohort's line, no duplicates")


def test_snapshot_lines_are_per_cohort_never_combined(tmp_path, monkeypatch):
    pos, hist = _setup(tmp_path, monkeypatch, {"SPY": 500.0, "ACM": 55.0, "EMR": 110.0})
    ns.run(date(2026, 7, 6), hist, pos, ns.load_portfolio_config(), dry_run=False)
    rows = _history(hist)
    cohorts = sorted(r["cohort"] for r in rows)
    assert cohorts == ["cohort_1", "legacy_pre_fix"]   # two distinct lines
    for r in rows:
        assert "cohort" in r and "nav" in r and "benchmark_nav" in r
    print("  ✓ each cohort gets its own NAV line, never a combined one")


def test_units_persisted_for_cohort_1_only(tmp_path, monkeypatch):
    pos, hist = _setup(tmp_path, monkeypatch, {"SPY": 500.0, "ACM": 55.0, "EMR": 110.0})
    ns.run(date(2026, 7, 6), hist, pos, ns.load_portfolio_config(), dry_run=False)
    recs = {r["ticker"]: r for r in yaml.safe_load(pos.read_text())["positions"]}
    assert "units" in recs["ACM"]              # cohort_1 → persisted
    assert recs["ACM"]["units"] == (100_000 / 20) / 50.0
    assert "units" not in recs["EMR"]          # legacy → approximation, not persisted
    print("  ✓ units persisted for cohort_1 only; legacy left as approximation")


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    pos, hist = _setup(tmp_path, monkeypatch, {"SPY": 500.0, "ACM": 55.0, "EMR": 110.0})
    assert ns.run(date(2026, 7, 6), hist, pos, ns.load_portfolio_config(), dry_run=True) == 0
    assert not hist.exists()                   # no history written
    recs = {r["ticker"]: r for r in yaml.safe_load(pos.read_text())["positions"]}
    assert "units" not in recs["ACM"]          # no persistence in dry-run
    print("  ✓ --dry-run computes but writes nothing")


def test_cohort_1_snapshot_not_blocked_by_legacy_failure(tmp_path, monkeypatch):
    """If legacy pricing/build blows up, cohort_1 must still be snapshotted."""
    pos, hist = _setup(tmp_path, monkeypatch, {"SPY": 500.0, "ACM": 55.0, "EMR": 110.0})
    real_build = ns.build_snapshot

    def _selective_build(**kw):
        if kw["cohort"] == "legacy_pre_fix":
            raise RuntimeError("legacy exploded")
        return real_build(**kw)

    monkeypatch.setattr(ns, "build_snapshot", _selective_build)
    assert ns.run(date(2026, 7, 6), hist, pos, ns.load_portfolio_config(), dry_run=False) == 0
    cohorts = [r["cohort"] for r in _history(hist)]
    assert cohorts == ["cohort_1"]             # cohort_1 present, legacy skipped
    print("  ✓ a legacy failure does not block Cohort-1's snapshot")


if __name__ == "__main__":
    print("Run via pytest (uses tmp_path + monkeypatch fixtures).")
