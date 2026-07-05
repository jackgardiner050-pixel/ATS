#!/usr/bin/env python3
"""Item 9 / Study A — weekly EPS-trend snapshot logger (LOGGING ONLY).

yfinance `eps_trend` exposes only current snapshots (a `current` value and a
`90daysAgo` value) — there is NO stored history, so the src/signals/revisions.py
signal (FY1 consensus now vs 90d ago, ±2% → POSITIVE/NEGATIVE/FLAT) cannot be
backtested historically. The only way to ever test it is to START accumulating
point-in-time snapshots now. This script appends one JSONL line per universe
ticker per run to data/eps_trend_history.jsonl.

It makes NO decisions, touches no src/, and never influences ratings/positions.
This is the single repo addition permitted by the item-9 brief. Run it weekly
(cron) — every logged week increases the eventual forward-test sample.

Classification mirrors src/signals/revisions.py (_compute_direction, ±2%); it is
replicated inline here so the logger stays standalone.

Usage:  python scripts/log_eps_trend.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.io_utils import append_jsonl   # durable fsync'd append (reuse)

print = get_print(__file__)  # noqa: A001

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "config" / "universe.yaml"
OUT = ROOT / "data" / "eps_trend_history.jsonl"


def _direction(cur, ago):
    """±2% classification, matching src/signals/revisions.py:_compute_direction."""
    if cur is None or ago is None:
        return "NO_COVERAGE"
    try:
        cur, ago = float(cur), float(ago)
    except (TypeError, ValueError):
        return "NO_COVERAGE"
    if abs(ago) < 0.001:
        return "NO_COVERAGE"
    if cur > ago * 1.02:
        return "POSITIVE"
    if cur < ago * 0.98:
        return "NEGATIVE"
    return "FLAT"


def _fy1_snapshot(ticker: str) -> dict | None:
    """Read the '+1y' (FY1) row of yfinance eps_trend. None on any failure."""
    try:
        import yfinance as yf
        et = yf.Ticker(ticker).eps_trend
        if et is None or getattr(et, "empty", True):
            return None
        row = et.loc["+1y"] if "+1y" in et.index else None
        if row is None:
            return None
        cur = row.get("current")
        ago = row.get("90daysAgo")
        return {"fy1_current": None if cur is None else float(cur),
                "fy1_90d_ago": None if ago is None else float(ago)}
    except Exception:
        return None


def main() -> int:
    cfg = yaml.safe_load(UNIVERSE.read_text()) or {}
    tickers = sorted({t.upper() for t in cfg.get("universe", [])})
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    print(f"Logging eps_trend snapshots for {len(tickers)} tickers → {OUT}")

    n_ok = n_nc = 0
    for t in tickers:
        snap = _fy1_snapshot(t)
        if snap is None:
            rec = {"date": today, "ticker": t, "fy1_current": None,
                   "fy1_90d_ago": None, "direction": "NO_COVERAGE", "fetched_at_utc": now}
            n_nc += 1
        else:
            direction = _direction(snap["fy1_current"], snap["fy1_90d_ago"])
            rec = {"date": today, "ticker": t, **snap,
                   "direction": direction, "fetched_at_utc": now}
            n_ok += 1 if direction != "NO_COVERAGE" else 0
            n_nc += 1 if direction == "NO_COVERAGE" else 0
        append_jsonl(OUT, rec)

    print(f"Logged {len(tickers)} rows ({n_ok} with a direction, {n_nc} NO_COVERAGE).")
    print("Forward-observation only — accrues one snapshot/week; see the Study A memo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
