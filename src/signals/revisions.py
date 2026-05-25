"""EPS revision direction signal using consensus estimate trend (90-day window).

Data source: yfinance Ticker.eps_trend, +1y (FY1) row.
Compares current consensus EPS estimate to the 90-day-ago estimate.
Threshold: >+2% → POSITIVE, <-2% → NEGATIVE, within ±2% → FLAT.
No analyst count gate — eps_trend already aggregates the consensus.
"""
from __future__ import annotations
import math


def _compute_direction(eps_current, eps_90d_ago) -> str:
    """Pure-logic EPS revision classification using ±2% threshold.

    Returns POSITIVE | NEGATIVE | FLAT | NO_COVERAGE.
    Threshold is strict (>2%, not >=2%) to avoid noise from rounding.
    Near-zero base (|eps_90d_ago| < 0.001) returns NO_COVERAGE —
    ratio-based comparison is unreliable when base EPS is near zero.
    """
    try:
        if eps_current is None or eps_90d_ago is None:
            return "NO_COVERAGE"
        cur = float(eps_current)
        ago = float(eps_90d_ago)
        if math.isnan(cur) or math.isnan(ago):
            return "NO_COVERAGE"
        if abs(ago) < 0.001:
            return "NO_COVERAGE"
    except (TypeError, ValueError):
        return "NO_COVERAGE"

    if cur > ago * 1.02:
        return "POSITIVE"
    if cur < ago * 0.98:
        return "NEGATIVE"
    return "FLAT"


def compute_revisions(ticker: str) -> dict:
    """Return FY1 EPS revision direction for ticker using eps_trend consensus data.

    Compares the current +1y EPS consensus to the estimate from 90 days ago.
    Returns {"direction": str, "eps_current": float|None, "eps_90d_ago": float|None,
             "eps_change_pct": float|None}.
    direction: POSITIVE | NEGATIVE | FLAT | NO_COVERAGE
    """
    _empty = {"direction": "NO_COVERAGE", "eps_current": None,
              "eps_90d_ago": None, "eps_change_pct": None}
    try:
        import yfinance as yf
        et = yf.Ticker(ticker).eps_trend
        if et is None or (hasattr(et, "empty") and et.empty):
            return _empty
        if "+1y" not in et.index:
            return _empty

        row = et.loc["+1y"]
        eps_current = row.get("current")
        eps_90d_ago = row.get("90daysAgo")

        direction = _compute_direction(eps_current, eps_90d_ago)

        if direction == "NO_COVERAGE":
            return _empty

        cur = float(eps_current)
        ago = float(eps_90d_ago)
        change_pct = round((cur - ago) / abs(ago) * 100, 2)

        return {
            "direction": direction,
            "eps_current": round(cur, 4),
            "eps_90d_ago": round(ago, 4),
            "eps_change_pct": change_pct,
        }
    except Exception:
        return _empty
