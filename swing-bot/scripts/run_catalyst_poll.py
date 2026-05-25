#!/usr/bin/env python3
"""Swing Bot Tier 0 catalyst poll — every 15 min during market hours (Mon-Fri 14:00-20:00 UTC).

Pipeline per run:
  1. Kill switch pre-check — abort if disabled
  2. Load Tier 0 active watchlist (open positions + recent catalyst tickers)
  3. Poll EDGAR for new 8-K filings on the full watchlist (push-based, cheap)
  4. For each EDGAR hit: add ticker to Tier 0, apply entry/exit rules
  5. For Tier 0 tickers: fetch Finnhub quote, check exits on open positions
  6. For Tier 0 tickers with catalyst in active list: check entry conditions
  7. Save state, send Telegram alerts

Finnhub call budget per run:
  ≤ 50 Tier 0 tickers × 1 quote = 50 calls (83% of 60/min limit)
  EDGAR uses SEC APIs, not Finnhub.

Hard rules enforced:
  - place_real_order() never called (raises RuntimeError if called)
  - alert_mode_only: True  → log signals but skip all I/O writes
  - Ringfenced: only reads/writes swing-bot/data/
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

from src.active_watchlist import add_catalyst_ticker, get_tier0
from src.catalysts.edgar_8k import get_recent_8ks
from src.finnhub_client import FinnhubClient
from src.kill_switch import check_kill_switch, format_kill_alert, format_soft_alert
from src.paper_executor import (
    append_trade, close_position, load_positions, load_trades,
    open_position, save_positions,
)
from src.rules.entry import build_entry_signal, check_entry, fetch_market_data
from src.rules.exit import check_exit
from src.rules.filters import is_negative_8k, passes_all_filters
from src.telegram_client import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("catalyst_poll")

_CONFIG_PATH = _ROOT / "config" / "settings.yaml"
_WATCHLIST_PATH = _ROOT / "config" / "watchlist.yaml"
_SEEN_PATH = _ROOT / "data" / "seen_accessions.json"
_CATALYST_LOG = _ROOT / "data" / "catalyst_log.jsonl"
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
    return list(dict.fromkeys(tickers))


def _load_seen_accessions() -> set[str]:
    if not _SEEN_PATH.exists():
        return set()
    with open(_SEEN_PATH) as f:
        return set(json.load(f))


def _save_seen_accessions(seen: set[str]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SEEN_PATH, "w") as f:
        json.dump(list(seen)[-2000:], f)


def _log_catalyst(catalyst: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {**catalyst, "logged_at": datetime.now(timezone.utc).isoformat()}
    with open(_CATALYST_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _spy_quote(client: FinnhubClient) -> float:
    q = client.quote("SPY")
    return q.get("current_price", 0.0)


def _send_entry_alert(pos: dict, alert_mode: bool) -> None:
    prefix = "[ALERT MODE] " if alert_mode else ""
    msg = (
        f"{prefix}🟢 SWING ENTRY: {pos['ticker']}\n"
        f"Entry: ${pos['entry_price']:.2f} | Size: £{pos['notional_gbp']:.0f}\n"
        f"Stop: ${pos['stop_loss_price']:.2f} | Target: ${pos['profit_target_price']:.2f}\n"
        f"Catalyst: {pos['catalyst_type']}\n"
        f"Exit by: {pos['time_exit_date']}"
    )
    send_message(msg)


def _send_exit_alert(trade: dict, alert_mode: bool) -> None:
    prefix = "[ALERT MODE] " if alert_mode else ""
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
    entry_cfg = cfg.get("entry_rules", {})
    exit_cfg = cfg.get("exit_rules", {})

    alert_mode = bool(bot_cfg.get("alert_mode_only", True))
    disable_date = str(bot_cfg.get("disable_date", "2026-11-25"))
    phase_b = cfg.get("llm", {}).get("enabled", False)

    position_size_gbp = float(portfolio_cfg.get("position_size_gbp", 50.0))
    max_positions = int(portfolio_cfg.get("max_positions", 10))
    profit_target = float(exit_cfg.get("profit_target_pct", 10.0))
    stop_loss = float(exit_cfg.get("stop_loss_pct", -5.0))
    max_hold_days = int(exit_cfg.get("max_hold_trading_days", 10))

    today = date.today().isoformat()
    now = datetime.now(timezone.utc)
    log.info("=== Tier 0 catalyst poll %s (alert_mode=%s) ===", now.isoformat(), alert_mode)

    # ── 1. Kill switch pre-check ──────────────────────────────────────────────
    trades = load_trades()
    hard_killed, reason, _ = check_kill_switch(trades, disable_date=disable_date)
    if hard_killed:
        log.error("Kill switch hard kill (%s) — aborting", reason)
        cumulative_gbp = sum(t.get("pnl_gbp", 0) for t in trades)
        cumulative_pct = cumulative_gbp / 500.0 * 100
        send_message(format_kill_alert(reason, cumulative_pct, cumulative_gbp))
        sys.exit(0)

    # ── 2. Load state ─────────────────────────────────────────────────────────
    watchlist = _load_watchlist()
    positions = load_positions()
    seen_accessions = _load_seen_accessions()
    finnhub = FinnhubClient()

    # ── 3. EDGAR 8-K push (full watchlist, no per-ticker Finnhub cost) ────────
    new_catalysts: list[dict] = []
    edgar_catalysts: list[dict] = []
    try:
        edgar_catalysts = get_recent_8ks(
            watchlist_tickers=watchlist,
            seen_accessions=seen_accessions,
            phase_b_enabled=phase_b,
        )
        for c in edgar_catalysts:
            seen_accessions.add(c.get("accession_number", ""))
            _log_catalyst(c)
            add_catalyst_ticker(c["ticker"], f"8K:{c.get('catalyst_type','?')}")
        new_catalysts.extend(edgar_catalysts)
        log.info("EDGAR: %d new 8-K catalysts", len(edgar_catalysts))
    except Exception as exc:
        log.warning("EDGAR poll failed: %s", exc)
    _save_seen_accessions(seen_accessions)

    # ── 4. Build Tier 0 active list ───────────────────────────────────────────
    tier0 = get_tier0(positions)
    log.info("Tier 0: %d tickers (%d open positions)", len(tier0), len(positions))

    # Set of tickers with a negative catalyst today (for signal reversal exit)
    negative_tickers = {c["ticker"] for c in edgar_catalysts if is_negative_8k(c)}

    # ── 5. Fetch Finnhub quote for each Tier 0 ticker ────────────────────────
    # Count SPY quote for alpha tracking
    spy_price = _spy_quote(finnhub)
    log.info("SPY: $%.2f", spy_price)

    finnhub_calls = 1  # SPY
    tier0_quotes: dict[str, dict] = {}
    for ticker in tier0:
        q = finnhub.quote(ticker)
        finnhub_calls += 1
        if q:
            tier0_quotes[ticker] = q
    log.info("Finnhub: %d calls, %d quotes received", finnhub_calls, len(tier0_quotes))

    # ── 6. Process exits for open positions ───────────────────────────────────
    closed: list[dict] = []
    for ticker, pos in list(positions.items()):
        quote = tier0_quotes.get(ticker)
        if not quote:
            log.debug("No Finnhub quote for %s — skipping exit check", ticker)
            continue

        cur_price = quote["current_price"]
        exit_sig = check_exit(
            position=pos,
            current_price=cur_price,
            today=today,
            negative_catalyst=(ticker in negative_tickers),
            profit_target_pct=profit_target,
            stop_loss_pct=-abs(stop_loss),
            max_hold_trading_days=max_hold_days,
        )
        if not exit_sig.should_exit:
            log.debug("HOLD %s @ $%.2f (%+.1f%%)", ticker, cur_price, exit_sig.return_pct)
            continue

        trade = close_position(pos, today, cur_price, exit_sig.reason, spy_price)
        if not alert_mode:
            del positions[ticker]
            append_trade(trade)
            trades.append(trade)
            log.info("CLOSED %s @ $%.2f: %s (%+.1f%%)", ticker, cur_price, exit_sig.reason, exit_sig.return_pct)
        else:
            log.info("[ALERT] Would close %s @ $%.2f: %s (%+.1f%%)", ticker, cur_price, exit_sig.reason, exit_sig.return_pct)

        closed.append(trade)
        _send_exit_alert(trade, alert_mode)

    # ── 7. Process entries for catalyst tickers ───────────────────────────────
    opened: list[dict] = []

    # Candidates = tickers with a fresh catalyst, not already held
    catalyst_tickers = {c["ticker"] for c in new_catalysts}
    entry_candidates = [t for t in catalyst_tickers if t not in positions]

    for ticker in entry_candidates:
        if not passes_all_filters(next(c for c in new_catalysts if c["ticker"] == ticker), phase_b):
            continue

        # Prefer Finnhub quote for entry price; fall back to yfinance for volume/trend
        fq = tier0_quotes.get(ticker) or finnhub.quote(ticker)
        if not fq:
            continue
        finnhub_calls += (0 if ticker in tier0_quotes else 1)

        # Augment with yfinance for 5-day trend + volume (no extra Finnhub cost)
        yf_data = fetch_market_data(ticker)
        market_data = {
            "current_price": fq["current_price"],
            "price_change_pct": fq["price_change_pct"],
            "trend_5d_pct": yf_data.get("trend_5d_pct", 0.0),
            "avg_daily_volume_usd": yf_data.get("avg_daily_volume_usd", 0.0),
        }

        catalyst = next(c for c in new_catalysts if c["ticker"] == ticker)
        result = check_entry(
            ticker=ticker,
            catalyst=catalyst,
            market_data=market_data,
            n_open_positions=len(positions),
            position_size_gbp=position_size_gbp,
            min_price_change_pct=float(entry_cfg.get("min_price_change_pct", 3.0)),
            min_liquidity_usd=float(entry_cfg.get("min_liquidity_usd", 6_350_000)),
            five_day_trend_floor_pct=float(entry_cfg.get("five_day_trend_floor_pct", -1.0)),
            max_positions=max_positions,
        )
        if not result.passed:
            log.info("Entry FAILED %s: %s", ticker, result.reason)
            continue

        log.info("Entry PASSED %s: catalyst=%s price=%+.1f%% vol=$%.0fM",
                 ticker, catalyst.get("catalyst_type"), market_data["price_change_pct"],
                 market_data["avg_daily_volume_usd"] / 1e6)

        signal = build_entry_signal(ticker, catalyst, fq["current_price"], position_size_gbp,
                                    profit_target, -abs(stop_loss))
        from datetime import timedelta
        time_exit = (date.fromisoformat(today) + timedelta(days=14)).isoformat()

        pos = open_position(
            ticker=ticker, entry_date=today, entry_price=signal.entry_price,
            shares=signal.shares, notional_gbp=signal.notional_gbp, catalyst=catalyst,
            spy_entry_price=spy_price, stop_loss_price=signal.stop_loss_price,
            profit_target_price=signal.profit_target_price, time_exit_date=time_exit,
        )
        if not alert_mode:
            positions[ticker] = pos
            log.info("OPENED %s @ $%.2f", ticker, signal.entry_price)
        else:
            log.info("[ALERT] Would open %s @ $%.2f", ticker, signal.entry_price)

        opened.append(pos)
        _send_entry_alert(pos, alert_mode)

    # ── 8. Persist ────────────────────────────────────────────────────────────
    if not alert_mode:
        save_positions(positions)

    # ── 9. Post-trade kill switch ──────────────────────────────────────────────
    if not alert_mode and closed:
        trades_now = load_trades()
        hard_killed, reason, soft_fired = check_kill_switch(trades_now, disable_date=disable_date)
        cum_gbp = sum(t.get("pnl_gbp", 0) for t in trades_now)
        cum_pct = cum_gbp / 500.0 * 100
        if hard_killed:
            send_message(format_kill_alert(reason, cum_pct, cum_gbp))
        elif soft_fired:
            send_message(format_soft_alert(cum_pct, cum_gbp))

    log.info("Poll done: %d opened, %d closed, %d open, %d Finnhub calls",
             len(opened), len(closed), len(positions), finnhub_calls)


if __name__ == "__main__":
    main()
