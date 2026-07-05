"""Tests for the cohort tag: migration script + report-build gate."""
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.migrate_add_cohort_tag import migrate, LEGACY_COHORT


def _write_positions(path: Path, records: list[dict]) -> None:
    path.write_text(yaml.dump({"positions": records}, sort_keys=False))


def _legacy_record(ticker: str, entry_date: str = "2026-05-25") -> dict:
    """A pre-fix position record as it exists on disk today — no cohort field."""
    return {
        "ticker": ticker,
        "direction": "LONG",
        "entry_date": entry_date,
        "entry_price": 100.0,
        "entry_rating": "STRONG_BUY",
        "entry_confidence": "MED",
        "price_target": 130.0,
        "spy_entry_price": 500.0,
    }


TODAY = date(2026, 7, 5)
TWELVE = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]


def test_migration_tags_exactly_the_expected_records(tmp_path):
    p = tmp_path / "paper_positions.yaml"
    _write_positions(p, [_legacy_record(t) for t in TWELVE])

    rc = migrate(p, TODAY)
    assert rc == 0

    loaded = yaml.safe_load(p.read_text())["positions"]
    assert len(loaded) == 12
    assert all(r["cohort"] == LEGACY_COHORT for r in loaded)
    assert {r["ticker"] for r in loaded} == set(TWELVE)
    print("  ✓ migration tags exactly the 12 legacy records with legacy_pre_fix")


def test_migration_fails_loudly_on_rerun(tmp_path):
    p = tmp_path / "paper_positions.yaml"
    _write_positions(p, [_legacy_record(t) for t in TWELVE])

    assert migrate(p, TODAY) == 0            # first run tags
    before = p.read_text()
    assert migrate(p, TODAY) != 0            # second run errors (already tagged)
    assert p.read_text() == before           # and writes nothing
    print("  ✓ re-running the migration errors and leaves the file unchanged")


def test_migration_skips_future_dated_records(tmp_path):
    p = tmp_path / "paper_positions.yaml"
    _write_positions(p, [
        _legacy_record("ACM", "2026-05-25"),        # <= today → tagged
        _legacy_record("FUT", "2099-01-01"),        # > today → left untouched
    ])
    assert migrate(p, TODAY) == 0
    recs = {r["ticker"]: r for r in yaml.safe_load(p.read_text())["positions"]}
    assert recs["ACM"]["cohort"] == LEGACY_COHORT
    assert "cohort" not in recs["FUT"]
    print("  ✓ migration only tags entry_date <= today")


def test_migration_missing_file_errors(tmp_path):
    assert migrate(tmp_path / "nope.yaml", TODAY) != 0
    print("  ✓ migration on a missing file returns non-zero")


def test_report_build_aborts_on_untagged_record(tmp_path, monkeypatch):
    """The report build (paper_report.main) must exit non-zero on an untagged record."""
    import src.paper_trading as pt
    pos_path = tmp_path / "paper_positions.yaml"
    _write_positions(pos_path, [_legacy_record("ACM")])   # deliberately untagged
    monkeypatch.setattr(pt, "POSITIONS_PATH", pos_path)
    monkeypatch.setattr(pt, "TRADES_PATH", tmp_path / "paper_trades.jsonl")

    # load_positions/load_trades read POSITIONS_PATH/TRADES_PATH as module globals
    # at call time, so the monkeypatch above is enough — no reload needed. The gate
    # runs before any network call, so this stays offline.
    import scripts.paper_report as report

    import pytest
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 1
    print("  ✓ paper_report aborts (exit 1) when a record lacks a valid cohort")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        test_migration_tags_exactly_the_expected_records(tp)
        test_migration_fails_loudly_on_rerun(tp)
    print("Migration tests passed (run via pytest for the report-gate monkeypatch test).")
