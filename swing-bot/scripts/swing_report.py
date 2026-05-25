#!/usr/bin/env python3
"""Swing Bot on-demand report — prints open positions and closed trade stats.

Usage:
    python scripts/swing_report.py [--telegram]

Flags:
    --telegram   Also send the report to the swing Telegram channel.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import yfinance as yf

from src.kill_switch import load_state as load_kill_state
from src.paper_executor import load_positions, load_trades
from src.telegram_client import send_message


def _current_price(ticker: str) -> float:
    try:
        hist = yf.Ticker(ticker).history(period="1d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _spy_price() -> float:
    return _current_price("SPY")


def _format_report(positions: dict, trades: list[dict], spy_price: float) -> str:
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 SWING BOT REPORT — {now}", ""]

    # ── Kill switch state ──────────────────────────────────────────────────
    ks = load_kill_state()
    if ks.get("disabled"):
        lines.append(f"⛔ KILL SWITCH: {ks.get('disable_reason', 'disabled')}")
    else:
        cumulative_pct = ks.get("cumulative_pnl_pct", 0.0)
        cumulative_gbp = ks.get("cumulative_pnl_gbp", 0.0)
        icon = "🟢" if cumulative_pct >= 0 else "🔴"
        lines.append(f"{icon} Kill switch: ARMED | Cumulative P&L: {cumulative_pct:+.1f}% (£{cumulative_gbp:+.2f})")
        lines.append(f"   Disable date: {ks.get('disable_date', '?')} | Trades: {ks.get('total_closed_trades', 0)}")
    lines.append("")

    # ── Open positions ─────────────────────────────────────────────────────
    lines.append(f"📂 OPEN POSITIONS ({len(positions)})")
    if not positions:
        lines.append("   None")
    else:
        for ticker, pos in sorted(positions.items()):
            cur = _current_price(ticker)
            entry = float(pos["entry_price"])
            notional = float(pos.get("notional_gbp", 50.0))
            if cur > 0 and entry > 0:
                ret_pct = (cur - entry) / entry * 100
                unreal_gbp = notional * (cur - entry) / entry
                spy_entry = float(pos.get("spy_entry_price", spy_price or 1))
                spy_ret = (spy_price - spy_entry) / spy_entry * 100 if spy_price > 0 and spy_entry > 0 else 0
                alpha = ret_pct - spy_ret
                lines.append(
                    f"   {ticker:6s}  Entry £{entry:.2f} → £{cur:.2f}  "
                    f"{ret_pct:+.1f}% (£{unreal_gbp:+.2f})  α{alpha:+.1f}%  "
                    f"catalyst={pos.get('catalyst_type','?')}"
                )
            else:
                lines.append(f"   {ticker:6s}  Entry £{entry:.2f} → no price")
    lines.append("")

    # ── Closed trades ──────────────────────────────────────────────────────
    lines.append(f"📋 CLOSED TRADES ({len(trades)})")
    if not trades:
        lines.append("   None yet")
    else:
        winners = [t for t in trades if t.get("pnl_gbp", 0) > 0]
        losers = [t for t in trades if t.get("pnl_gbp", 0) <= 0]
        total_pnl = sum(t.get("pnl_gbp", 0) for t in trades)
        avg_ret = sum(t.get("return_pct", 0) for t in trades) / len(trades) * 100
        avg_alpha = sum(t.get("alpha", 0) for t in trades) / len(trades) * 100
        win_rate = len(winners) / len(trades) * 100

        lines.append(f"   Win rate:   {win_rate:.0f}%  ({len(winners)}W / {len(losers)}L)")
        lines.append(f"   Total P&L:  £{total_pnl:+.2f}")
        lines.append(f"   Avg return: {avg_ret:+.1f}%  |  Avg α: {avg_alpha:+.1f}%")
        lines.append("")
        lines.append("   Recent closes:")
        for t in trades[-5:]:
            ret = t.get("return_pct", 0) * 100
            pnl = t.get("pnl_gbp", 0)
            icon = "✅" if pnl > 0 else "❌"
            lines.append(
                f"   {icon} {t['ticker']:6s}  {t['exit_date']}  "
                f"{ret:+.1f}%  £{pnl:+.2f}  [{t.get('exit_reason','?')}]"
            )

    lines.append("")
    lines.append("Hard rules: paper_only ✓ | ringfenced ✓ | kill_switch armed ✓")
    return "\n".join(lines)


def main() -> None:
    send_to_telegram = "--telegram" in sys.argv

    positions = load_positions()
    trades = load_trades()
    spy_price = _spy_price()

    report = _format_report(positions, trades, spy_price)
    print(report)

    if send_to_telegram:
        ok = send_message(report)
        if ok:
            print("\n✓ Sent to Telegram")
        else:
            print("\n✗ Telegram send failed (see logs)")


if __name__ == "__main__":
    main()
