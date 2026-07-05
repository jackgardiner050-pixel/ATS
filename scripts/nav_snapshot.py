#!/usr/bin/env python3
"""Daily paper-book NAV snapshot — cron-able, run post-close.

Appends one NAV line PER COHORT to data/nav_history.jsonl (legacy_pre_fix and
cohort_1 are snapshotted separately and never combined, per the observation
protocol). Prices use yfinance history with auto_adjust=True (total-return
closes) for both stocks and SPY; benchmark_nav = nav_start · SPY_today/SPY_at_inception,
inception = earliest entry_date within that cohort (computed independently).

Robustness:
  * a snapshot failure never crashes and never writes a partial line — the whole
    history file is rebuilt in memory (idempotent upsert of today's line) and
    written atomically via src.io_utils.atomic_write_text
  * running twice the same day REPLACES that date's line for each cohort, not
    duplicates it
  * cohort_1 is processed first and independently; any legacy_pre_fix problem
    cannot block or delay Cohort-1's snapshot

Sizing / cost parameters come from config/portfolio.yaml (intentionally NOT in the
protocol lock's ruleset). Units are persisted into cohort_1 position records on
first snapshot; legacy_pre_fix units are treated as an APPROXIMATION (the legacy
book was opened at a different real sizing) and are NOT persisted.

Read-only w.r.t. entry/exit decisions. No broker libraries.

Usage:
    python scripts/nav_snapshot.py
    python scripts/nav_snapshot.py --today 2026-07-06 --history /tmp/nav.jsonl --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.io_utils import atomic_write_text
from src.paper_trading import POSITIONS_PATH, load_positions, load_trades, save_positions
from src.portfolio.nav_ledger import build_snapshot, compute_units, upsert_snapshots

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_CONFIG = _ROOT / "config" / "portfolio.yaml"
HISTORY_PATH = _ROOT / "data" / "nav_history.jsonl"

# Cohorts get processed in this order — cohort_1 first so legacy never blocks it.
_COHORT_ORDER = ["cohort_1", "legacy_pre_fix"]


# ─── config / price helpers ──────────────────────────────────────────────────

def load_portfolio_config(path: Path = PORTFOLIO_CONFIG) -> dict:
    cfg = yaml.safe_load(path.read_text()) or {}
    return {
        "nav_start": float(cfg.get("paper_nav_start", 100_000)),
        "n_target_positions": int(cfg.get("n_target_positions", 20)),
        "cost_bps": float(cfg.get("paper_cost_bps", 20)),
    }


def _last_adj_close(ticker: str) -> float | None:
    """Latest total-return (auto_adjust) close, or None on any failure."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _adj_close_on(ticker: str, day: date) -> float | None:
    """First total-return close on/after `day`, or None on failure."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(
            start=day.isoformat(), end=(day + timedelta(days=7)).isoformat(),
            auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[0])
    except Exception:
        return None


def _entry_date(rec: dict) -> date | None:
    raw = rec.get("entry_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


# ─── snapshot for one cohort ─────────────────────────────────────────────────

def _snapshot_cohort(cohort: str, opens: list[dict], closes: list[dict],
                     today: date, cfg: dict) -> tuple[dict | None, list[dict]]:
    """Return (snapshot_line_or_None, cohort_1_records_needing_unit_persist)."""
    dated = [d for d in (_entry_date(r) for r in opens + closes) if d is not None]
    if not dated:
        print(f"  {cohort}: no dated positions/trades — skipping")
        return None, []
    inception = min(dated)

    spy_today = _last_adj_close("SPY")
    spy_inception = _adj_close_on("SPY", inception)
    if spy_today is None or spy_inception is None:
        print(f"  {cohort}: WARNING SPY price unavailable (today={spy_today}, "
              f"inception={spy_inception}); benchmark_nav will be null")
        spy_today = spy_today or 0.0
        spy_inception = spy_inception or 0.0

    prices = {r["ticker"]: c for r in opens
              if (c := _last_adj_close(r["ticker"])) is not None}

    # units: persist for cohort_1; legacy units are approximations (not persisted)
    to_persist: list[dict] = []
    for r in opens:
        if "units" not in r or r.get("units") is None:
            units = compute_units(cfg["nav_start"], cfg["n_target_positions"],
                                  float(r["entry_price"]))
            if cohort == "cohort_1":
                r["units"] = units
                to_persist.append(r)
            # legacy: leave units off the record; build_snapshot derives it in-memory

    if cohort == "legacy_pre_fix":
        print(f"  {cohort}: units are an APPROXIMATION (legacy sizing differs) — not persisted")

    snap = build_snapshot(
        date=today.isoformat(), cohort=cohort,
        open_positions=opens, closed_trades=closes, prices=prices,
        spy_tr_index=spy_today, spy_inception_price=spy_inception,
        nav_start=cfg["nav_start"], n_target_positions=cfg["n_target_positions"],
        cost_bps=cfg["cost_bps"],
    )
    print(f"  {cohort}: nav={snap['nav']} benchmark_nav={snap['benchmark_nav']} "
          f"n_positions={snap['n_positions']}")
    return snap, to_persist


def _read_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  WARNING skipping malformed history line")
    return out


def _write_history(path: Path, records: list[dict]) -> None:
    text = "".join(json.dumps(r) + "\n" for r in records)
    atomic_write_text(path, text)


# ─── main ────────────────────────────────────────────────────────────────────

def run(today: date, history_path: Path, positions_path: Path,
        cfg: dict, dry_run: bool) -> int:
    positions = load_positions(path=positions_path)
    trades = load_trades()

    opens_by_cohort: dict[str, list[dict]] = defaultdict(list)
    for rec in positions.values():
        opens_by_cohort[rec.get("cohort")].append(rec)
    closes_by_cohort: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        closes_by_cohort[t.get("cohort")].append(t)

    cohorts = [c for c in _COHORT_ORDER if c in opens_by_cohort or c in closes_by_cohort]
    if not cohorts:
        print("No cohorts with open positions or closed trades — nothing to snapshot.")
        return 0

    new_snaps: list[dict] = []
    persist: list[dict] = []
    for cohort in cohorts:
        try:
            snap, to_persist = _snapshot_cohort(
                cohort, opens_by_cohort.get(cohort, []), closes_by_cohort.get(cohort, []),
                today, cfg)
            if snap is not None:
                new_snaps.append(snap)
                persist.extend(to_persist)
        except Exception as e:                     # never let one cohort break another
            print(f"  {cohort}: ERROR building snapshot — skipped: {e}")

    if not new_snaps:
        print("No snapshots produced.")
        return 1

    merged = upsert_snapshots(_read_history(history_path), new_snaps)
    if dry_run:
        print(f"[dry-run] would write {len(merged)} history rows to {history_path} "
              f"and persist units for {len(persist)} cohort_1 record(s)")
        return 0

    _write_history(history_path, merged)
    print(f"Wrote {len(new_snaps)} snapshot line(s) → {history_path} "
          f"({len(merged)} rows total; same-day lines replaced, not duplicated)")

    if persist:
        save_positions(positions, path=positions_path)   # persist cohort_1 units
        print(f"Persisted units into {len(persist)} cohort_1 position record(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily paper-book NAV snapshot (per cohort).")
    ap.add_argument("--today", type=str, default=None, help="override date (YYYY-MM-DD)")
    ap.add_argument("--history", type=Path, default=HISTORY_PATH)
    ap.add_argument("--positions", type=Path, default=POSITIONS_PATH)
    ap.add_argument("--portfolio-config", type=Path, default=PORTFOLIO_CONFIG)
    ap.add_argument("--dry-run", action="store_true", help="compute but write nothing")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    cfg = load_portfolio_config(args.portfolio_config)
    print(f"NAV snapshot for {today} (nav_start={cfg['nav_start']:.0f}, "
          f"n_target={cfg['n_target_positions']}, cost_bps={cfg['cost_bps']:.0f})")

    try:
        return run(today, args.history, args.positions, cfg, args.dry_run)
    except Exception as e:                          # snapshot failure never crashes
        print(f"ERROR: snapshot aborted without writing a partial line: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
