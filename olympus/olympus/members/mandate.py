"""Mandate (Phase 3) — the 70/30 core/satellite rule, enforced in-loop.

Target 70% core / 30% satellite. When the satellite drifts PAST the ~35% band, trim it back to
30% and bank the excess into the core. RATCHET-DOWN by default: trim when it overgrows; do NOT
force-feed the satellite when it shrinks (configurable). Returns paper SELL orders; the loop
executes them through the PaperBroker and banks the proceeds into the core.
"""
from __future__ import annotations

from olympus.adapters.execution import Order
from olympus.core import paper_portfolio as PP

TARGET_SATELLITE = 0.30
BAND_UPPER = 0.35
RATCHET_DOWN_ONLY = True   # configurable: trim on overgrowth only; never force-feed on shrink


def check(state: dict, *, ratchet_down_only: bool = RATCHET_DOWN_ONLY,
          target: float = TARGET_SATELLITE, band: float = BAND_UPPER) -> dict:
    sat_frac = PP.satellite_fraction(state)
    total = PP.total_value(state)
    sat_val = PP.satellite_value(state)
    orders, action, excess = [], "none", 0.0

    if sat_frac > band:
        target_val = target * total
        excess = sat_val - target_val
        for t, pos in state["satellite"].items():
            pos_val = pos["shares"] * pos["last_price"]
            sell_shares = round((pos_val * (excess / sat_val)) / pos["last_price"], 6) if sat_val else 0.0
            if sell_shares > 0:
                orders.append(Order(ticker=t, side="SELL", price=pos["last_price"], shares=sell_shares,
                                    reason=f"mandate trim: satellite {sat_frac:.1%} > {band:.0%} band "
                                           f"→ ratchet back to {target:.0%}; bank excess into core"))
        action = "trim"
    elif sat_frac < target:
        action = "below_target_no_action" if ratchet_down_only else "would_force_feed"

    return {"satellite_fraction": round(sat_frac, 4), "target": target, "band_upper": band,
            "action": action, "excess_value": round(excess, 2), "orders": orders,
            "ratchet_down_only": ratchet_down_only}
