#!/usr/bin/env python3
"""Back up the data/ directory to a dated tarball, keeping the last 30.

Writes ``backups/data_<YYYYMMDD>.tar.gz`` containing the whole ``data/`` tree,
then prunes older tarballs so at most 30 remain. Re-running on the same day
overwrites that day's archive (idempotent).

Usage:
    python scripts/backup_data.py
    python scripts/backup_data.py --keep 60
"""
from __future__ import annotations

import argparse
import sys
import tarfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / "data"
BACKUPS_DIR = _ROOT / "backups"

_PREFIX = "data_"
_SUFFIX = ".tar.gz"


def create_backup(data_dir: Path, backups_dir: Path, date_str: str) -> Path:
    """Tar `data_dir` into `backups_dir/data_<date_str>.tar.gz` and return the path."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    out = backups_dir / f"{_PREFIX}{date_str}{_SUFFIX}"
    # Write to a tmp then replace so a reader never sees a half-written archive.
    tmp = out.with_name(out.name + ".tmp")
    with tarfile.open(tmp, "w:gz") as tar:
        tar.add(data_dir, arcname=data_dir.name)
    tmp.replace(out)
    return out


def prune_backups(backups_dir: Path, keep: int = 30) -> list[Path]:
    """Delete all but the newest `keep` backup tarballs. Return the pruned paths.

    "Newest" is by sorted filename — the ``data_<YYYYMMDD>`` naming sorts
    chronologically, so lexical order is date order.
    """
    if not backups_dir.exists():
        return []
    archives = sorted(
        (p for p in backups_dir.iterdir()
         if p.name.startswith(_PREFIX) and p.name.endswith(_SUFFIX)),
        key=lambda p: p.name,
    )
    to_remove = archives[:-keep] if keep > 0 else archives
    for p in to_remove:
        p.unlink()
    return to_remove


def main() -> int:
    ap = argparse.ArgumentParser(description="Back up data/ to a dated tarball (keep last N).")
    ap.add_argument("--keep", type=int, default=30, help="how many backups to retain (default 30)")
    args = ap.parse_args()

    if not DATA_DIR.exists():
        print(f"ERROR: data directory not found: {DATA_DIR}")
        return 1

    date_str = date.today().strftime("%Y%m%d")
    out = create_backup(DATA_DIR, BACKUPS_DIR, date_str)
    size_kb = out.stat().st_size / 1024
    print(f"Backup written: {out}  ({size_kb:.1f} KiB)")

    pruned = prune_backups(BACKUPS_DIR, keep=args.keep)
    if pruned:
        print(f"Pruned {len(pruned)} old backup(s) beyond keep={args.keep}: "
              + ", ".join(p.name for p in pruned))
    remaining = len([p for p in BACKUPS_DIR.iterdir()
                     if p.name.startswith(_PREFIX) and p.name.endswith(_SUFFIX)])
    print(f"{remaining} backup(s) retained in {BACKUPS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
