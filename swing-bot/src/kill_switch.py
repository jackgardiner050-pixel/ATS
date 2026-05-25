"""Kill switch — two-tier drawdown protection for the swing bot paper sandbox.

Tier 1 — Soft alert at −10% cumulative P&L:
  - Sends Telegram warning once per period (soft_alert_sent flag prevents repeat pings)
  - Does NOT disable the bot
  - Resets only on manual state edit (intentional friction)

Tier 2 — Hard kill at −20% cumulative P&L (£400 floor on £500 start):
  - Sets disabled=True in kill_switch_state.yaml
  - User must consciously re-enable (no auto-restart)
  - Sends Telegram alert on trigger (best-effort, never blocks disable)

Time box: auto-disables at disable_date (6-month hard limit, set in settings.yaml)

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

_SOFT_ALERT_PCT = -10.0   # warn at -10%, do not disable
_HARD_KILL_PCT  = -20.0   # disable at -20% (£400 floor on £500 start)


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
        "soft_alert_sent": False,        # True once -10% warning has been sent this period
        "start_value_gbp": 500.0,
        "start_date": date.today().isoformat(),
        "disable_date": "2026-11-25",    # 6-month hard limit
        "cumulative_pnl_gbp": 0.0,
        "cumulative_pnl_pct": 0.0,
        "total_closed_trades": 0,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


def is_disabled(path: Optional[Path] = None) -> bool:
    """Return True if the hard kill switch has been triggered."""
    return load_state(path).get("disabled", False)


def check_kill_switch(
    trades: list[dict],
    path: Optional[Path] = None,
    soft_alert_pct: float = _SOFT_ALERT_PCT,
    hard_kill_pct: float = _HARD_KILL_PCT,
    disable_date: str = "2026-11-25",
) -> tuple[bool, str, bool]:
    """Evaluate kill switch conditions after each trade close.

    Args:
        trades:           All closed paper trades (full history).
        path:             Override for kill_switch_state.yaml path.
        soft_alert_pct:   Soft alert threshold (default -10%).
        hard_kill_pct:    Hard kill threshold (default -20%).
        disable_date:     6-month auto-disable date (ISO string).

    Returns:
        (hard_killed: bool, reason: str, soft_alert_fired: bool)
        soft_alert_fired is True only on the FIRST crossing of the soft threshold.
    """
    state = load_state(path)
    if state.get("disabled"):
        return True, state.get("disable_reason", "already_disabled"), False

    start_value = float(state.get("start_value_gbp", 500.0))
    cumulative_pnl = sum(float(t.get("pnl_gbp", 0)) for t in trades)
    cumulative_pct = cumulative_pnl / start_value * 100 if start_value > 0 else 0

    state["cumulative_pnl_gbp"] = round(cumulative_pnl, 4)
    state["cumulative_pnl_pct"] = round(cumulative_pct, 4)
    state["total_closed_trades"] = len(trades)
    state["last_checked"] = datetime.now(timezone.utc).isoformat()

    # ── Time box check ────────────────────────────────────────────────────────
    today = date.today().isoformat()
    if today >= disable_date:
        state["disabled"] = True
        state["disable_reason"] = f"time_expiry ({disable_date})"
        save_state(state, path)
        log.warning("Kill switch: 6-month time box expired (%s). Bot disabled.", disable_date)
        return True, state["disable_reason"], False

    soft_fired = False

    # ── Tier 2: Hard kill at -20% ─────────────────────────────────────────────
    if cumulative_pct <= hard_kill_pct:
        state["disabled"] = True
        state["disable_reason"] = (
            f"hard_kill ({cumulative_pct:.1f}% ≤ {hard_kill_pct:.1f}%)"
        )
        save_state(state, path)
        log.warning(
            "Kill switch HARD KILL: cumulative P&L %.1f%% (£%.2f) ≤ %.1f%%.",
            cumulative_pct, cumulative_pnl, hard_kill_pct,
        )
        return True, state["disable_reason"], False

    # ── Tier 1: Soft alert at -10% (once per period) ──────────────────────────
    if cumulative_pct <= soft_alert_pct and not state.get("soft_alert_sent", False):
        state["soft_alert_sent"] = True
        soft_fired = True
        log.warning(
            "Kill switch SOFT ALERT: cumulative P&L %.1f%% (£%.2f) ≤ %.1f%%.",
            cumulative_pct, cumulative_pnl, soft_alert_pct,
        )

    save_state(state, path)
    return False, "ok", soft_fired


def format_soft_alert(cumulative_pct: float, cumulative_gbp: float) -> str:
    """Format the Telegram soft-alert (warning, bot still running)."""
    return (
        f"⚠️ SWING BOT WARNING — Soft alert threshold hit\n\n"
        f"Cumulative P&L: {cumulative_pct:+.1f}% (£{cumulative_gbp:+.2f})\n"
        f"Soft threshold: {_SOFT_ALERT_PCT:.0f}% | Hard kill: {_HARD_KILL_PCT:.0f}%\n\n"
        f"Bot is still running. Review open positions.\n"
        f"Hard kill (auto-disable) triggers at {_HARD_KILL_PCT:.0f}% (£{500*(1+_HARD_KILL_PCT/100):.0f} floor)."
    )


def format_kill_alert(reason: str, cumulative_pct: float, cumulative_gbp: float) -> str:
    """Format the Telegram hard-kill alert message."""
    return (
        f"⛔ SWING BOT HARD KILL TRIGGERED\n\n"
        f"Reason: {reason}\n"
        f"Cumulative P&L: {cumulative_pct:+.1f}% (£{cumulative_gbp:+.2f})\n"
        f"Floor breached: £{500*(1+_HARD_KILL_PCT/100):.0f} (−20% on £500 start)\n\n"
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
