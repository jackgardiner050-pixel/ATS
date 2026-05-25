"""Detect unusual volume + price spikes for watchlist tickers.

Criteria: today's volume > 3× 30-day average volume AND price up ≥ 3% on the day.
Data source: yfinance (free, no key required).

This is an independent catalyst signal — does not require a specific event.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def get_volume_anomalies(
    watchlist_tickers: set[str],
    volume_multiplier: float = 3.0,
    min_price_change_pct: float = 3.0,
) -> list[dict]:
    """Return volume-spike catalysts for watchlist tickers.

    Args:
        watchlist_tickers:    Set of uppercase ticker symbols.
        volume_multiplier:    Trigger if today's vol > N× 30-day avg (default 3×).
        min_price_change_pct: Also require price up ≥ N% on the day (default 3%).

    Returns:
        List of catalyst dicts.
    """
    catalysts: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed")
        return []

    for ticker in watchlist_tickers:
        try:
            result = _check_volume_spike(ticker, yf, volume_multiplier, min_price_change_pct)
            if result:
                catalysts.append(result)
        except Exception as exc:
            log.debug("Volume check failed for %s: %s", ticker, exc)

    return catalysts


def _check_volume_spike(
    ticker: str,
    yf,
    volume_multiplier: float,
    min_price_change_pct: float,
) -> Optional[dict]:
    """Return catalyst dict if volume spike + price criteria met, else None."""
    hist = yf.Ticker(ticker).history(period="35d")
    if hist is None or (hasattr(hist, "empty") and hist.empty) or len(hist) < 5:
        return None

    today_row = hist.iloc[-1]
    today_volume = float(today_row.get("Volume", 0))
    today_close = float(today_row.get("Close", 0))
    today_open = float(today_row.get("Open", today_close))

    if today_volume == 0 or today_close == 0:
        return None

    avg_volume_30d = float(hist["Volume"].iloc[:-1].tail(30).mean())
    if avg_volume_30d == 0:
        return None

    volume_ratio = today_volume / avg_volume_30d
    price_change_pct = (today_close - today_open) / today_open * 100

    if volume_ratio < volume_multiplier:
        return None
    if price_change_pct < min_price_change_pct:
        return None

    return {
        "ticker": ticker,
        "catalyst_type": "VOLUME_SPIKE",
        "volume_today": int(today_volume),
        "volume_30d_avg": int(avg_volume_30d),
        "volume_ratio": round(volume_ratio, 2),
        "price_change_pct": round(price_change_pct, 2),
        "current_price": round(today_close, 4),
        "material": True,
        "confidence": 1.0,
    }
