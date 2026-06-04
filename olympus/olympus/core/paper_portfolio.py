"""Paper portfolio state the autonomous loop manages (paper/simulated only).

Tracks the 70/30 core/satellite split the mandate enforces. Single JSON file under data/
(gitignored). Seeded over-band so the mandate trim demonstrably fires; in normal operation the
loop updates last_price from live data and applies fills.
"""
from __future__ import annotations

import json
from datetime import date

from olympus.core import config

STATE = config.DATA_DIR / "paper_portfolio.json"

_SEED = {
    "mode": "paper/simulated",
    "as_of": date(2026, 6, 4).isoformat(),
    "core_value": 70000.0,          # the passive core the satellite banks excess into
    "cash": 0.0,
    "satellite": {                  # seeded so satellite has drifted PAST the 35% band
        "VRT":  {"shares": 80.0,  "last_price": 334.0, "cost_basis": 316.0},
        "SMCI": {"shares": 300.0, "last_price": 50.0,  "cost_basis": 42.0},
    },
}


def load() -> dict:
    if not STATE.exists():
        save(dict(_SEED))
    return json.loads(STATE.read_text())


def save(state: dict) -> None:
    state.setdefault("mode", "paper/simulated")
    STATE.write_text(json.dumps(state, indent=2))


def satellite_value(state: dict) -> float:
    return sum(p["shares"] * p["last_price"] for p in state["satellite"].values())


def total_value(state: dict) -> float:
    return state["core_value"] + state["cash"] + satellite_value(state)


def satellite_fraction(state: dict) -> float:
    tot = total_value(state)
    return (satellite_value(state) / tot) if tot > 0 else 0.0


def apply_fill(state: dict, fill: dict) -> None:
    """Apply a paper Fill to the satellite + cash (and bank trims into the core)."""
    t, sat = fill["ticker"], state["satellite"]
    if fill["side"] == "BUY":
        pos = sat.setdefault(t, {"shares": 0.0, "last_price": fill["fill_price"], "cost_basis": fill["fill_price"]})
        pos["shares"] += fill["shares"]
        pos["last_price"] = fill["fill_price"]
        state["cash"] += fill["net_dollars"]            # negative
    elif fill["side"] == "SELL":
        pos = sat.get(t)
        if pos:
            pos["shares"] = round(pos["shares"] - fill["shares"], 6)
            pos["last_price"] = fill["fill_price"]
            if pos["shares"] <= 1e-6:
                sat.pop(t, None)
        state["cash"] += fill["net_dollars"]            # positive proceeds
