"""Active watchlist (Tier 0) management.

Tier 0 = tickers polled every 15 minutes via Finnhub.
Membership rules:
  1. Any ticker currently in the paper book (open position)
  2. Any ticker that received a catalyst in the last 48 hours

Stored in data/active_watchlist.json:
  {"tickers": {"AAPL": {"added": "2026-05-25T14:00:00+00:00", "reason": "catalyst"}}}

Capped at MAX_ACTIVE to stay well within Finnhub 60 calls/min.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_STATE_PATH = Path(__file__).parent.parent / "data" / "active_watchlist.json"
MAX_ACTIVE = 50       # hard cap — 50 Finnhub calls/poll well within 60/min
CATALYST_TTL_HOURS = 48  # remove catalyst tickers after 48h if not in book


def load(path: Optional[Path] = None) -> dict[str, dict]:
    """Load active watchlist. Returns {ticker: {added, reason}}."""
    p = path or _STATE_PATH
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = json.load(f)
        return data.get("tickers", {})
    except Exception as exc:
        log.warning("Failed to load active watchlist: %s", exc)
        return {}


def save(tickers: dict[str, dict], path: Optional[Path] = None) -> None:
    p = path or _STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump({"tickers": tickers}, f, default=str, indent=2)


def add_catalyst_ticker(
    ticker: str,
    reason: str,
    tickers: Optional[dict[str, dict]] = None,
    path: Optional[Path] = None,
) -> dict[str, dict]:
    """Add a ticker that just triggered a catalyst. Returns updated dict."""
    if tickers is None:
        tickers = load(path)
    now = datetime.now(timezone.utc).isoformat()
    if ticker not in tickers:
        log.debug("Active watchlist: adding %s (%s)", ticker, reason)
    tickers[ticker] = {"added": now, "reason": reason}
    save(tickers, path)
    return tickers


def get_tier0(
    open_positions: dict[str, dict],
    path: Optional[Path] = None,
    max_age_hours: int = CATALYST_TTL_HOURS,
) -> list[str]:
    """Return deduplicated list of Tier 0 tickers: open positions + recent catalysts.

    Automatically prunes entries older than max_age_hours that are no longer in
    the paper book.
    """
    stored = load(path)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    # Prune stale catalyst tickers (not in open positions)
    pruned: dict[str, dict] = {}
    for ticker, meta in stored.items():
        if ticker in open_positions:
            pruned[ticker] = meta  # always keep open positions
            continue
        try:
            added_dt = datetime.fromisoformat(meta["added"])
            if added_dt.tzinfo is None:
                added_dt = added_dt.replace(tzinfo=timezone.utc)
            if added_dt >= cutoff:
                pruned[ticker] = meta  # keep recent catalysts
        except (KeyError, ValueError):
            pass  # drop malformed entries

    # Add all open positions in case they weren't in stored
    for ticker in open_positions:
        if ticker not in pruned:
            pruned[ticker] = {"added": now.isoformat(), "reason": "open_position"}

    save(pruned, path)

    # Return sorted list, capped at MAX_ACTIVE
    result = sorted(pruned.keys())
    if len(result) > MAX_ACTIVE:
        log.warning("Active watchlist capped at %d (had %d)", MAX_ACTIVE, len(result))
        result = result[:MAX_ACTIVE]
    return result
