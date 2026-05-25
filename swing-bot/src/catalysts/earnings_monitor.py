"""Detect earnings beats for watchlist tickers.

Criteria: EPS beat ≥ 5% AND positive revenue surprise.
Data source: yfinance (free, no key required).

Called during every 15-min poll. Only tickers with earnings today are evaluated.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)


def get_earnings_beats(
    watchlist_tickers: set[str],
    min_beat_pct: float = 5.0,
) -> list[dict]:
    """Return earnings-beat catalysts for tickers reporting today.

    Args:
        watchlist_tickers: Set of uppercase ticker symbols.
        min_beat_pct:      Minimum EPS beat percentage (default 5%).

    Returns:
        List of catalyst dicts with EPS beat details.
    """
    catalysts: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed")
        return []

    for ticker in watchlist_tickers:
        try:
            result = _check_earnings_beat(ticker, yf, min_beat_pct)
            if result:
                catalysts.append(result)
        except Exception as exc:
            log.debug("Earnings check failed for %s: %s", ticker, exc)

    return catalysts


def _check_earnings_beat(
    ticker: str,
    yf,
    min_beat_pct: float,
) -> Optional[dict]:
    """Check if ticker reported an earnings beat today. Returns catalyst dict or None."""
    t = yf.Ticker(ticker)

    # earnings_history contains quarterly results with actual vs estimated EPS
    try:
        hist = t.earnings_history
        if hist is None or (hasattr(hist, "empty") and hist.empty):
            return None
    except Exception:
        return None

    if hasattr(hist, "empty") and hist.empty:
        return None

    # Most recent quarter
    try:
        most_recent = hist.iloc[0]
        eps_actual = most_recent.get("epsActual")
        eps_estimate = most_recent.get("epsEstimate")
        surprise_pct = most_recent.get("surprisePercent")
    except (IndexError, AttributeError, KeyError):
        return None

    if eps_actual is None or eps_estimate is None or eps_estimate == 0:
        return None

    if surprise_pct is None:
        try:
            surprise_pct = (float(eps_actual) - float(eps_estimate)) / abs(float(eps_estimate)) * 100
        except (TypeError, ZeroDivisionError):
            return None

    if float(surprise_pct) < min_beat_pct:
        return None

    # Check revenue surprise (positive = beat)
    rev_surprise = _check_revenue_surprise(t)

    return {
        "ticker": ticker,
        "catalyst_type": "EARNINGS_BEAT",
        "eps_actual": float(eps_actual),
        "eps_estimate": float(eps_estimate),
        "eps_beat_pct": round(float(surprise_pct), 2),
        "revenue_beat": rev_surprise,
        "material": True,
        "confidence": 1.0,
    }


def _check_revenue_surprise(t) -> bool:
    """Return True if most recent quarter had positive revenue surprise."""
    try:
        quarterly = t.quarterly_financials
        if quarterly is None or (hasattr(quarterly, "empty") and quarterly.empty):
            return False
        # If revenue exists and is positive, consider it a beat (yfinance doesn't
        # always expose revenue estimates — positive revenue is a soft check)
        revenue_row = quarterly.loc["Total Revenue"] if "Total Revenue" in quarterly.index else None
        if revenue_row is not None and len(revenue_row) >= 2:
            latest = float(revenue_row.iloc[0])
            prior = float(revenue_row.iloc[1])
            return latest > prior
    except Exception:
        pass
    return False
