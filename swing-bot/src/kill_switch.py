"""Kill switch — auto-disables swing bot on excessive paper loss or time expiry.

Hard rules:
  - Triggers at cumulative P&L ≤ -10% from start value (£450 floor on £500)
  - Auto-disables at disable_date (6-month time box, set in settings.yaml)
  - When triggered: sets disabled=True in kill_switch_state.yaml
  - User must consciously re-enable (no auto-restart)
  - Sends Telegram alert on trigger (best-effort, doesn't block disable)

Storage: data/kill_switch_state.yaml (gitignored)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

_STATE_PATH = Path(__file__).parent.parent / "data" / "kill_switch_state.yaml"


def load_state(path: Optional[Path] = None) -> dict:
    """Load kill switch state. Returns default state if file missing."""
    p = path or _STATE_PATH
    if not p.exists():
        return _default_state()
    with open(p) as f:
        return yaml.safe_load(f) or _default_state()


def save_state(state: dict, path: Optional[Path] = None) -> None:
    p = path or _STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def _default_state() -> dict:
    return {
        "disabled": False,
        "disable_reason": None,
        "start_value_gbp": 500.0,
        "start_date": date.today().isoformat(),
        "disable_date": "2026-11-25",  # 6-month hard limit
        "cumulative_pnl_gbp": 0.0,
        "cumulative_pnl_pct": 0.0,
        "total_closed_trades": 0,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


def is_disabled(path: Optional[Path] = None) -> bool:
    """Return True if the kill switch has been triggered (check this before every poll)."""
    return load_state(path).get("disabled", False)


def check_kill_switch(
    trades: list[dict],
    path: Optional[Path] = None,
    max_drawdown_pct: float = -10.0,
    disable_date: str = "2026-11-25",
) -> tuple[bool, str]:
    """Evaluate kill switch conditions after each trade close.

    Args:
        trades:           All closed paper trades (full history).
        path:             Override for kill_switch_state.yaml path.
        max_drawdown_pct: Trigger threshold (default -10%).
        disable_date:     6-month auto-disable date (ISO string).

    Returns:
        (triggered: bool, reason: str)
    """
    state = load_state(path)
    if state.get("disabled"):
        return True, state.get("disable_reason", "already_disabled")

    start_value = float(state.get("start_value_gbp", 500.0))
    cumulative_pnl = sum(float(t.get("pnl_gbp", 0)) for t in trades)
    cumulative_pct = cumulative_pnl / start_value * 100 if start_value > 0 else 0

    state["cumulative_pnl_gbp"] = round(cumulative_pnl, 4)
    state["cumulative_pnl_pct"] = round(cumulative_pct, 4)
    state["total_closed_trades"] = len(trades)
    state["last_checked"] = datetime.now(timezone.utc).isoformat()

    # Check 6-month time box
    today = date.today().isoformat()
    if today >= disable_date:
        state["disabled"] = True
        state["disable_reason"] = f"time_expiry ({disable_date})"
        save_state(state, path)
        log.warning("Kill switch: 6-month time box expired (%s). Bot disabled.", disable_date)
        return True, state["disable_reason"]

    # Check cumulative drawdown
    if cumulative_pct <= max_drawdown_pct:
        state["disabled"] = True
        state["disable_reason"] = (
            f"cumulative_loss ({cumulative_pct:.1f}% ≤ {max_drawdown_pct:.1f}%)"
        )
        save_state(state, path)
        log.warning(
            "Kill switch TRIGGERED: cumulative P&L %.1f%% (£%.2f) ≤ %.1f%% threshold.",
            cumulative_pct, cumulative_pnl, max_drawdown_pct,
        )
        return True, state["disable_reason"]

    save_state(state, path)
    return False, "ok"


def format_kill_alert(reason: str, cumulative_pct: float, cumulative_gbp: float) -> str:
    """Format the Telegram kill switch alert message."""
    return (
        f"⛔ SWING BOT KILL SWITCH TRIGGERED\n\n"
        f"Reason: {reason}\n"
        f"Cumulative P&L: {cumulative_pct:+.1f}% (£{cumulative_gbp:+.2f})\n\n"
        f"Bot is now DISABLED. Re-enable manually in kill_switch_state.yaml "
        f"after reviewing the catalyst log."
    )


def update_pnl(trades: list[dict], path: Optional[Path] = None) -> None:
    """Update cumulative P&L in state without triggering the kill switch check."""
    state = load_state(path)
    start_value = float(state.get("start_value_gbp", 500.0))
    cumulative_pnl = sum(float(t.get("pnl_gbp", 0)) for t in trades)
    state["cumulative_pnl_gbp"] = round(cumulative_pnl, 4)
    state["cumulative_pnl_pct"] = round(
        cumulative_pnl / start_value * 100 if start_value > 0 else 0, 4
    )
    state["total_closed_trades"] = len(trades)
    save_state(state, path)
