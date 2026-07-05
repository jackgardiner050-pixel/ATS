"""Adaptive cadence state tracking for the universe screener.

Cadence is purely mechanical — intervals are fixed by the table below and
never modified based on realised P&L or rating outcomes.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml

from src.io_utils import atomic_write_text

STATE_PATH = Path(__file__).parent.parent / "data" / "screen_state.yaml"

# Cadence table: (rating, confidence) → interval in days
# UNKNOWN treated the same as MED throughout
_CADENCE_DAYS: dict[tuple[str, str], int] = {
    ("STRONG_BUY",  "HIGH"):    7,
    ("STRONG_BUY",  "MED"):     7,
    ("STRONG_BUY",  "LOW"):     7,
    ("STRONG_BUY",  "UNKNOWN"): 7,
    ("BUY",         "HIGH"):    7,
    ("BUY",         "MED"):     7,
    ("BUY",         "LOW"):     7,
    ("BUY",         "UNKNOWN"): 7,
    ("HOLD",        "HIGH"):   28,
    ("HOLD",        "MED"):    14,
    ("HOLD",        "LOW"):    14,
    ("HOLD",        "UNKNOWN"):14,
    ("SELL",        "HIGH"):   28,
    ("SELL",        "MED"):    28,
    ("SELL",        "LOW"):    28,
    ("SELL",        "UNKNOWN"):28,
    ("STRONG_SELL", "HIGH"):   56,
    ("STRONG_SELL", "MED"):    42,
    ("STRONG_SELL", "LOW"):    14,
    ("STRONG_SELL", "UNKNOWN"):42,
    ("BROKEN",      "HIGH"):   28,
    ("BROKEN",      "MED"):    28,
    ("BROKEN",      "LOW"):    28,
    ("BROKEN",      "UNKNOWN"):28,
}


def load_state(path: Optional[Path] = None) -> dict[str, dict]:
    """Load screen_state.yaml → {TICKER: record_dict}."""
    p = path or STATE_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    records = raw.get("state") or []
    return {r["ticker"]: r for r in records if "ticker" in r}


def save_state(state: dict[str, dict], path: Optional[Path] = None) -> None:
    """Persist state dict to screen_state.yaml."""
    p = path or STATE_PATH
    records = sorted(state.values(), key=lambda r: r.get("ticker", ""))
    text = yaml.dump({"state": records}, default_flow_style=False, sort_keys=False)
    atomic_write_text(p, text)


def compute_next_due(rating: str, confidence: str, last_screen_date: date) -> date:
    """Return the date on which this ticker should next be screened."""
    rat = (rating or "BROKEN").upper()
    conf = (confidence or "UNKNOWN").upper()
    if conf not in ("HIGH", "MED", "LOW", "UNKNOWN"):
        conf = "UNKNOWN"
    days = _CADENCE_DAYS.get((rat, conf), 28)
    return last_screen_date + timedelta(days=days)


def _earnings_within_window(ticker: str, today: date, window_days: int = 7) -> bool:
    """True if next known earnings date is within window_days calendar days of today.

    7 calendar days ≈ 5 trading days. Fails silently → False so the screener
    is never blocked by a yfinance outage.
    """
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return False
        next_earn = None
        if hasattr(cal, "columns"):
            # DataFrame (older yfinance)
            col = next((c for c in cal.columns if "Earnings" in str(c)), None)
            if col is not None:
                vals = cal[col].dropna()
                if not vals.empty:
                    next_earn = vals.iloc[0]
        elif isinstance(cal, dict):
            raw = cal.get("Earnings Date") or cal.get("earningsDate")
            if raw:
                next_earn = raw[0] if isinstance(raw, (list, tuple)) else raw
        if next_earn is None:
            return False
        earn_date = next_earn.date() if hasattr(next_earn, "date") else date.fromisoformat(str(next_earn)[:10])
        return 0 <= (earn_date - today).days <= window_days
    except Exception:
        return False


def is_due(
    ticker: str,
    today: date,
    state: Optional[dict[str, dict]] = None,
    path: Optional[Path] = None,
    _earnings_override: Optional[bool] = None,
) -> bool:
    """Return True if ticker should be screened today.

    _earnings_override is a test-injection hook; pass True/False to skip the
    yfinance call in unit tests.
    """
    if state is None:
        state = load_state(path)
    record = state.get(ticker.upper())

    if record is None:
        return True

    if record.get("force_rescreen", False):
        return True

    next_due_raw = record.get("next_due_date")
    if not next_due_raw:
        return True
    next_due = date.fromisoformat(str(next_due_raw))
    if today >= next_due:
        return True

    # Earnings override (skip yfinance in tests via _earnings_override)
    if _earnings_override is not None:
        return _earnings_override
    if _earnings_within_window(ticker, today):
        return True

    return False


def update_state(
    ticker: str,
    result: dict,
    state: Optional[dict[str, dict]] = None,
    path: Optional[Path] = None,
    today: Optional[date] = None,
) -> dict[str, dict]:
    """Write a post-run record for ticker into state. Returns updated state dict."""
    if state is None:
        state = load_state(path)
    if today is None:
        today = date.today()

    t = ticker.upper()
    rating = (result.get("rating") or "BROKEN").upper()
    confidence = (result.get("confidence") or "UNKNOWN").upper()

    earnings_date_next = None
    try:
        import yfinance as yf
        cal = yf.Ticker(t).calendar
        if cal is not None:
            if hasattr(cal, "columns"):
                col = next((c for c in cal.columns if "Earnings" in str(c)), None)
                if col:
                    vals = cal[col].dropna()
                    if not vals.empty:
                        ev = vals.iloc[0]
                        earnings_date_next = str(ev.date() if hasattr(ev, "date") else ev)[:10]
            elif isinstance(cal, dict):
                raw = cal.get("Earnings Date") or cal.get("earningsDate")
                if raw:
                    ev = raw[0] if isinstance(raw, (list, tuple)) else raw
                    earnings_date_next = str(ev.date() if hasattr(ev, "date") else ev)[:10]
    except Exception:
        pass

    next_due = compute_next_due(rating, confidence, today)

    state[t] = {
        "ticker": t,
        "last_screen_date": str(today),
        "last_rating": rating,
        "last_confidence": confidence,
        "last_pt": float(result.get("price_target_12m") or 0),
        "last_expected_return": float(result.get("expected_return") or 0),
        "next_due_date": str(next_due),
        "earnings_date_next": earnings_date_next,
        "force_rescreen": False,
        "notes": "",
    }

    save_state(state, path)
    return state


def apply_force(
    tickers: list[str],
    state: Optional[dict[str, dict]] = None,
    path: Optional[Path] = None,
) -> dict[str, dict]:
    """Set force_rescreen=True for the given tickers.

    Pass an empty list or ["*"] to force every ticker already in state.
    Returns the updated state dict.
    """
    if state is None:
        state = load_state(path)

    targets = list(state.keys()) if (not tickers or tickers == ["*"]) else [t.upper() for t in tickers]

    for t in targets:
        if t in state:
            state[t]["force_rescreen"] = True
        else:
            state[t] = {
                "ticker": t,
                "last_screen_date": None,
                "last_rating": None,
                "last_confidence": None,
                "last_pt": None,
                "last_expected_return": None,
                "next_due_date": None,
                "earnings_date_next": None,
                "force_rescreen": True,
                "notes": "force-applied before first screen",
            }

    save_state(state, path)
    return state
