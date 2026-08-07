"""Phaethon constitutional trim — reduce over-cap holdings to MAX_SINGLE_POSITION.

Mechanical enforcement on an EXISTING book, operator-invoked (NOT part of the frozen
daily publish path — governance.py stays diagnostic-only there, per its own docstring).
For each holding whose weight_pct exceeds the cap, reduce it to exactly the cap and
release the excess as cash. Never redistributes the released amount into other
positions — that is a separate, later cash-deployment feature, not this one.
"""
from __future__ import annotations


def trim_to_cap(holdings: list[dict], cap: float = 0.10) -> tuple[list[dict], float, list[dict]]:
    """Trim each holding whose weight_pct exceeds `cap` (a fraction, e.g. 0.10 = 10%)
    down to exactly cap*100. Pure function — does not mutate the input list/dicts.

    Each holding must have at least {'ticker': str, 'weight_pct': number}, where
    weight_pct is already expressed as a percentage of the WHOLE portfolio (cash
    included) — the same units src.phaethon.scorecard.holdings_view produces.

    Returns (trimmed_holdings, released_cash_pct, trim_log):
      trimmed_holdings  — new list; over-cap weight_pct reduced to cap*100, every other
                           key (ticker, bought_at, last, ...) carried through unchanged.
      released_cash_pct — sum of (before - cap*100) across all trimmed positions, in the
                           same weight_pct units (percentage points of the whole book).
      trim_log          — one entry per trimmed position: ticker, before_pct, after_pct,
                           released_pct.
    """
    cap_pct = round(cap * 100, 10)
    trimmed: list[dict] = []
    trim_log: list[dict] = []
    released = 0.0
    for h in holdings:
        w = h.get("weight_pct", 0) or 0
        if w > cap_pct + 1e-9:
            released_pct = w - cap_pct
            trim_log.append({
                "ticker": h.get("ticker", "?"),
                "before_pct": w,
                "after_pct": cap_pct,
                "released_pct": round(released_pct, 6),
            })
            released += released_pct
            trimmed.append({**h, "weight_pct": cap_pct})
        else:
            trimmed.append(dict(h))
    return trimmed, round(released, 6), trim_log
