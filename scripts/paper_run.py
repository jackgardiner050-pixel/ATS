#!/usr/bin/env python3
"""Paper trading run — apply entry/exit rules from latest screener output.

Hard rules:
  no_real_orders       : True — never interacts with a broker
  no_live_pnl_learning : True — P&L logged for analysis only, never fed back
  human_gated          : True — must be invoked explicitly

Reads:  runs/_screen/<latest>/summary.json
        data/paper_positions.yaml
Writes: data/paper_positions.yaml  (updated open positions)
        data/paper_trades.jsonl    (appended closed trades, immutable)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_trading import (
    fetch_spy_price,
    load_positions,
    save_positions,
    append_trade,
    process_screener_results,
)

_SCREEN_ROOT = Path(__file__).parent.parent / "runs" / "_screen"


def _latest_summary() -> tuple[Path, dict]:
    """Return (path, data) for the most recent screen summary."""
    dirs = sorted(_SCREEN_ROOT.iterdir()) if _SCREEN_ROOT.exists() else []
    dirs = [d for d in dirs if d.is_dir()]
    if not dirs:
        print("No screen runs found under runs/_screen/. Run run_universe.py first.")
        sys.exit(1)
    latest = dirs[-1]
    summary_path = latest / "summary.json"
    if not summary_path.exists():
        print(f"No summary.json in {latest}")
        sys.exit(1)
    with open(summary_path) as f:
        return summary_path, json.load(f)


def main() -> None:
    today = str(date.today())

    summary_path, summary = _latest_summary()
    results = summary.get("results", [])
    ts = summary.get("timestamp", "?")
    print(f"Paper run  —  {today}")
    print(f"  Screener input: {summary_path.parent.name}  ({len(results)} tickers)")

    spy_price = fetch_spy_price()
    if spy_price is None:
        print("  ERROR: could not fetch SPY price. Aborting.")
        sys.exit(1)
    print(f"  SPY price: ${spy_price:.2f}")

    current_positions = load_positions()
    print(f"  Open positions before run: {len(current_positions)}")

    new_positions, closed_trades, opened, closed = process_screener_results(
        results, current_positions, spy_price, today
    )

    # Persist
    save_positions(new_positions)
    for trade in closed_trades:
        append_trade(trade)

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    if opened:
        print(f"  Opened ({len(opened)}):")
        for t in sorted(opened):
            pos = new_positions[t]
            print(f"    + {t:<6}  entry=${pos['entry_price']:>8.2f}  pt=${pos['price_target']:>8.0f}"
                  f"  [{pos['entry_rating']} / {pos['entry_confidence']}]")
    else:
        print("  No new positions opened.")

    if closed:
        print(f"  Closed ({len(closed)}):")
        for trade in closed_trades:
            sign = "+" if trade["return_pct"] >= 0 else ""
            print(f"    - {trade['ticker']:<6}  ret={sign}{trade['return_pct']*100:.2f}%"
                  f"  alpha={sign}{trade['alpha']*100:.2f}%  [{trade['exit_rating']}]")
    else:
        print("  No positions closed.")

    print()
    print(f"  Open positions after run: {len(new_positions)}")
    if new_positions:
        print()
        print(f"  {'Ticker':<8} {'Entry date':<12} {'Entry $':>9} {'Target $':>9} {'Rating':<14} {'Conf'}")
        print("  " + "-" * 65)
        for pos in sorted(new_positions.values(), key=lambda p: p["ticker"]):
            print(f"  {pos['ticker']:<8} {pos['entry_date']:<12} ${pos['entry_price']:>8.2f}"
                  f" ${pos['price_target']:>8.0f} {pos['entry_rating']:<14} {pos['entry_confidence']}")


if __name__ == "__main__":
    main()
