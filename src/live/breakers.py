"""Live loss breakers — daily / weekly / cumulative, evaluated against live_limits.yaml.

FAIL-SAFE: the thresholds are deliberately null placeholders today. This module builds the
MECHANISM only — it loads whatever is in live_limits.yaml at runtime and, if ANY of
DAILY/WEEKLY/CUMULATIVE is still null, it REFUSES to evaluate and BLOCKS card generation
(never silently skips a check). The −3/−6/−20 numbers from the protocol draft are NOT
hardcoded anywhere here — they are config, set later by deliberate re-registration.

Breaches:
  daily      → data/live/HALT_DAILY (auto-clears next session)
  weekly     → data/live/HALT_WEEKLY (two-step reset, like the kill switch)
  cumulative → KILL (terminal): "PILOT TERMINATED — post-mortem required"
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from src.live import LIVE_DATA
from src.live.kill import engage_kill, is_killed

_THRESHOLD_KEYS = ("DAILY_LOSS_HALT_PCT", "WEEKLY_LOSS_HALT_PCT", "CUMULATIVE_KILL_PCT")
HALT_DAILY = LIVE_DATA / "HALT_DAILY"
HALT_WEEKLY = LIVE_DATA / "HALT_WEEKLY"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def missing_thresholds(limits: dict) -> list[str]:
    return [k for k in _THRESHOLD_KEYS if limits.get(k) is None]


def is_daily_halted(today: date | None = None, sentinel: Path = HALT_DAILY) -> bool:
    """Daily halt auto-clears on a NEW session/day: the sentinel is date-stamped and only
    counts for the day it was written."""
    p = Path(sentinel)
    if not p.exists():
        return False
    stamped = p.read_text().strip().split("\n", 1)[0]
    return stamped == str(today or date.today())


def is_weekly_halted(sentinel: Path = HALT_WEEKLY) -> bool:
    return Path(sentinel).exists()


def evaluate(pnl_state: dict, limits: dict, today: date | None = None,
             halt_daily: Path | None = None, halt_weekly: Path | None = None,
             on_kill=None) -> dict:
    """Evaluate breakers + apply sentinel/kill side effects. Returns
    {blocked: bool, reasons: [...], actions: [...]}. The kill switch itself is a separate
    gate (kill.kill_block) checked before this in live_card_run.

    FAIL-SAFE: any null threshold → blocked=True, NO P&L check performed.
    Paths/on_kill are injectable for testing; defaults are the real sentinels + a terminal
    engage_kill. The -3/-6/-20 numbers live ONLY in config (limits), never here.
    """
    today = today or date.today()
    halt_daily = Path(halt_daily) if halt_daily else HALT_DAILY
    halt_weekly = Path(halt_weekly) if halt_weekly else HALT_WEEKLY
    on_kill = on_kill or (lambda reason: engage_kill(reason, terminal=True))

    missing = missing_thresholds(limits)
    if missing:
        return {"blocked": True, "actions": [],
                "reasons": [f"breaker thresholds not set in live_limits.yaml: {missing} — "
                            f"FAIL-SAFE, card generation blocked until they are configured."]}

    actions, reasons = [], []
    daily, weekly = pnl_state.get("daily_pnl_pct"), pnl_state.get("weekly_pnl_pct")
    cumulative = pnl_state.get("cumulative_pnl_pct")

    if daily is not None and float(daily) <= -abs(float(limits["DAILY_LOSS_HALT_PCT"])):
        halt_daily.parent.mkdir(parents=True, exist_ok=True)
        halt_daily.write_text(f"{today}\ndaily {float(daily):.4f} @ {_now()}\n")
        actions.append("HALT_DAILY")
        reasons.append(f"daily P&L {float(daily):.1%} breached daily halt")

    if weekly is not None and float(weekly) <= -abs(float(limits["WEEKLY_LOSS_HALT_PCT"])):
        halt_weekly.parent.mkdir(parents=True, exist_ok=True)
        halt_weekly.write_text(f"weekly {float(weekly):.4f} @ {_now()}\n")
        actions.append("HALT_WEEKLY")
        reasons.append(f"weekly P&L {float(weekly):.1%} breached weekly halt")

    if cumulative is not None and float(cumulative) <= -abs(float(limits["CUMULATIVE_KILL_PCT"])):
        on_kill(f"PILOT TERMINATED — cumulative P&L {float(cumulative):.1%} breached kill; "
                f"post-mortem required.")
        actions.append("KILL_TERMINAL")
        reasons.append(f"cumulative P&L {float(cumulative):.1%} breached kill — PILOT TERMINATED")

    blocked = bool(actions) or is_daily_halted(today, halt_daily) or is_weekly_halted(halt_weekly)
    return {"blocked": blocked, "actions": actions, "reasons": reasons}


def clear_daily(sentinel: Path = HALT_DAILY) -> None:
    """Daily halt auto-clears next session; this removes a stale/consumed daily sentinel."""
    if Path(sentinel).exists():
        Path(sentinel).unlink()
