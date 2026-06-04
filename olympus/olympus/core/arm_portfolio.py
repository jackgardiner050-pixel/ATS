"""Per-arm paper books (v2) — one paper/simulated portfolio per growth arm (A/B/C).

Each arm keeps its OWN book so the arms can be scored independently and against each other. The
portfolio MATH is reused from `paper_portfolio` (it operates on a plain state dict); only load/
save/reset are per-arm (a separate gitignored JSON file each). Paper/simulated only.
"""
from __future__ import annotations

import json
from datetime import date

from olympus.core import config
from olympus.core import paper_portfolio as PP

# reuse the pure state math (path-independent)
satellite_value = PP.satellite_value
total_value = PP.total_value
satellite_fraction = PP.satellite_fraction
apply_fill = PP.apply_fill


def state_path(arm_id: str):
    return config.DATA_DIR / f"arm_{arm_id}_portfolio.json"


def reset_to_cash(arm_id: str, notional: float = 10000.0) -> dict:
    """Start an arm's book at all-cash (satellite empty → deploy-toward-target has room)."""
    state = {"mode": "paper/simulated", "arm": arm_id, "as_of": date.today().isoformat(),
             "core_value": float(notional), "cash": 0.0, "satellite": {}}
    save(arm_id, state)
    return state


def load(arm_id: str, notional: float = 10000.0) -> dict:
    p = state_path(arm_id)
    if not p.exists():
        return reset_to_cash(arm_id, notional)
    return json.loads(p.read_text())


def save(arm_id: str, state: dict) -> None:
    state.setdefault("mode", "paper/simulated")
    state["arm"] = arm_id
    state_path(arm_id).write_text(json.dumps(state, indent=2))
