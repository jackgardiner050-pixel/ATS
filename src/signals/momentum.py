"""12-month relative price momentum signal (12-1 factor, T-12 to T-1).

Excludes the most recent calendar month to avoid short-term reversal contamination.
Quintile 1 = top performers (highest return), Quintile 5 = bottom.
"""
from __future__ import annotations
import math


def _assign_quintiles(returns: dict[str, float | None]) -> dict[str, dict]:
    """Pure-math assignment of percentile and quintile from a returns dict.

    Quintile 1 = highest return (top 20%), Quintile 5 = lowest (bottom 20%).
    Tickers with None returns get quintile=None.
    """
    valid = [(t, v) for t, v in returns.items()
             if v is not None and not math.isnan(float(v))]
    valid.sort(key=lambda x: x[1])          # ascending: worst → best
    n = len(valid)

    result: dict[str, dict] = {}
    for ticker, ret in returns.items():
        if ret is None or (isinstance(ret, float) and math.isnan(ret)):
            result[ticker] = {"return_12m": None, "pctile": None, "quintile": None}
            continue
        rank = next(i for i, (t, _) in enumerate(valid) if t == ticker)
        pctile = rank / (n - 1) if n > 1 else 0.5
        # Map pctile [0,1] → quintile [5,1]: pctile=0 (worst)→Q5, pctile=1 (best)→Q1
        q = 5 - min(4, int(pctile * 5))
        result[ticker] = {
            "return_12m": float(ret),
            "pctile": round(pctile, 4),
            "quintile": q,
        }
    return result


def _fetch_single_return(ticker: str, yf) -> float | None:
    """Return 12m price return (T-12 to T-1) for a single ticker via yfinance."""
    try:
        hist = yf.Ticker(ticker).history(period="13mo")
        if hist is None or hist.empty:
            return None
        monthly = hist["Close"].resample("ME").last().dropna()
        if len(monthly) < 13:
            return None
        t1_price = float(monthly.iloc[-2])    # end of last complete month (T-1)
        t12_price = float(monthly.iloc[-13])  # end of 12th prior month (T-12)
        if t12_price <= 0:
            return None
        return t1_price / t12_price - 1.0
    except Exception:
        return None


def compute_universe_momentum(tickers: list[str]) -> dict[str, dict]:
    """Compute 12m momentum for all tickers and rank within the universe.

    Returns {ticker: {"return_12m": float | None, "pctile": float | None, "quintile": int | None}}.
    Missing or insufficient history → quintile = None.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {t: {"return_12m": None, "pctile": None, "quintile": None} for t in tickers}

    raw: dict[str, float | None] = {}
    for ticker in tickers:
        raw[ticker] = _fetch_single_return(ticker, yf)

    return _assign_quintiles(raw)
