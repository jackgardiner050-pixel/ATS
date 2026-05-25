#!/usr/bin/env python3
"""Swing Bot catalyst poll — 15-min cron entry point (weekdays 14:00-20:00 UTC).

Pipeline per run:
  1. Kill switch check — hard abort if triggered
  2. 6-month time box check — hard abort if expired
  3. alert_mode_only guard — log signals but skip position I/O if true
  4. Poll all catalyst sources for watchlist tickers
  5. Apply entry/exit rules, open/close paper positions
  6. Send Telegram alerts for any new entries/exits
  7. Save kill switch state

Hard rules enforced:
  - place_real_order() is never called (exists only to raise RuntimeError)
  - No trade data fed back to any model (no_live_pnl_learning)
  - Ringfenced: only reads/writes swing-bot/data/
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Allow running from repo root or scripts/ directory
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT.parent.parent))  # agent/ on path for nothing
sys.path.insert(0, str(_ROOT))               # swing-bot/ on path

import yaml

from src.catalysts.edgar_8k import get_recent_8ks
from src.catalysts.earnings_monitor import get_earnings_beats
from src.catalysts.fda_calendar import get_fda_approvals
from src.catalysts.volume_anomaly import get_volume_spikes
from src.kill_switch import check_kill_switch, is_disabled, format_kill_alert
from src.paper_executor import (
    load_positions, save_positions, load_trades, append_trade,
    open_position, close_position,
)
from src.rules.entry import check_entry, build_entry_signal, fetch_market_data
from src.rules.exit import check_exit
from src.rules.filters import passes_all_filters, is_negative_8k
from src.telegram_client import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("run_catalyst_poll")

_CONFIG_PATH = _ROOT / "config" / "settings.yaml"
_WATCHLIST_PATH = _ROOT / "config" / "watchlist.yaml"
_SEEN_PATH = _ROOT / "data" / "seen_accessions.json"
_DATA_DIR = _ROOT / "data"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _load_watchlist() -> list[str]:
    with open(_WATCHLIST_PATH) as f:
        wl = yaml.safe_load(f) or {}
    tickers: list[str] = []
    for tier in ("tier1", "tier2"):
        tickers.extend(wl.get(tier, []))
    return list(dict.fromkeys(tickers))  # dedup, preserve order


def _load_seen_accessions() -> set[str]:
    if not _SEEN_PATH.exists():
        return set()
    with open(_SEEN_PATH) as f:
        return set(json.load(f))


def _save_seen_accessions(seen: set[str]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Keep last 2000 to prevent unbounded growth
    recent = list(seen)[-2000:]
    with open(_SEEN_PATH, "w") as f:
        json.dump(recent, f)


def _spy_price() -> float:
    """Fetch current SPY price for alpha tracking."""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period="1d")
        if spy is not None and not spy.empty:
            return float(spy["Close"].iloc[-1])
    except Exception as exc:
        log.warning("SPY price fetch failed: %s", exc)
    return 0.0


def _process_entries(
    catalysts: list[dict],
    positions: dict,
    cfg: dict,
    alert_mode_only: bool,
    today: str,
    spy_price: float,
) -> list[dict]:
    """Evaluate entry conditions and open positions for passing catalysts."""
    portfolio_cfg = cfg.get("portfolio", {})
    entry_cfg = cfg.get("entry_rules", {})
    exit_cfg = cfg.get("exit_rules", {})
    phase_b_enabled = cfg.get("llm", {}).get("enabled", False)

    position_size_gbp = float(portfolio_cfg.get("position_size_gbp", 50.0))
    max_positions = int(portfolio_cfg.get("max_positions", 10))
    min_price_change_pct = float(entry_cfg.get("min_price_change_pct", 3.0))
    min_liquidity_usd = float(entry_cfg.get("min_liquidity_usd", 6_350_000))
    five_day_trend_floor = float(entry_cfg.get("five_day_trend_floor_pct", -1.0))
    profit_target_pct = float(exit_cfg.get("profit_target_pct", 10.0))
    stop_loss_pct = float(exit_cfg.get("stop_loss_pct", -5.0))
    max_hold_days = int(exit_cfg.get("max_hold_trading_days", 10))

    new_positions = []
    for catalyst in catalysts:
        ticker = catalyst.get("ticker", "")
        if not ticker or ticker in positions:
            continue  # skip if already holding this ticker

        if not passes_all_filters(catalyst, phase_b_enabled):
            log.debug("Catalyst filtered out for %s: %s", ticker, catalyst.get("catalyst_type"))
            continue

        market_data = fetch_market_data(ticker)
        if not market_data:
            log.debug("No market data for %s — skipping", ticker)
            continue

        result = check_entry(
            ticker=ticker,
            catalyst=catalyst,
            market_data=market_data,
            n_open_positions=len(positions),
            position_size_gbp=position_size_gbp,
            min_price_change_pct=min_price_change_pct,
            min_liquidity_usd=min_liquidity_usd,
            five_day_trend_floor_pct=five_day_trend_floor,
            max_positions=max_positions,
        )

        if not result.passed:
            log.info("Entry check FAILED for %s: %s", ticker, result.reason)
            continue

        log.info("Entry check PASSED for %s: %s", ticker, catalyst.get("catalyst_type"))

        signal = build_entry_signal(
            ticker=ticker,
            catalyst=catalyst,
            current_price=market_data["current_price"],
            position_size_gbp=position_size_gbp,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=-abs(stop_loss_pct),
        )

        # Build time_exit_date (10 trading days ≈ 14 calendar days, use calendar for simplicity)
        from datetime import timedelta
        entry_date_obj = date.fromisoformat(today)
        time_exit_date = (entry_date_obj + timedelta(days=14)).isoformat()

        pos = open_position(
            ticker=ticker,
            entry_date=today,
            entry_price=signal.entry_price,
            shares=signal.shares,
            notional_gbp=signal.notional_gbp,
            catalyst=catalyst,
            spy_entry_price=spy_price,
            stop_loss_price=signal.stop_loss_price,
            profit_target_price=signal.profit_target_price,
            time_exit_date=time_exit_date,
        )

        if alert_mode_only:
            log.info("[ALERT MODE] Would open: %s @ £%.2f (£%.0f)",
                     ticker, signal.entry_price, signal.notional_gbp)
        else:
            positions[ticker] = pos
            log.info("OPENED position: %s @ £%.2f", ticker, signal.entry_price)

        new_positions.append(pos)
        _send_entry_alert(pos, alert_mode_only)

    return new_positions


def _process_exits(
    positions: dict,
    catalysts: list[dict],
    trades: list[dict],
    cfg: dict,
    alert_mode_only: bool,
    today: str,
    spy_price: float,
) -> list[dict]:
    """Evaluate exit conditions and close positions that trigger."""
    exit_cfg = cfg.get("exit_rules", {})
    profit_target_pct = float(exit_cfg.get("profit_target_pct", 10.0))
    stop_loss_pct = float(exit_cfg.get("stop_loss_pct", -5.0))
    max_hold_days = int(exit_cfg.get("max_hold_trading_days", 10))

    # Build set of tickers with negative catalysts today
    negative_tickers = {
        c["ticker"] for c in catalysts if is_negative_8k(c)
    }

    closed = []
    for ticker, pos in list(positions.items()):
        market_data = fetch_market_data(ticker)
        if not market_data:
            log.debug("No market data for %s — cannot check exit", ticker)
            continue

        current_price = market_data["current_price"]
        signal = check_exit(
            position=pos,
            current_price=current_price,
            today=today,
            negative_catalyst=(ticker in negative_tickers),
            profit_target_pct=profit_target_pct,
            stop_loss_pct=-abs(stop_loss_pct),
            max_hold_trading_days=max_hold_days,
        )

        if not signal.should_exit:
            log.debug("HOLD %s @ £%.2f (%.1f%%)", ticker, current_price, signal.return_pct)
            continue

        trade = close_position(
            position=pos,
            exit_date=today,
            exit_price=current_price,
            exit_reason=signal.reason,
            spy_exit_price=spy_price,
        )

        if alert_mode_only:
            log.info("[ALERT MODE] Would close: %s @ £%.2f (%s, %.1f%%)",
                     ticker, current_price, signal.reason, signal.return_pct)
        else:
            del positions[ticker]
            append_trade(trade)
            trades.append(trade)
            log.info("CLOSED %s @ £%.2f: %s (%.1f%%)",
                     ticker, current_price, signal.reason, signal.return_pct)

        closed.append(trade)
        _send_exit_alert(trade, alert_mode_only)

    return closed


def _send_entry_alert(pos: dict, alert_mode_only: bool) -> None:
    prefix = "[ALERT MODE] " if alert_mode_only else ""
    msg = (
        f"{prefix}🟢 SWING ENTRY: {pos['ticker']}\n"
        f"Entry: £{pos['entry_price']:.2f} | Size: £{pos['notional_gbp']:.0f}\n"
        f"Stop: £{pos['stop_loss_price']:.2f} | Target: £{pos['profit_target_price']:.2f}\n"
        f"Catalyst: {pos['catalyst_type']}\n"
        f"Exit by: {pos['time_exit_date']}"
    )
    send_message(msg)


def _send_exit_alert(trade: dict, alert_mode_only: bool) -> None:
    prefix = "[ALERT MODE] " if alert_mode_only else ""
    pnl = trade.get("pnl_gbp", 0.0)
    ret = trade.get("return_pct", 0.0) * 100
    alpha = trade.get("alpha", 0.0) * 100
    icon = "🟢" if pnl >= 0 else "🔴"
    msg = (
        f"{prefix}{icon} SWING EXIT: {trade['ticker']}\n"
        f"Reason: {trade['exit_reason']}\n"
        f"Return: {ret:+.1f}% | P&L: £{pnl:+.2f}\n"
        f"Alpha vs SPY: {alpha:+.1f}%"
    )
    send_message(msg)


def main() -> None:
    cfg = _load_config()
    bot_cfg = cfg.get("bot", {})
    portfolio_cfg = cfg.get("portfolio", {})

    alert_mode_only = bool(bot_cfg.get("alert_mode_only", True))
    disable_date = str(bot_cfg.get("disable_date", "2026-11-25"))
    max_drawdown_pct = float(portfolio_cfg.get("kill_switch_pct", -10.0))
    phase_b_enabled = cfg.get("llm", {}).get("enabled", False)

    today = date.today().isoformat()
    now_utc = datetime.now(timezone.utc)

    log.info("=== Swing Bot catalyst poll %s (alert_mode_only=%s) ===", now_utc.isoformat(), alert_mode_only)

    # ── 1. Kill switch pre-check ──────────────────────────────────────────────
    trades = load_trades()
    triggered, reason = check_kill_switch(
        trades=trades,
        max_drawdown_pct=max_drawdown_pct,
        disable_date=disable_date,
    )
    if triggered:
        log.error("Kill switch active (%s) — aborting poll", reason)
        cumulative_pct = sum(t.get("return_pct", 0) for t in trades) * 100
        cumulative_gbp = sum(t.get("pnl_gbp", 0) for t in trades)
        send_message(format_kill_alert(reason, cumulative_pct, cumulative_gbp))
        sys.exit(0)

    # ── 2. Load state ─────────────────────────────────────────────────────────
    watchlist = _load_watchlist()
    positions = load_positions()
    seen_accessions = _load_seen_accessions()
    spy_price = _spy_price()

    log.info("Watchlist: %d tickers | Open positions: %d | SPY: £%.2f",
             len(watchlist), len(positions), spy_price)

    # ── 3. Poll catalyst sources ──────────────────────────────────────────────
    all_catalysts: list[dict] = []

    try:
        edgar_catalysts = get_recent_8ks(
            watchlist_tickers=watchlist,
            seen_accessions=seen_accessions,
            phase_b_enabled=phase_b_enabled,
        )
        for c in edgar_catalysts:
            seen_accessions.add(c.get("accession_number", ""))
        all_catalysts.extend(edgar_catalysts)
        log.info("EDGAR 8-K: %d new catalysts", len(edgar_catalysts))
    except Exception as exc:
        log.warning("EDGAR poll failed: %s", exc)

    try:
        earnings_catalysts = get_earnings_beats(
            tickers=watchlist,
            min_eps_beat_pct=float(cfg.get("entry_rules", {}).get("earnings_beat_min_pct", 5.0)),
        )
        all_catalysts.extend(earnings_catalysts)
        log.info("Earnings: %d catalysts", len(earnings_catalysts))
    except Exception as exc:
        log.warning("Earnings poll failed: %s", exc)

    try:
        fda_catalysts = get_fda_approvals(tickers=watchlist)
        all_catalysts.extend(fda_catalysts)
        log.info("FDA: %d catalysts", len(fda_catalysts))
    except Exception as exc:
        log.warning("FDA poll failed: %s", exc)

    try:
        volume_catalysts = get_volume_spikes(
            tickers=watchlist,
            volume_spike_multiplier=float(cfg.get("entry_rules", {}).get("volume_spike_multiplier", 3.0)),
        )
        all_catalysts.extend(volume_catalysts)
        log.info("Volume: %d catalysts", len(volume_catalysts))
    except Exception as exc:
        log.warning("Volume poll failed: %s", exc)

    log.info("Total catalysts this poll: %d", len(all_catalysts))

    # ── 4. Process exits first (reduce exposure before opening new) ───────────
    closed = _process_exits(
        positions=positions,
        catalysts=all_catalysts,
        trades=trades,
        cfg=cfg,
        alert_mode_only=alert_mode_only,
        today=today,
        spy_price=spy_price,
    )

    # ── 5. Process entries ────────────────────────────────────────────────────
    opened = _process_entries(
        catalysts=all_catalysts,
        positions=positions,
        cfg=cfg,
        alert_mode_only=alert_mode_only,
        today=today,
        spy_price=spy_price,
    )

    # ── 6. Persist state ──────────────────────────────────────────────────────
    if not alert_mode_only:
        save_positions(positions)

    _save_seen_accessions(seen_accessions)

    # ── 7. Post-trade kill switch check ───────────────────────────────────────
    if not alert_mode_only and closed:
        trades_updated = load_trades()
        triggered, reason = check_kill_switch(
            trades=trades_updated,
            max_drawdown_pct=max_drawdown_pct,
            disable_date=disable_date,
        )
        if triggered:
            log.error("Kill switch triggered after trade closes (%s)", reason)
            cumulative_pct = sum(t.get("return_pct", 0) for t in trades_updated) * 100
            cumulative_gbp = sum(t.get("pnl_gbp", 0) for t in trades_updated)
            send_message(format_kill_alert(reason, cumulative_pct, cumulative_gbp))

    log.info("Poll complete: %d opened, %d closed, %d open positions",
             len(opened), len(closed), len(positions))


if __name__ == "__main__":
    main()
