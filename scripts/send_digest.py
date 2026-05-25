#!/usr/bin/env python3
"""Send weekly Telegram digest after run_universe.py + paper_run.py complete.

Called by cron at 09:15 UTC Sunday:
  .venv/bin/python scripts/send_digest.py >> logs/digest.log 2>&1

Hard rules:
  no_real_orders       : True — sends text messages only, no trade execution
  no_live_pnl_learning : True — reads positions for display only
  human_gated          : True — all action belongs to the human reader
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

_AGENT_ROOT = Path(__file__).parent.parent


def _load_dotenv(path: Path = _AGENT_ROOT / ".env") -> None:
    """Load key=value pairs from .env into os.environ (no library required)."""
    if not path.exists():
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def _latest_summary() -> dict:
    screen_root = _AGENT_ROOT / "runs" / "_screen"
    dirs = sorted(d for d in screen_root.iterdir() if d.is_dir())
    if not dirs:
        raise FileNotFoundError("No screen runs found under runs/_screen/")
    path = dirs[-1] / "summary.json"
    with open(path) as f:
        return json.load(f)


def _paper_book_metrics(spy_price: float | None) -> dict:
    """Compute unrealised P&L for the paper book. Pure read — no writes."""
    from src.paper_trading import load_positions, load_trades

    positions = load_positions()
    trades = load_trades()

    if not positions:
        return {
            "n_open": 0,
            "n_closed": len(trades),
            "avg_unrealized_pct": None,
            "spy_return_pct": None,
            "entry_date_first": None,
        }

    # Fetch current prices
    rets: list[float] = []
    spy_rets: list[float] = []
    try:
        import yfinance as yf
        for ticker, pos in positions.items():
            try:
                info = yf.Ticker(ticker).info
                current = None
                for key in ("regularMarketPrice", "currentPrice", "previousClose"):
                    v = info.get(key)
                    if v and float(v) > 0:
                        current = float(v)
                        break
                if current and spy_price:
                    rets.append(current / pos["entry_price"] - 1.0)
                    spy_rets.append(spy_price / pos["spy_entry_price"] - 1.0)
            except Exception:
                pass
    except ImportError:
        pass

    entry_date_first = min(
        (pos.get("entry_date", "9999") for pos in positions.values()),
        default=None,
    )

    return {
        "n_open": len(positions),
        "n_closed": len(trades),
        "avg_unrealized_pct": sum(rets) / len(rets) if rets else None,
        "spy_return_pct": sum(spy_rets) / len(spy_rets) if spy_rets else None,
        "entry_date_first": entry_date_first,
    }


def main() -> None:
    _load_dotenv()

    from src.telegram.client import send_message
    from src.telegram.digest import format_digest
    from src.telegram.alerts import (
        is_quiet_hours, load_last_state, save_current_state, detect_changes,
    )
    from src.paper_trading import fetch_spy_price

    today = str(date.today())
    log.info("send_digest starting — %s", today)

    # Quiet hours check (digest always fires at 09:15 UTC, well outside window,
    # but guard is here for robustness if the cron time ever shifts)
    if is_quiet_hours():
        log.info("Quiet hours active — skipping digest send")
        return

    # Load screener output
    try:
        summary = _latest_summary()
    except Exception as exc:
        log.error("Could not load summary: %s", exc)
        return

    results = summary.get("results", [])
    log.info("Loaded summary: %d tickers", len(results))

    # SPY price
    spy_price = fetch_spy_price()
    if spy_price is None:
        log.warning("Could not fetch SPY price — paper book marks will be unavailable")

    # Paper book metrics
    try:
        paper_book = _paper_book_metrics(spy_price)
    except Exception as exc:
        log.warning("Paper book metrics failed: %s", exc)
        paper_book = {"n_open": 0, "n_closed": 0}

    # Rating change detection
    last_state = load_last_state()
    changes = detect_changes(results, last_state)
    if changes:
        log.info("Rating changes detected: %s", [c["ticker"] for c in changes])

    # Format and send digest
    digest_text = format_digest(results, paper_book, changes, today)
    ok = send_message(digest_text)
    if ok:
        log.info("Digest sent successfully")
    else:
        log.error("Digest send failed — check Telegram credentials and network")

    # Save state snapshot for next week's change detection
    save_current_state(results)
    log.info("State snapshot saved")


if __name__ == "__main__":
    main()
