#!/usr/bin/env python3
"""Swing Bot EOD mark-to-market — runs daily at 22:30 UTC after US close.

Responsibilities:
  1. Fetch closing prices for all open positions (yfinance, after close)
  2. Check exit conditions against closing prices
  3. Close any positions that triggered today
  4. Update kill switch state with latest cumulative P&L
  5. Send Telegram alert if any positions closed or if kill switch nearing threshold
  6. Log mark-to-market to data/eod_marks.jsonl

Uses yfinance (free, no rate-limit concern) rather than Finnhub at EOD.
The 15-min delay is moot after market close — closing prices are final.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import yaml

from src.kill_switch import (
    check_kill_switch, format_kill_alert, format_soft_alert, is_disabled, update_pnl,
)
from src.paper_executor import (
    append_trade, close_position, load_positions, load_trades, save_positions,
)
from src.rules.exit import check_exit
from src.telegram_client import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("eod_mark")

_CONFIG_PATH = _ROOT / "config" / "settings.yaml"
_MARKS_LOG = _ROOT / "data" / "eod_marks.jsonl"
_DATA_DIR = _ROOT / "data"


def _closing_price(ticker: str) -> float:
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.debug("Price fetch failed for %s: %s", ticker, exc)
    return 0.0


def _spy_close() -> float:
    return _closing_price("SPY")


def _log_mark(record: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_MARKS_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def main() -> None:
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}

    bot_cfg = cfg.get("bot", {})
    portfolio_cfg = cfg.get("portfolio", {})
    exit_cfg = cfg.get("exit_rules", {})

    alert_mode = bool(bot_cfg.get("alert_mode_only", True))
    disable_date = str(bot_cfg.get("disable_date", "2026-11-25"))
    profit_target = float(exit_cfg.get("profit_target_pct", 10.0))
    stop_loss = float(exit_cfg.get("stop_loss_pct", -5.0))
    max_hold_days = int(exit_cfg.get("max_hold_trading_days", 10))

    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    log.info("=== EOD mark-to-market %s (alert_mode=%s) ===", now, alert_mode)

    if is_disabled():
        log.info("Kill switch disabled — skipping EOD mark")
        sys.exit(0)

    positions = load_positions()
    trades = load_trades()
    spy_price = _spy_close()
    log.info("Open positions: %d | SPY close: $%.2f", len(positions), spy_price)

    if not positions:
        # Still update P&L state even with no open positions
        update_pnl(trades)
        log.info("No open positions — P&L state updated")
        return

    closed: list[dict] = []
    marks: list[dict] = []

    for ticker, pos in list(positions.items()):
        cur_price = _closing_price(ticker)
        if cur_price <= 0:
            log.warning("Could not fetch closing price for %s — skipping", ticker)
            continue

        entry = float(pos["entry_price"])
        ret_pct = (cur_price - entry) / entry * 100

        exit_sig = check_exit(
            position=pos,
            current_price=cur_price,
            today=today,
            negative_catalyst=False,
            profit_target_pct=profit_target,
            stop_loss_pct=-abs(stop_loss),
            max_hold_trading_days=max_hold_days,
        )

        mark = {
            "date": today,
            "ticker": ticker,
            "entry_price": entry,
            "close_price": cur_price,
            "return_pct": round(ret_pct, 4),
            "should_exit": exit_sig.should_exit,
            "exit_reason": exit_sig.reason if exit_sig.should_exit else None,
        }
        marks.append(mark)
        _log_mark(mark)

        log.info("Mark %s: entry $%.2f → close $%.2f (%+.1f%%) %s",
                 ticker, entry, cur_price, ret_pct,
                 f"EXIT:{exit_sig.reason}" if exit_sig.should_exit else "hold")

        if exit_sig.should_exit:
            trade = close_position(pos, today, cur_price, exit_sig.reason, spy_price)
            if not alert_mode:
                del positions[ticker]
                append_trade(trade)
                trades.append(trade)
            else:
                log.info("[ALERT] Would close %s: %s (%+.1f%%)", ticker, exit_sig.reason, ret_pct)
            closed.append(trade)

            # Send exit alert
            pnl = trade.get("pnl_gbp", 0.0)
            alpha = trade.get("alpha", 0.0) * 100
            icon = "🟢" if pnl >= 0 else "🔴"
            prefix = "[ALERT MODE] " if alert_mode else ""
            send_message(
                f"{prefix}{icon} SWING EXIT (EOD): {ticker}\n"
                f"Reason: {exit_sig.reason}\n"
                f"Return: {ret_pct:+.1f}% | P&L: £{pnl:+.2f}\n"
                f"Alpha vs SPY: {alpha:+.1f}%"
            )

    if not alert_mode:
        save_positions(positions)

    # Update cumulative P&L state
    all_trades = load_trades() if not alert_mode else trades
    update_pnl(all_trades)

    # Kill switch check after EOD closes (two-tier: soft alert at -10%, hard kill at -20%)
    if not alert_mode:
        hard_killed, reason, soft_fired = check_kill_switch(all_trades, disable_date=disable_date)
        cum_gbp = sum(t.get("pnl_gbp", 0) for t in all_trades)
        cum_pct = cum_gbp / 500.0 * 100
        if hard_killed:
            send_message(format_kill_alert(reason, cum_pct, cum_gbp))
        elif soft_fired:
            send_message(format_soft_alert(cum_pct, cum_gbp))

    # EOD summary
    unrealised_pnl = sum(
        float(pos.get("notional_gbp", 50)) * (m["return_pct"] / 100)
        for pos, m in zip(positions.values(), [mk for mk in marks if not mk["should_exit"]])
        if m["return_pct"] is not None
    )
    log.info("EOD done: %d closed, %d still open, unrealised £%.2f", len(closed), len(positions), unrealised_pnl)


if __name__ == "__main__":
    main()
