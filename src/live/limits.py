"""Live-pilot limit loading + guard checks (modeled on src/governance/constitution.py).

Load-time validation (execution-stage enum + hard boolean), a `LiveLimitViolation`
exception, and the two guard functions `check_order_admissible` / `check_breakers`.
NO broker libraries; imports NO decision math.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_LIVE_LIMITS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "live_limits.yaml"

# E2 (autonomous execution) is deliberately NOT parseable today — it requires constitution
# v3. Only E0 (shadow) and E1 (human-executed) are valid values.
VALID_EXECUTION_STAGES = ("E0", "E1")

# Same immutability treatment as the constitution hard booleans: must be True.
_HARD_BOOLEANS = ["HUMAN_EXECUTES_ALL_ORDERS"]

# Loss-breaker keys (percentages; None = placeholder not yet set by the locked protocol).
_BREAKERS = (
    ("DAILY_LOSS_HALT_PCT", "daily_pnl_pct", "daily"),
    ("WEEKLY_LOSS_HALT_PCT", "weekly_pnl_pct", "weekly"),
    ("CUMULATIVE_KILL_PCT", "cumulative_pnl_pct", "cumulative"),
)


class LiveLimitViolation(Exception):
    """Raised when a live-pilot hard limit is breached (load-time or at a guard check)."""


def load_live_limits(path: Path | None = None) -> dict:
    """Load + validate config/live_limits.yaml. Raises LiveLimitViolation on an invalid
    execution stage or a hard-boolean breach."""
    p = path or _LIVE_LIMITS_PATH
    if not p.exists():
        raise FileNotFoundError(f"Live limits file not found: {p}")
    cfg = yaml.safe_load(p.read_text())
    if not cfg:
        raise ValueError("Live limits file is empty.")
    _validate_execution_stage(cfg)
    _validate_hard_booleans(cfg)
    return cfg


def _validate_execution_stage(cfg: dict) -> None:
    stage = cfg.get("execution_stage")
    if stage == "E2":
        raise LiveLimitViolation(
            "execution_stage 'E2' (autonomous execution) requires constitution v3 — it "
            "cannot be used under the current constitution, so the value cannot even parse "
            "today. Set 'E0' or 'E1'.")
    if stage not in VALID_EXECUTION_STAGES:
        raise LiveLimitViolation(
            f"execution_stage {stage!r} is invalid; expected one of {VALID_EXECUTION_STAGES}.")


def _validate_hard_booleans(cfg: dict) -> None:
    """Raise LiveLimitViolation if any hard boolean is not True (constitution pattern)."""
    for key in _HARD_BOOLEANS:
        if key not in cfg:
            raise LiveLimitViolation(f"Missing hard boolean in live limits: {key}")
        if cfg[key] is not True:
            raise LiveLimitViolation(
                f"Live-limit violation: {key} must be True, got {cfg[key]!r}. This is an "
                f"immutable hard rule — a human, never the system, executes every order.")


def cards_enabled(limits: dict) -> bool:
    """Card generation is refused while the pilot is unfunded (MAX_LIVE_CAPITAL_GBP == 0)."""
    return float(limits.get("MAX_LIVE_CAPITAL_GBP", 0) or 0) > 0


def _order_weight(intent: dict, capital: float) -> float:
    """Order size as a fraction of live capital (from an explicit weight, or notional/capital)."""
    if intent.get("weight") is not None:
        return float(intent["weight"])
    if intent.get("notional_gbp") is not None and capital > 0:
        return float(intent["notional_gbp"]) / capital
    return 0.0


def check_order_admissible(intent: dict, book_state: dict, limits: dict) -> list[str]:
    """Return a list of violation strings for one proposed order intent. Empty = admissible.

    intent      : {ticker, weight | notional_gbp, ...}
    book_state  : {orders_this_week: int, ...}
    """
    violations: list[str] = []
    capital = float(limits.get("MAX_LIVE_CAPITAL_GBP", 0) or 0)
    if capital <= 0:
        # loader refuses to generate cards while unfunded — nothing is admissible
        return ["MAX_LIVE_CAPITAL_GBP is 0 — the pilot is unfunded; no live order cards may "
                "be generated until the operator sets capital via re-registration."]

    max_pos = float(limits.get("MAX_SINGLE_POSITION_LIVE", 0.10))
    weight = _order_weight(intent, capital)
    if weight > max_pos + 1e-9:
        violations.append(
            f"{intent.get('ticker', '?')}: position {weight:.1%} exceeds "
            f"MAX_SINGLE_POSITION_LIVE {max_pos:.1%}")

    max_orders = int(limits.get("MAX_ORDERS_PER_WEEK", 5))
    placed = int(book_state.get("orders_this_week", 0))
    if placed >= max_orders:
        violations.append(
            f"MAX_ORDERS_PER_WEEK {max_orders} reached ({placed} already issued this week) "
            f"— no further order cards this week.")
    return violations


def check_breakers(pnl_state: dict, limits: dict) -> dict:
    """Evaluate the loss breakers against P&L state. Returns
    {halt: bool, kill: bool, reasons: [...]}. An unset (null) threshold is skipped.

    pnl_state percentages are fractions, negative for a loss (e.g. -0.03 = down 3%).
    """
    reasons: list[str] = []
    kill = False
    for key, pnl_key, label in _BREAKERS:
        thr = limits.get(key)
        if thr is None:
            continue  # placeholder not yet set by the locked protocol
        pnl = pnl_state.get(pnl_key)
        if pnl is not None and float(pnl) <= -abs(float(thr)):
            reasons.append(f"{label} loss {float(pnl):.1%} <= halt {-abs(float(thr)):.1%}")
            if key == "CUMULATIVE_KILL_PCT":
                kill = True
    return {"halt": bool(reasons), "kill": kill, "reasons": reasons}
