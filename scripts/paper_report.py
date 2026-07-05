#!/usr/bin/env python3
"""Paper trading report — open positions, unrealised P&L, SPY alpha, closed-trade stats.

Hard rules:
  no_real_orders       : True
  no_live_pnl_learning : True — this script reads outcomes for display only
  human_gated          : True

Usage:
  python3 scripts/paper_report.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._common import get_print
print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

from src.paper_trading import fetch_spy_price, load_positions, load_trades


def _fetch_prices(tickers: list[str]) -> dict[str, float | None]:
    """Fetch current prices for a list of tickers via yfinance."""
    prices: dict[str, float | None] = {}
    try:
        import yfinance as yf
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                for key in ("regularMarketPrice", "currentPrice", "previousClose"):
                    v = info.get(key)
                    if v is not None and float(v) > 0:
                        prices[ticker] = float(v)
                        break
                else:
                    prices[ticker] = None
            except Exception:
                prices[ticker] = None
    except ImportError:
        for t in tickers:
            prices[t] = None
    return prices


def main() -> None:
    today = str(date.today())
    print(f"Paper Trading Report  —  {today}")
    print("=" * 70)

    # ── Open positions ─────────────────────────────────────────────────────────
    positions = load_positions()
    trades = load_trades()

    spy_price = fetch_spy_price()
    if spy_price is None:
        print("WARNING: could not fetch SPY price; unrealised P&L vs SPY unavailable.")

    if not positions:
        print("\n  No open positions.")
    else:
        print(f"\n  Open positions ({len(positions)}):\n")
        tickers = list(positions.keys())
        current_prices = _fetch_prices(tickers)

        total_ret = 0.0
        total_alpha = 0.0
        n_priced = 0

        print(f"  {'Ticker':<8} {'Entry':<12} {'Entry $':>9} {'Now $':>9} "
              f"{'Return':>8} {'SPY α':>8} {'Target $':>9} {'Rating':<14}")
        print("  " + "-" * 86)

        for pos in sorted(positions.values(), key=lambda p: p["ticker"]):
            t = pos["ticker"]
            entry_price = pos["entry_price"]
            spy_entry = pos["spy_entry_price"]
            now = current_prices.get(t)

            if now is not None:
                ret_pct = now / entry_price - 1.0
                spy_now_str = f"${spy_price:.2f}" if spy_price else "—"
                spy_ret = (spy_price / spy_entry - 1.0) if spy_price else None
                alpha = (ret_pct - spy_ret) if spy_ret is not None else None
                ret_str = f"{ret_pct*100:+.2f}%"
                alpha_str = f"{alpha*100:+.2f}%" if alpha is not None else "—"
                now_str = f"${now:>8.2f}"
                total_ret += ret_pct
                if alpha is not None:
                    total_alpha += alpha
                n_priced += 1
            else:
                ret_str = "—"
                alpha_str = "—"
                now_str = "—"

            print(f"  {t:<8} {pos['entry_date']:<12} ${entry_price:>8.2f} {now_str:>9} "
                  f"{ret_str:>8} {alpha_str:>8} ${pos['price_target']:>8.0f} {pos['entry_rating']:<14}")

        if n_priced:
            avg_ret = total_ret / n_priced
            avg_alpha = total_alpha / n_priced
            print("  " + "-" * 86)
            print(f"  {'Average':<8} {'':<12} {'':<10} {'':<10} "
                  f"{avg_ret*100:>+7.2f}% {avg_alpha*100:>+7.2f}%")

    # ── Closed trades ──────────────────────────────────────────────────────────
    if not trades:
        print("\n  No closed trades yet.")
    else:
        print(f"\n  Closed trades ({len(trades)}):\n")
        print(f"  {'Ticker':<8} {'Entry':<12} {'Exit':<12} {'Return':>8} {'SPY α':>8} "
              f"{'Entry $':>9} {'Exit $':>9} {'Exit rating'}")
        print("  " + "-" * 84)

        total_ret = 0.0
        total_alpha = 0.0
        wins = 0

        for t in sorted(trades, key=lambda x: x.get("exit_date", "")):
            ret = t["return_pct"]
            alpha = t["alpha"]
            total_ret += ret
            total_alpha += alpha
            if ret > 0:
                wins += 1
            print(f"  {t['ticker']:<8} {t['entry_date']:<12} {t['exit_date']:<12} "
                  f"{ret*100:>+7.2f}% {alpha*100:>+7.2f}% "
                  f"${t['entry_price']:>8.2f} ${t['exit_price']:>8.2f} {t['exit_rating']}")

        n = len(trades)
        avg_ret = total_ret / n
        avg_alpha = total_alpha / n
        win_rate = wins / n * 100
        print("  " + "-" * 84)
        print(f"  {'Summary':<8} n={n:<11} {'':>12} {avg_ret*100:>+7.2f}% {avg_alpha*100:>+7.2f}%"
              f"  win_rate={win_rate:.0f}%")

    print()
    print("  Constraints: no_real_orders=True  no_live_pnl_learning=True")


if __name__ == "__main__":
    main()
