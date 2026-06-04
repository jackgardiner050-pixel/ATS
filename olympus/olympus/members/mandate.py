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
from olympus.preregistration.spec import load_spec

TARGET_SATELLITE = 0.30
BAND_UPPER = 0.35
RATCHET_DOWN_ONLY = True   # configurable: trim on overgrowth only; never force-feed on shrink
# conviction → size mapping: at the Actionable bar use the band floor (smallest), at 85+ the ceiling
_CONV_FLOOR, _CONV_CEIL = ACTIONABLE_CONVICTION, 85

# v2 growth discipline thresholds — read from the LOCKED growth_mandate_v1 pre-registration
_GROWTH = load_spec("growth_mandate_v1")
_HARVEST = _GROWTH["harvest_into_core"]
_EXIT = _GROWTH["exit_thesis_break"]


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


def _gain_pct(pos: dict) -> float | None:
    cb = pos.get("cost_basis")
    return ((pos["last_price"] / cb - 1) * 100) if (cb and cb > 0) else None


def harvest_plan(state: dict, *, run_hard_gain_pct: float = float(_HARVEST["run_hard_gain_pct"]),
                 harvest_fraction: float = float(_HARVEST["harvest_fraction"]),
                 max_single: float = MAX_SINGLE, band_drift_trim: bool = bool(_HARVEST["band_drift_trim"])) -> dict:
    """HARVEST-INTO-CORE (ride → harvest → compound). Trim a winner that has RUN HARD (>= the
    run-hard gain) or DRIFTED past its single-name band, banking the proceeds into the safe core.
    Returns paper SELL orders; the loop executes them and banks the proceeds.
    """
    total = PP.total_value(state)
    orders, per = [], []
    for t, pos in list(state["satellite"].items()):
        gain = _gain_pct(pos)
        pos_val = pos["shares"] * pos["last_price"]
        weight = (pos_val / total) if total > 0 else 0.0
        run_hard = gain is not None and gain >= run_hard_gain_pct
        over_band = band_drift_trim and weight > max_single
        if not (run_hard or over_band):
            continue
        # harvest a fraction on a run-hard trigger; if over-band, also trim back toward the cap
        sell_shares = round(pos["shares"] * harvest_fraction, 6)
        if over_band:
            trim_to_cap = round((pos_val - max_single * total) / pos["last_price"], 6)
            sell_shares = max(sell_shares, trim_to_cap)
        sell_shares = min(round(sell_shares, 6), pos["shares"])
        if sell_shares <= 0:
            continue
        reason = (f"harvest-into-core: {t} " + (f"run hard +{gain:.0f}% " if run_hard else "") +
                  (f"(band drift {weight:.1%}>{max_single:.0%}) " if over_band else "") +
                  f"→ trim {harvest_fraction:.0%}, bank into core")
        orders.append(Order(ticker=t, side="SELL", price=pos["last_price"], shares=sell_shares, reason=reason))
        per.append({"ticker": t, "gain_pct": round(gain, 1) if gain is not None else None,
                    "weight": round(weight, 4), "run_hard": run_hard, "over_band": over_band,
                    "trim_shares": sell_shares})
    return {"orders": orders, "n_harvests": len(orders), "per_position": per,
            "reason": "harvested winners into core" if orders else "no winner at the harvest trigger"}


def exit_plan(state: dict, theses_by_ticker: dict | None = None, *,
              profit_take_pct: float = float(_EXIT["profit_take_pct"]),
              profit_take_fraction: float = float(_EXIT["profit_take_fraction"]),
              drawdown_pct: float = float(_EXIT["momentum_break_drawdown_pct"])) -> dict:
    """TIGHT EXIT / THESIS-BREAK — HYBRID (pre-registered thresholds). EXIT a held name when its
    growth thesis BREAKS (durability flips to peaking/hype, or growth decelerates, or momentum rolls
    over) OR it has fallen >= drawdown_pct from its post-entry high (momentum-break); TRIM on a big
    profit-take. SELL orders only (proceeds banked into core by the loop).
    """
    theses = theses_by_ticker or {}
    orders, per = [], []
    for t, pos in list(state["satellite"].items()):
        th = theses.get(t) or {}
        durab = str(th.get("growth_durability", "")).lower()
        trend = str(th.get("growth_trend", "")).lower()
        mom = str(th.get("momentum_state", "")).lower()
        thesis_break = durab in ("peaking", "hype") or trend == "decelerating" or mom == "rolling_over"
        high = pos.get("high") or pos.get("last_price")
        drawdown = ((high - pos["last_price"]) / high * 100) if high else 0.0
        momentum_break = drawdown >= drawdown_pct
        gain = _gain_pct(pos)
        profit_take = gain is not None and gain >= profit_take_pct

        if thesis_break or momentum_break:
            shares = pos["shares"]                                    # FULL exit on a broken thesis
            why = ("thesis-break (" + ", ".join(
                       [x for x in [("durability " + durab) if durab in ("peaking", "hype") else "",
                                    "growth decelerating" if trend == "decelerating" else "",
                                    "momentum rolled over" if mom == "rolling_over" else ""] if x]) + ")"
                   ) if thesis_break else f"momentum-break (-{drawdown:.0f}% from high)"
            orders.append(Order(t, "SELL", price=pos["last_price"], shares=round(shares, 6),
                                reason=f"EXIT {t}: {why}"))
            per.append({"ticker": t, "action": "EXIT", "why": why,
                        "gain_pct": round(gain, 1) if gain is not None else None})
        elif profit_take:
            shares = round(pos["shares"] * profit_take_fraction, 6)
            orders.append(Order(t, "SELL", price=pos["last_price"], shares=shares,
                                reason=f"profit-take {t}: +{gain:.0f}% ≥ {profit_take_pct:.0f}% → trim "
                                       f"{profit_take_fraction:.0%}"))
            per.append({"ticker": t, "action": "TRIM", "why": f"profit-take +{gain:.0f}%",
                        "gain_pct": round(gain, 1)})
    return {"orders": orders, "n_exits": sum(1 for p in per if p["action"] == "EXIT"),
            "n_trims": sum(1 for p in per if p["action"] == "TRIM"), "per_position": per,
            "reason": "exited/trimmed on thesis or momentum break" if orders else "no exit/profit-take triggered"}


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
