"""Extraction invariants — cross-check EDGAR-extracted fundamentals vs yfinance.

Pure functions. Each invariant returns a list of violation dicts:
    {ticker, check, extracted, reference, severity}

THRESHOLDS ARE CARRIED OVER UNCHANGED FROM THE ORIGINAL BUG REPORTS (see
KNOWN_BUGS.md: BUG-002/003/004/005/006). They were NOT re-chosen to make the
current 60-name universe pass — if a live invariant fires, that is a finding to
report, not a threshold to loosen.
"""
from __future__ import annotations

from typing import Optional

SEV_HIGH = "SEV_HIGH"
SEV_MED = "SEV_MED"

# ── thresholds (sourced from KNOWN_BUGS.md bug reports — do not re-fit) ──
REVENUE_TOL = 0.15            # BUG-004/006: revenue mismatch drove EBITDA/PT errors
GROSS_MARGIN_MIN = 0.0        # BUG-006: negative/zero GM is a broken extraction
GROSS_MARGIN_MAX = 0.90      # BUG-006: UNH-class gp inflation hit 88.7% GM
OP_MARGIN_DIFF_PP = 0.10     # 10 percentage points vs yfinance operatingMargins
SHARES_TOL = 0.10            # BUG-002: share count drove per-share PT explosion
NET_DEBT_TOL = 0.25          # BUG-003: equity-bridge / net-debt sensitivity
UNIT_MIN, UNIT_MAX = 1e6, 1e13   # BUG-002: dollars-vs-$mm unit magnitude
PT_RATIO_MIN, PT_RATIO_MAX = 0.2, 3.0   # BUG-002/005: price target vs current price

_MONETARY_FIELDS = ["revenue", "cost_of_revenue", "gross_profit", "operating_income"]


def _pct_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b)


def _v(ticker, check, extracted, reference, severity) -> dict:
    return {"ticker": ticker, "check": check, "extracted": extracted,
            "reference": reference, "severity": severity}


def check_revenue(ticker, extracted, reference) -> list[dict]:
    d = _pct_diff(extracted.get("revenue"), reference.get("totalRevenue"))
    if d is not None and d > REVENUE_TOL:
        return [_v(ticker, "revenue_vs_yfinance", extracted.get("revenue"),
                   reference.get("totalRevenue"), SEV_HIGH)]
    return []


def check_margins(ticker, extracted, reference) -> list[dict]:
    out: list[dict] = []
    rev = extracted.get("revenue")
    gp = extracted.get("gross_profit")
    oi = extracted.get("operating_income")
    if rev and gp is not None:
        gm = gp / rev
        if not (GROSS_MARGIN_MIN < gm < GROSS_MARGIN_MAX):
            out.append(_v(ticker, "gross_margin_out_of_range", round(gm, 4),
                          f"(>{GROSS_MARGIN_MIN}, <{GROSS_MARGIN_MAX})", SEV_HIGH))
    if rev and gp is not None and oi is not None:
        gm, om = gp / rev, oi / rev
        if om >= gm:
            out.append(_v(ticker, "op_margin_ge_gross_margin", round(om, 4),
                          round(gm, 4), SEV_MED))
    ref_om = reference.get("operatingMargins")
    if rev and oi is not None and ref_om is not None:
        om = oi / rev
        if abs(om - ref_om) > OP_MARGIN_DIFF_PP:
            out.append(_v(ticker, "op_margin_vs_yfinance", round(om, 4),
                          round(ref_om, 4), SEV_MED))
    return out


def check_shares(ticker, extracted, reference) -> list[dict]:
    d = _pct_diff(extracted.get("shares"), reference.get("sharesOutstanding"))
    if d is not None and d > SHARES_TOL:
        return [_v(ticker, "shares_vs_yfinance", extracted.get("shares"),
                   reference.get("sharesOutstanding"), SEV_HIGH)]
    return []


def check_net_debt(ticker, extracted, reference) -> list[dict]:
    ext = extracted.get("net_debt")
    td, tc = reference.get("totalDebt"), reference.get("totalCash")
    if ext is None or td is None or tc is None:
        return []
    ref_nd = td - tc
    d = _pct_diff(ext, ref_nd)
    if d is not None and d > NET_DEBT_TOL:
        return [_v(ticker, "net_debt_vs_yfinance", ext, ref_nd, SEV_MED)]
    return []


def check_unit_magnitude(ticker, extracted, reference) -> list[dict]:
    out = []
    for field in _MONETARY_FIELDS:
        val = extracted.get(field)
        if val is None or val == 0:
            continue
        if not (UNIT_MIN <= abs(val) <= UNIT_MAX):
            out.append(_v(ticker, f"unit_magnitude_{field}", val,
                          f"[{UNIT_MIN:.0e}, {UNIT_MAX:.0e}]", SEV_HIGH))
    return out


def check_price_target(ticker, extracted, reference) -> list[dict]:
    pt, price = extracted.get("price_target"), extracted.get("current_price")
    if pt is None or not price:
        return []
    ratio = abs(pt / price)
    if not (PT_RATIO_MIN <= ratio <= PT_RATIO_MAX):
        return [_v(ticker, "price_target_vs_price_ratio", round(ratio, 3),
                   f"[{PT_RATIO_MIN}, {PT_RATIO_MAX}]", SEV_HIGH)]
    return []


_CHECKS = [check_revenue, check_margins, check_shares, check_net_debt,
           check_unit_magnitude, check_price_target]


def run_invariants(ticker: str, extracted: dict, reference: dict) -> list[dict]:
    """Run every invariant for one ticker; return all violations (possibly empty)."""
    out: list[dict] = []
    for fn in _CHECKS:
        out.extend(fn(ticker, extracted, reference))
    return out
