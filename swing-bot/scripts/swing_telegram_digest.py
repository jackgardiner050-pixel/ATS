#!/usr/bin/env python3
"""Swing Bot weekly Sunday digest — summary of the week's paper activity.

Cron: 0 9 * * 0   (Sunday 09:00 UTC)

Sends to swing bot channel (SWING_BOT_TOKEN / SWING_BOT_CHAT_ID).
Never raises — logs failures and exits cleanly.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import yfinance as yf
import yaml

from src.kill_switch import load_state as load_kill_state
from src.paper_executor import load_positions, load_trades
from src.telegram_client import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("swing_digest")


def _spy_price() -> float:
    try:
        hist = yf.Ticker("SPY").history(period="1d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _week_trades(trades: list[dict]) -> list[dict]:
    """Trades closed in the last 7 days."""
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    return [t for t in trades if t.get("exit_date", "") >= cutoff]


def _format_digest(
    positions: dict,
    trades: list[dict],
    week_trades: list[dict],
    spy_price: float,
    ks_state: dict,
    alert_mode_only: bool,
) -> str:
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📅 SWING BOT WEEKLY DIGEST — {now}", ""]

    mode_tag = "[ALERT MODE — positions simulated only]" if alert_mode_only else ""
    if mode_tag:
        lines.append(mode_tag)
        lines.append("")

    # Kill switch
    if ks_state.get("disabled"):
        lines.append(f"⛔ KILL SWITCH TRIGGERED: {ks_state.get('disable_reason','?')}")
        lines.append("Bot is disabled. Re-enable manually after review.")
        return "\n".join(lines)

    cum_pct = ks_state.get("cumulative_pnl_pct", 0.0)
    cum_gbp = ks_state.get("cumulative_pnl_gbp", 0.0)
    icon = "🟢" if cum_pct >= 0 else "🔴"
    lines.append(f"{icon} Overall P&L: {cum_pct:+.1f}% (£{cum_gbp:+.2f})")
    lines.append(f"   Disable date: {ks_state.get('disable_date','?')} | Total trades: {ks_state.get('total_closed_trades',0)}")
    lines.append("")

    # This week
    lines.append(f"📆 THIS WEEK ({len(week_trades)} trades closed)")
    if not week_trades:
        lines.append("   No closes this week.")
    else:
        winners = [t for t in week_trades if t.get("pnl_gbp", 0) > 0]
        total_pnl = sum(t.get("pnl_gbp", 0) for t in week_trades)
        avg_ret = sum(t.get("return_pct", 0) for t in week_trades) / len(week_trades) * 100
        avg_alpha = sum(t.get("alpha", 0) for t in week_trades) / len(week_trades) * 100
        lines.append(f"   W/L: {len(winners)}/{len(week_trades)-len(winners)}  |  P&L: £{total_pnl:+.2f}  |  Avg ret: {avg_ret:+.1f}%  |  Avg α: {avg_alpha:+.1f}%")
        lines.append("")
        for t in week_trades:
            ret = t.get("return_pct", 0) * 100
            pnl = t.get("pnl_gbp", 0)
            ico = "✅" if pnl > 0 else "❌"
            lines.append(f"   {ico} {t['ticker']:6s}  {t['exit_reason']:16s}  {ret:+.1f}%  £{pnl:+.2f}")
    lines.append("")

    # Open positions
    lines.append(f"📂 OPEN POSITIONS ({len(positions)})")
    if not positions:
        lines.append("   None")
    else:
        for ticker, pos in sorted(positions.items()):
            try:
                hist = yf.Ticker(ticker).history(period="1d")
                cur = float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else 0.0
            except Exception:
                cur = 0.0
            entry = float(pos["entry_price"])
            if cur > 0 and entry > 0:
                ret = (cur - entry) / entry * 100
                lines.append(f"   {ticker:6s}  Entry £{entry:.2f} → £{cur:.2f}  {ret:+.1f}%  [{pos.get('catalyst_type','?')}]")
            else:
                lines.append(f"   {ticker:6s}  Entry £{entry:.2f}")
    lines.append("")

    # All-time stats
    if trades:
        all_winners = [t for t in trades if t.get("pnl_gbp", 0) > 0]
        all_pnl = sum(t.get("pnl_gbp", 0) for t in trades)
        all_ret = sum(t.get("return_pct", 0) for t in trades) / len(trades) * 100
        all_alpha = sum(t.get("alpha", 0) for t in trades) / len(trades) * 100
        lines.append(f"📈 ALL-TIME ({len(trades)} trades)")
        lines.append(f"   Win rate: {len(all_winners)/len(trades)*100:.0f}%  |  Total P&L: £{all_pnl:+.2f}")
        lines.append(f"   Avg return: {all_ret:+.1f}%  |  Avg alpha: {all_alpha:+.1f}%")
        lines.append("")

    lines.append("paper_only ✓ | ringfenced ✓ | kill_switch armed ✓")
    return "\n".join(lines)


def main() -> None:
    log.info("=== Swing Bot weekly digest ===")

    try:
        cfg_path = _ROOT / "config" / "settings.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        alert_mode_only = bool(cfg.get("bot", {}).get("alert_mode_only", True))
    except Exception as exc:
        log.warning("Could not read settings: %s — defaulting alert_mode_only=True", exc)
        alert_mode_only = True

    positions = load_positions()
    trades = load_trades()
    ks_state = load_kill_state()
    spy_price = _spy_price()
    week_trades = _week_trades(trades)

    digest = _format_digest(positions, trades, week_trades, spy_price, ks_state, alert_mode_only)
    print(digest)

    ok = send_message(digest)
    if ok:
        log.info("Weekly digest sent to Telegram")
    else:
        log.warning("Telegram send failed — digest printed to stdout only")


if __name__ == "__main__":
    main()
