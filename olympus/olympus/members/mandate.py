"""Mandate (Phase 3) — the 70/30 core/satellite rule, enforced in-loop.

Target 70% core / 30% satellite. When the satellite drifts PAST the ~35% band, trim it back to
30% and bank the excess into the core. RATCHET-DOWN by default: trim when it overgrows; do NOT
force-feed the satellite when it shrinks (configurable). Returns paper SELL orders; the loop
executes them through the PaperBroker and banks the proceeds into the core.
"""
from __future__ import annotations

from olympus.adapters.execution import Order
from olympus.core import paper_portfolio as PP
from olympus.core.constants import MAX_INITIAL, MAX_SINGLE, ACTIONABLE_CONVICTION

TARGET_SATELLITE = 0.30
BAND_UPPER = 0.35
RATCHET_DOWN_ONLY = True   # configurable: trim on overgrowth only; never force-feed on shrink
# conviction → size mapping: at the Actionable bar use the band floor (smallest), at 85+ the ceiling
_CONV_FLOOR, _CONV_CEIL = ACTIONABLE_CONVICTION, 85


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def deploy_plan(state: dict, buy_candidates: list[dict], *, target: float = TARGET_SATELLITE,
                max_initial: float = MAX_INITIAL, max_single: float = MAX_SINGLE) -> dict:
    """When the satellite is BELOW target, plan conviction-ranked BUYs that deploy TOWARD — but
    never force to — the target. Each `buy_candidate` = {ticker, conviction, price, band_lo, band_hi}.

    Honest: deploy only what conviction supports. Size each by conviction within its band; cap at
    max_initial / max_single; stop at the target. If candidates are weak/few, the book stays UNDER
    target — that gap is reported, not papered over. Never inflate conviction to justify a buy.
    """
    total = PP.total_value(state)
    cur = PP.satellite_fraction(state)
    if cur >= target or not buy_candidates:
        return {"orders": [], "deployed_value": 0.0, "target": target,
                "satellite_fraction_before": round(cur, 4), "satellite_fraction_planned": round(cur, 4),
                "gap_to_target": round(max(0.0, target - cur), 4), "under_deployed": cur < target,
                "per_position": [],
                "reason": "already at/above target" if cur >= target
                          else "no buy-worthy candidates — UNDER-DEPLOYED, not forced"}
    room_value = (target - cur) * total
    orders, per, deployed = [], [], 0.0
    for c in sorted(buy_candidates, key=lambda x: -x["conviction"]):
        if deployed >= room_value:
            break
        price = c.get("price")
        if not price or price <= 0:
            continue
        lo, hi = c["band_lo"], min(c["band_hi"], max_single)
        # conviction-weighted size within the band; capped by the initial cap and remaining room
        frac = lo + (hi - lo) * _clamp01((c["conviction"] - _CONV_FLOOR) / (_CONV_CEIL - _CONV_FLOOR))
        frac = min(frac, max_initial, max_single)
        size_value = min(frac * total, room_value - deployed)   # deploy TOWARD target; don't exceed it
        if size_value <= 0:
            continue
        orders.append(Order(c["ticker"], "BUY", price=price, dollars=round(size_value, 2),
                            reason=f"deploy-toward-target: conviction {c['conviction']} → "
                                   f"{size_value/total:.1%} (toward {target:.0%}, not forced)"))
        deployed += size_value
        per.append({"ticker": c["ticker"], "conviction": c["conviction"],
                    "size_frac": round(size_value / total, 4)})
    planned = cur + deployed / total
    return {"orders": orders, "deployed_value": round(deployed, 2), "target": target,
            "satellite_fraction_before": round(cur, 4), "satellite_fraction_planned": round(planned, 4),
            "gap_to_target": round(max(0.0, target - planned), 4),
            "under_deployed": planned < target - 0.01, "per_position": per,
            "reason": "deployed toward target by conviction" if orders else "no buy-worthy candidates — UNDER-DEPLOYED"}


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
