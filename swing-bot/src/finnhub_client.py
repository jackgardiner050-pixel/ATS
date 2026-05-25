"""Finnhub API client — rate-limited to 60 calls/min (free tier).

Provides only what swing-bot needs: quote + company news headline count.
All methods return empty dict/list on failure — never raise.

Free tier limits:
  60 calls/minute  (we target ≤1 req/sec, leaving headroom)
  US quotes: 15-minute delayed (acceptable per spec)

API docs: https://finnhub.io/docs/api
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"
_CALL_INTERVAL = 1.05  # seconds between calls — 57/min, safe margin under 60/min
_TIMEOUT = 10
_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_api_key() -> str:
    """Read FINNHUB_API_KEY from swing-bot/.env or process environment."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    if key:
        return key
    if _ENV_PATH.exists():
        with open(_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FINNHUB_API_KEY="):
                    return line.partition("=")[2].strip().strip('"').strip("'")
    return ""


class FinnhubClient:
    """Rate-limited Finnhub client. One instance per process — controls call spacing."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or _load_api_key()
        self._last_call_time: float = 0.0

    def _get(self, endpoint: str, params: dict) -> dict | list:
        """Execute a rate-limited GET. Returns {} on any failure."""
        if not self._api_key:
            log.warning("FINNHUB_API_KEY not set — skipping Finnhub call")
            return {}
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < _CALL_INTERVAL:
            time.sleep(_CALL_INTERVAL - elapsed)
        try:
            resp = requests.get(
                f"{_BASE_URL}/{endpoint}",
                params={**params, "token": self._api_key},
                timeout=_TIMEOUT,
            )
            self._last_call_time = time.monotonic()
            if resp.status_code == 429:
                log.warning("Finnhub rate limit hit (429) — sleeping 60s")
                time.sleep(60)
                return {}
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            self._last_call_time = time.monotonic()
            log.debug("Finnhub %s failed: %s", endpoint, exc)
            return {}

    def quote(self, symbol: str) -> dict:
        """Fetch current quote for a symbol.

        Returns dict with keys: current_price, price_change_pct, prev_close,
        open, high, low. Returns {} if symbol not found or request fails.

        Prices are 15-minute delayed on free tier.
        """
        data = self._get("quote", {"symbol": symbol})
        if not data or not isinstance(data, dict):
            return {}
        c = data.get("c", 0)
        if not c or c == 0:
            return {}
        pc = float(data.get("pc", c))
        dp = (c - pc) / pc * 100 if pc > 0 else float(data.get("dp", 0))
        return {
            "current_price": float(c),
            "price_change_pct": round(float(dp), 4),
            "prev_close": float(pc),
            "open": float(data.get("o", c)),
            "high": float(data.get("h", c)),
            "low": float(data.get("l", c)),
        }

    def batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple symbols. Returns {ticker: quote_dict}.

        Respects rate limit between each call.
        """
        results: dict[str, dict] = {}
        for sym in symbols:
            q = self.quote(sym)
            if q:
                results[sym] = q
        return results
