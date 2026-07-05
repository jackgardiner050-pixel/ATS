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

from scripts._common import get_print
print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

from src.paper_trading import _paper_cost_bps, tr_fields
from src.paper_trading import (
    fetch_spy_price,
    load_positions,
    save_positions,
    append_trade,
    process_screener_results,
)

_SCREEN_ROOT = Path(__file__).parent.parent / "runs" / "_screen"


def _adj_close_on(ticker: str, day: str):
    """First yfinance auto_adjust (total-return) close on/after `day`. None on failure."""
    try:
        import yfinance as yf
        from datetime import timedelta
        d = date.fromisoformat(str(day)[:10])
        h = yf.Ticker(ticker).history(start=d.isoformat(),
                                      end=(d + timedelta(days=7)).isoformat(), auto_adjust=True)
        return float(h["Close"].iloc[0]) if h is not None and not h.empty else None
    except Exception:
        return None


def _fetch_aligned_adjusted(ticker: str, entry_date: str, exit_date: str):
    """(entry_adj, exit_adj, spy_entry_adj, spy_exit_adj) — stock and SPY from the
    same source at the same two dates. None on any failure (→ trade stays spot_only)."""
    return (_adj_close_on(ticker, entry_date), _adj_close_on(ticker, exit_date),
            _adj_close_on("SPY", entry_date), _adj_close_on("SPY", exit_date))


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

    # ── Attribution snapshot (PART E, additive) ────────────────────────────────
    # entry_signals is attached HERE (orchestration layer) rather than inside the
    # lock-protected open_position/close_position — it is a pure additive field and
    # does not alter any entry/exit decision input or threshold.
    signals_by_ticker = {
        r["ticker"]: {
            "momentum_quintile": r.get("momentum_quintile"),
            "revision_direction": r.get("revision_direction"),
            "confidence_before": r.get("confidence_before"),
            "confidence_after": r.get("confidence"),
            "dcf_upside": r.get("expected_return"),
            "cohort_outlier": r.get("cohort_outlier", False),
        }
        for r in results if r.get("ticker")
    }
    for t in opened:
        if t in new_positions:
            new_positions[t]["entry_signals"] = signals_by_ticker.get(t)
    # carry the closed position's entry_signals through onto its trade record
    for trade in closed_trades:
        prev = current_positions.get(trade["ticker"])
        if prev and prev.get("entry_signals") is not None:
            trade["entry_signals"] = prev["entry_signals"]

    # ── Honest total-return capture (item 10) ─────────────────────────────────
    # Capture stock AND SPY dividend-adjusted closes from the SAME source (yfinance
    # auto_adjust) at the SAME two dates (entry, exit) — timestamp-aligned by date —
    # and fill in the trade's TR fields via the shared tr_fields() math.
    for trade in closed_trades:
        adj = _fetch_aligned_adjusted(trade["ticker"], trade["entry_date"], trade["exit_date"])
        if adj and all(a is not None for a in adj):
            trade.update(tr_fields(*adj, cost_bps=trade.get("cost_bps") or _paper_cost_bps()))

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
