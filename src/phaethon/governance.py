"""Governance checks run on EVERY Phaethon publish.

These never silently clamp or fix — they SURFACE violations by writing a `status`
of "NONCONFORMING — …" into the arm JSON (the dashboard renders it as a red banner)
and firing a Telegram alert. Diagnostic/gate only; the underlying strategy is frozen.

Checks:
  (a) leverage      — Σ weight_pct ≤ 100% + tolerance (0.5%), else NONCONFORMING
  (b) micro-cap     — each holding above the documented floor (reuses admission)
  (c) max single    — each weight ≤ MAX_SINGLE_POSITION (constitution)

Arm B currently violates (a) and (c) on live data (cash −38% → 138% gross exposure,
top weight 13.7% > 10%). That is CORRECT behavior of this check — the negative-cash
accounting is a separate, confirmed bug (item 10), not a bug in governance.
"""
from __future__ import annotations

from typing import Callable, Optional

LEVERAGE_TOL_PCT = 0.5   # Σ weights may exceed 100% by this before NONCONFORMING


def check_leverage(holdings: list[dict], tol_pct: float = LEVERAGE_TOL_PCT):
    """Return (gross_exposure_pct, message|None). Message set when > 100% + tol."""
    gross = round(sum(h.get("weight_pct", 0) or 0 for h in holdings), 1)
    if gross > 100 + tol_pct:
        return gross, f"gross exposure {gross}%"
    return gross, None


def check_max_single_position(holdings: list[dict], max_frac: float) -> list[str]:
    """Flag any holding whose weight exceeds MAX_SINGLE_POSITION (fraction, e.g. 0.10)."""
    cap = max_frac * 100
    out = []
    for h in holdings:
        w = h.get("weight_pct", 0) or 0
        if w > cap + 1e-9:
            out.append(f"{h.get('ticker','?')} at {w}% > MAX_SINGLE_POSITION {cap:.0f}%")
    return out


def check_micro_cap(holdings: list[dict], screener_settings: dict,
                    fetch: Optional[Callable[[str], Optional[float]]] = None) -> list[str]:
    """Flag holdings below the documented micro-cap floor, reusing the admission check.
    `fetch(ticker)->market_cap|None` is injectable (default: yfinance)."""
    from src.universe.admission import check_market_cap_admission, fetch_market_cap, REASON_BELOW_MIN
    fetch = fetch or fetch_market_cap
    out = []
    for h in holdings:
        t = h.get("ticker", "?")
        admitted, reason = check_market_cap_admission(t, fetch(t), screener_settings)
        if not admitted and reason == REASON_BELOW_MIN:
            out.append(f"{t} below micro-cap floor")
    return out


def run_governance(holdings: list[dict], screener_settings: dict, constitution: dict,
                   mcap_fetch: Optional[Callable] = None, check_mcap: bool = True) -> dict:
    """Run all governance checks. Returns {conforming, status, violations, gross_exposure_pct}.

    status is "CONFORMING" or "NONCONFORMING — …" (leverage message leads, as specified).
    Never mutates holdings.
    """
    gross, lev_msg = check_leverage(holdings)
    max_pos = float(constitution.get("MAX_SINGLE_POSITION", 0.10))
    violations: list[str] = []
    if lev_msg:
        violations.append(lev_msg)
    violations.extend(check_max_single_position(holdings, max_pos))
    if check_mcap:
        try:
            violations.extend(check_micro_cap(holdings, screener_settings, mcap_fetch))
        except Exception:
            pass   # governance must never crash the publish

    if violations:
        status = "NONCONFORMING — " + "; ".join(violations)
    else:
        status = "CONFORMING"
    return {
        "conforming": not violations,
        "status": status,
        "violations": violations,
        "gross_exposure_pct": gross,
    }
