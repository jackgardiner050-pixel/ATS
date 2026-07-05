"""Per-ticker market-cap admission — enforce the documented screener size band.

config/settings.yaml has long defined screener.min_market_cap_usd (500M) and
max_market_cap_usd (200B), but no code read them. This module admits/excludes a
ticker BEFORE it reaches the rating or paper stages.

Diagnostic / gate only: it decides admission, it never modifies ratings,
positions, or trades. Thresholds are read from settings (the locked config) —
this module chooses no new numbers of its own.
"""
from __future__ import annotations

from typing import Optional, Tuple

# Exclusion / flag reasons (stable strings — surfaced in run summary.json)
REASON_BELOW_MIN = "below_min_market_cap"
REASON_ABOVE_MAX = "above_max_market_cap"
REASON_UNVERIFIED = "mcap_unverified"


def _coerce_usd(value) -> float:
    """Coerce a settings value to float, tolerating YAML underscore separators
    that some loaders return as strings (e.g. '500_000_000')."""
    if isinstance(value, str):
        value = value.replace("_", "").strip()
    return float(value)


def check_market_cap_admission(
    ticker: str,
    market_cap: Optional[float],
    settings: dict,
) -> Tuple[bool, Optional[str]]:
    """Return (admitted, reason) for a ticker given its market cap.

    `settings` is the screener settings dict; it MUST contain both
    min_market_cap_usd and max_market_cap_usd or a ValueError is raised (a missing
    floor must fail loudly, never silently admit everything).

    - market_cap None or <= 0  → admitted, reason="mcap_unverified" (admit + flag)
    - market_cap < floor        → NOT admitted, reason="below_min_market_cap"
    - market_cap > cap          → NOT admitted, reason="above_max_market_cap"
    - otherwise                 → admitted, reason=None
    """
    if "min_market_cap_usd" not in settings or "max_market_cap_usd" not in settings:
        raise ValueError(
            "settings missing min_market_cap_usd / max_market_cap_usd — "
            "cannot enforce the market-cap admission band"
        )
    floor = _coerce_usd(settings["min_market_cap_usd"])
    cap = _coerce_usd(settings["max_market_cap_usd"])

    if market_cap is None or float(market_cap) <= 0:
        return True, REASON_UNVERIFIED

    mc = float(market_cap)
    if mc < floor:
        return False, REASON_BELOW_MIN
    if mc > cap:
        return False, REASON_ABOVE_MAX
    return True, None


def fetch_market_cap(ticker: str) -> Optional[float]:
    """yfinance marketCap, mirroring src/data/peer_multiples.fetch_peer_market_data.
    Returns None on any failure (→ mcap_unverified, admitted with a flag)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker.upper()).info or {}
        mc = info.get("marketCap")
        return float(mc) if mc and mc > 0 else None
    except Exception:
        return None
