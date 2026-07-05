#!/usr/bin/env python3
"""One-off migration: tag the pre-fix legacy book with cohort: legacy_pre_fix.

Every open position with entry_date on or before today (the 12 positions opened
in the 2026-05-25 pre-fix run) is tagged ``cohort: legacy_pre_fix``. New
positions opened under the locked ruleset are tagged ``cohort_1`` at creation
(see paper_trading.open_position), so this migration only backfills the legacy
records.

Fail-loud, NOT blindly idempotent: if any record this migration would touch
already carries a ``cohort`` field, it exits non-zero without writing — that
means it already ran, or the data is not what we expect. Re-running on
already-tagged data is therefore an error, not a silent no-op.

Usage:
    python scripts/migrate_add_cohort_tag.py
    python scripts/migrate_add_cohort_tag.py --positions data/paper_positions.yaml
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.io_utils import atomic_write_text
from src.paper_trading import POSITIONS_PATH

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

LEGACY_COHORT = "legacy_pre_fix"


def migrate(positions_path: Path, today: date) -> int:
    if not positions_path.exists():
        print(f"ERROR: positions file not found: {positions_path}")
        return 1

    with open(positions_path) as f:
        raw = yaml.safe_load(f) or {}
    records = raw.get("positions") or []

    # Records this migration is responsible for: entry_date on or before today.
    to_tag: list[dict] = []
    conflicts: list[str] = []
    for r in records:
        entry_raw = r.get("entry_date")
        if not entry_raw:
            continue
        try:
            entry = date.fromisoformat(str(entry_raw)[:10])
        except ValueError:
            print(f"ERROR: unparseable entry_date {entry_raw!r} on {r.get('ticker', '?')}")
            return 1
        if entry > today:
            continue  # future-dated (not part of the legacy backfill)
        if "cohort" in r:
            conflicts.append(f"{r.get('ticker', '?')} (entry {entry_raw}, cohort={r['cohort']!r})")
        else:
            to_tag.append(r)

    if conflicts:
        print("ERROR: refusing to run — these records already have a cohort field:")
        for c in conflicts:
            print(f"  - {c}")
        print("This migration is not idempotent to re-run. Nothing written.")
        return 1

    if not to_tag:
        print("No untagged legacy records found (entry_date <= today). Nothing to do.")
        return 1

    for r in to_tag:
        r["cohort"] = LEGACY_COHORT

    text = yaml.dump({"positions": records}, default_flow_style=False, sort_keys=False)
    atomic_write_text(positions_path, text)

    print(f"Tagged {len(to_tag)} record(s) with cohort={LEGACY_COHORT!r} in {positions_path}:")
    for r in to_tag:
        print(f"  - {r.get('ticker', '?'):<6} entry_date={r.get('entry_date')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill cohort: legacy_pre_fix on the pre-fix book.")
    ap.add_argument("--positions", type=Path, default=POSITIONS_PATH,
                    help="path to paper_positions.yaml (default: live data file)")
    args = ap.parse_args()
    return migrate(args.positions, date.today())


if __name__ == "__main__":
    sys.exit(main())
