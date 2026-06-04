"""Naive technical/momentum screener (Phase 4) — the WALLED-OFF benchmark track.

A simple VCP-style trend/momentum screen on FREE data: uptrend (close > MA50 > MA200), relative
strength (3-month return), and volatility contraction (recent ATR/price < trailing ATR/price).
It produces its own picks each run and records them to a separate, firewalled ledger.

HARD FIREWALL: this module is imported ONLY by the scorecard (to MEASURE against it) and the CLI.
It is NEVER imported by Oracle / Athena-Nemesis / Hecate / Tyche / Zeus / the loop. Its picks must
not influence any decision. Fail loud if data is missing — never silently skip a name.
Paper/advisory only.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from olympus.core import storage

# Fixed, decision-independent universe (liquid momentum names). NOT derived from Oracle/decisions.
UNIVERSE = ["NVDA", "AAPL", "MSFT", "AMD", "AVGO", "META", "GOOGL", "AMZN", "TSLA", "NFLX", "CRM", "ORCL"]
ROUND_TRIP_COST_PCT = 0.20   # flat net-of-cost haircut applied when measuring screener picks


class ScreenerDataError(RuntimeError):
    """Raised when required price data is missing — fail loud, never silently drop a name."""


def _default_price_fn(ticker: str):
    import yfinance as yf
    h = yf.Ticker(ticker).history(period="1y")
    if h is None or len(h) < 200:
        raise ScreenerDataError(f"insufficient price history for {ticker} (need >=200 daily bars)")
    return h


def _signal(h) -> Optional[dict]:
    close = h["Close"].dropna()
    if len(close) < 200:
        raise ScreenerDataError("series too short after dropna (need >=200 bars)")
    ma50, ma200 = close.tail(50).mean(), close.tail(200).mean()
    px = float(close.iloc[-1])
    rs_3m = float(close.iloc[-1] / close.iloc[-63] - 1) * 100 if len(close) >= 63 else 0.0
    # volatility contraction (VCP proxy): recent 20d vs trailing 50d daily-range volatility
    rng = (h["High"] - h["Low"]) / h["Close"]
    vol_recent, vol_trailing = float(rng.tail(20).mean()), float(rng.tail(50).mean())
    contracting = vol_recent < vol_trailing
    uptrend = px > ma50 > ma200
    qualifies = bool(uptrend and contracting and rs_3m > 0)
    return {"price": round(px, 4), "rs_3m_pct": round(rs_3m, 2), "uptrend": uptrend,
            "contracting": contracting, "qualifies": qualifies}


def screen(universe: list[str] = None, top_n: int = 3,
           price_fn: Callable = _default_price_fn) -> list[dict]:
    universe = universe or UNIVERSE
    scored = []
    for t in universe:
        h = price_fn(t)                       # raises ScreenerDataError on missing data (fail loud)
        sig = _signal(h)
        if sig and sig["qualifies"]:
            scored.append({"ticker": t, **sig})
    scored.sort(key=lambda s: -s["rs_3m_pct"])
    return scored[:top_n]


def _acwi_anchor() -> Optional[float]:
    try:
        import yfinance as yf
        h = yf.Ticker("ACWI").history(period="5d")
        return round(float(h["Close"].dropna().iloc[-1]), 4) if len(h) else None
    except Exception:
        return None


def run_and_record(price_fn: Callable = _default_price_fn) -> list[dict]:
    picks = screen(price_fn=price_fn)
    today = date.today().isoformat()
    acwi = _acwi_anchor()      # benchmark anchor stamped at pick time → screener vs passive later
    for p in picks:
        storage.append_screener_pick({**p, "entry_date": today, "acwi_anchor": acwi,
                                      "net_cost_haircut_pct": ROUND_TRIP_COST_PCT,
                                      "mode": "paper/advisory"}, ticker=p["ticker"])
    return picks
