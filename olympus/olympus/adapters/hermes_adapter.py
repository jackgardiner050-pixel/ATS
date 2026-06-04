"""Hermes adapter (§4.7) — prepare a human-readable execution PATHWAY, never an order.

Wraps the existing v3 execution lab (~/trading/hermes_v3_lab) in spirit: for the MVP, Hermes
only prepares the pathway (instrument, proposed size, staged entry, review date, break
conditions). It does NOT connect to a broker and does NOT place trades. The v3 lab's friction
model is where expected-cost estimates would plug in (referenced, not invoked here).
"""
from __future__ import annotations


def pathway(thesis: dict, allocation) -> str:
    ticker = thesis["ticker"]
    if allocation.initial_allocation <= 0:
        action = (f"No new position. Decision is to MANAGE/HOLD existing exposure only "
                  f"(initial size 0%). " if thesis["bias"] != "BUY"
                  else "No position — size collapsed to 0% by the limits/survivability gates. ")
    else:
        action = (f"Stage into {ticker} up to {allocation.initial_allocation:.0%} initial / "
                  f"{allocation.target_allocation:.0%} target (max {allocation.max_allocation:.0%}). ")
    lines = [
        f"Instrument: {ticker} (single name, paper).",
        action.strip(),
        f"Review by: {thesis.get('review_by', 'n/a')}.",
        f"Thesis break: {thesis.get('invalidation', 'n/a')}.",
        "Expected costs: (v3 friction model plugs in here; not computed in MVP slice).",
        "",
        "**This is not an order. No trade has been placed. Human authorisation is required.**",
    ]
    return "\n".join(lines)
