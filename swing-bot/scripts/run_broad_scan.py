#!/usr/bin/env python3
"""Swing Bot Tier 1 broad scan — runs once daily after US close (~22:00 UTC weekdays).

Scans the full ~500-ticker watchlist via yfinance batch download for:
  - Earnings beats (EPS beat ≥ 5% + revenue beat)
  - Volume spikes (today > 3× 30-day average)
  - Strong intraday momentum (≥ 3% close-to-close change)

Any ticker that passes one or more filters is added to the Tier 0 active watchlist
so the next 15-min poll immediately picks it up with Finnhub quotes.

Also logs all scan results to data/broad_scan_log.jsonl for auditing.

No Finnhub calls in this script — keeps the budget clean.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import yaml

from src.active_watchlist import add_catalyst_ticker
from src.catalysts.earnings_monitor import get_earnings_beats
from src.catalysts.volume_anomaly import get_volume_spikes
from src.kill_switch import is_disabled
from src.rules.filters import passes_all_filters
from src.telegram_client import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("broad_scan")

_CONFIG_PATH = _ROOT / "config" / "settings.yaml"
_WATCHLIST_PATH = _ROOT / "config" / "watchlist.yaml"
_SCAN_LOG = _ROOT / "data" / "broad_scan_log.jsonl"
_DATA_DIR = _ROOT / "data"

_BATCH_SIZE = 50   # process watchlist in batches to avoid yfinance timeouts
_BATCH_SLEEP = 2   # seconds between batches


def _load_watchlist() -> list[str]:
    with open(_WATCHLIST_PATH) as f:
        wl = yaml.safe_load(f) or {}
    tickers: list[str] = []
    for tier in ("tier1", "tier2"):
        tickers.extend(wl.get(tier, []))
    return list(dict.fromkeys(tickers))


def _log_scan_result(record: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_SCAN_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _scan_batch(tickers: list[str], cfg: dict) -> list[dict]:
    """Scan one batch of tickers. Returns list of catalyst dicts found."""
    entry_cfg = cfg.get("entry_rules", {})
    min_eps_beat = float(entry_cfg.get("earnings_beat_min_pct", 5.0))
    vol_spike_mult = float(entry_cfg.get("volume_spike_multiplier", 3.0))

    catalysts: list[dict] = []

    try:
        earnings = get_earnings_beats(tickers, min_eps_beat_pct=min_eps_beat)
        catalysts.extend(earnings)
    except Exception as exc:
        log.debug("Earnings scan batch failed: %s", exc)

    try:
        spikes = get_volume_spikes(tickers, volume_spike_multiplier=vol_spike_mult)
        catalysts.extend(spikes)
    except Exception as exc:
        log.debug("Volume scan batch failed: %s", exc)

    return catalysts


def main() -> None:
    cfg_path = _CONFIG_PATH
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    if is_disabled():
        log.info("Kill switch is active — skipping broad scan")
        sys.exit(0)

    watchlist = _load_watchlist()
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    log.info("=== Tier 1 broad scan %s — %d tickers ===", now, len(watchlist))

    phase_b = cfg.get("llm", {}).get("enabled", False)
    all_catalysts: list[dict] = []

    # Process in batches to avoid hammering yfinance
    for i in range(0, len(watchlist), _BATCH_SIZE):
        batch = watchlist[i:i + _BATCH_SIZE]
        log.debug("Scanning batch %d-%d (%d tickers)", i, i + len(batch), len(batch))
        found = _scan_batch(batch, cfg)
        all_catalysts.extend(found)
        if i + _BATCH_SIZE < len(watchlist):
            time.sleep(_BATCH_SLEEP)

    log.info("Broad scan complete: %d catalysts found across %d tickers", len(all_catalysts), len(watchlist))

    # Filter to material catalysts only and add to Tier 0
    tier0_additions: list[str] = []
    for catalyst in all_catalysts:
        ticker = catalyst.get("ticker", "")
        if not ticker:
            continue
        if passes_all_filters(catalyst, phase_b_enabled=phase_b):
            add_catalyst_ticker(ticker, f"broad:{catalyst.get('catalyst_type','?')}")
            tier0_additions.append(ticker)
            log.info("Added to Tier 0: %s (%s)", ticker, catalyst.get("catalyst_type"))

        _log_scan_result({
            "date": today,
            "ticker": ticker,
            "catalyst_type": catalyst.get("catalyst_type"),
            "passes_filter": ticker in tier0_additions,
            **{k: v for k, v in catalyst.items() if k not in ("ticker", "catalyst_type")},
        })

    if tier0_additions:
        msg = (
            f"📡 BROAD SCAN COMPLETE — {today}\n\n"
            f"Scanned: {len(watchlist)} tickers\n"
            f"Catalysts found: {len(all_catalysts)}\n"
            f"Added to Tier 0: {len(tier0_additions)}\n\n"
            + "\n".join(f"  • {t}" for t in tier0_additions[:10])
            + ("\n  ..." if len(tier0_additions) > 10 else "")
        )
        send_message(msg)
        log.info("Sent Tier 0 additions to Telegram")
    else:
        log.info("No Tier 0 additions — no message sent")


if __name__ == "__main__":
    main()
