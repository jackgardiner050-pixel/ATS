"""Gaia rebalancing + glidepath — PRE-REGISTERED, LOCKED, mechanical DISCIPLINE (never condition-timing).

Two rules, both rules-based and horizon/calendar-driven (NOT market-condition driven):
  • Rebalancing — when any sleeve drifts > band_pp from its target weight, trim/top-up back to target,
    checked on a fixed schedule (monthly). Discipline, not timing. Tax-free inside an ISA.
  • Glidepath — lower the target risk-tier over time as the horizon shortens, driven by age/milestones
    via a configurable date→tier schedule. DEFAULT OFF (hold the current aggressive tier).

The parameters live in the LOCKED rules.yaml and are hash-verified (no silent tuning to flatter). All
paper/research; no personal data here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
RULES = _HERE / "rules.yaml"


def load_rules() -> dict:
    return yaml.safe_load(RULES.read_text())


def _canonical(rules: dict) -> str:
    """Canonical JSON of the locked PARAMS (the numeric/structural values that must not be tuned to
    flatter) — excludes descriptive notes and the lock hash itself."""
    rb, gp = rules["rebalancing"], rules["glidepath"]
    params = {"band_pp": rb["band_pp"], "schedule": rb["schedule"],
              "glidepath_enabled": bool(gp["enabled"]), "current_tier": gp["current_tier"],
              "steps": [{"date": str(s["date"]), "tier": int(s["tier"])} for s in gp["steps"]]}
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def lock_sha(rules: dict) -> str:
    return hashlib.sha256(_canonical(rules).encode()).hexdigest()[:16]


def verify_lock(rules: dict | None = None) -> bool:
    """True only if the rules are marked locked AND the stored hash matches the params (i.e. untampered)."""
    rules = rules or load_rules()
    return bool(rules.get("locked")) and rules.get("lock_sha") == lock_sha(rules)


# ── Rebalancing (rules-based, not condition-based) ──
def drift_pp(target: dict, actual: dict) -> dict:
    """Per-sleeve drift in PERCENTAGE POINTS (actual − target)."""
    return {s: round((actual.get(s, 0.0) - target.get(s, 0.0)) * 100, 2) for s in target}


def needs_rebalance(target: dict, actual: dict, band_pp: float) -> bool:
    return any(abs(d) > band_pp for d in drift_pp(target, actual).values())


def rebalanced_weights(target: dict) -> dict:
    """Trim/top-up everything back to target (the only action — never a market call)."""
    return dict(target)


def drifted_weights(target: dict, sleeve_returns_pct: dict) -> dict:
    """Actual weights after each sleeve moves by its return since the last rebalance."""
    grown = {s: w * (1 + sleeve_returns_pct.get(s, 0.0) / 100) for s, w in target.items()}
    tot = sum(grown.values())
    return {s: round(v / tot, 6) for s, v in grown.items()} if tot else dict(target)


# ── Glidepath (horizon-based, configurable; default OFF) ──
def target_tier(as_of: date, rules: dict | None = None) -> int:
    """The target risk-tier for a given date. While the glidepath is OFF (default) this is always the
    current tier; when ON, it steps DOWN on/after each scheduled date. Driven by the calendar/horizon,
    NEVER by market conditions."""
    rules = rules or load_rules()
    gp = rules["glidepath"]
    tier = int(gp["current_tier"])
    if not gp.get("enabled"):
        return tier
    for step in sorted(gp.get("steps", []), key=lambda x: str(x["date"])):
        if as_of.isoformat() >= str(step["date"]):
            tier = int(step["tier"])
    return tier


def active_core(cores: list, as_of: date, rules: dict | None = None) -> dict:
    """The core whose risk tier the glidepath currently targets."""
    t = target_tier(as_of, rules)
    return next((c for c in cores if c["risk"] == t), cores[0])
