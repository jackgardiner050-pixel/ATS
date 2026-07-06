"""Live kill switch — the file is the single source of truth (works with Telegram down).

Engaged iff data/live/KILL exists OR a /kill was received (the handler writes the file).
Engaged → card generation refuses, all PENDING intents → KILLED, alert sent. Reset requires
TWO deliberate steps, both logged with an operator reason: /confirm_resume AND manual
deletion of the KILL file. A cumulative-breach kill is TERMINAL — resume is additionally
refused until a completed post-mortem exists (POST_MORTEM_PATH in live_limits.yaml).

Modeled on the swing-bot Tier-2 pattern; swing-bot code is NOT imported (ringfence).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.io_utils import append_jsonl
from src.live import LIVE_DATA

_REPO = LIVE_DATA.parent.parent
KILL_SENTINEL = LIVE_DATA / "KILL"
KILL_LOG = LIVE_DATA / "kill_events.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_killed(sentinel: Path = KILL_SENTINEL) -> bool:
    return Path(sentinel).exists()


def _events(log: Path = KILL_LOG) -> list[dict]:
    p = Path(log)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def last_kill_event(log: Path = KILL_LOG) -> dict | None:
    ev = _events(log)
    return ev[-1] if ev else None


def engage_kill(reason: str, terminal: bool = False,
                sentinel: Path = KILL_SENTINEL, log: Path = KILL_LOG) -> None:
    """Write the KILL file (source of truth) + log the ENGAGE event. Called by the /kill
    handler and by the cumulative breaker (terminal=True)."""
    Path(sentinel).parent.mkdir(parents=True, exist_ok=True)
    Path(sentinel).write_text(f"KILLED {_now()}\nterminal: {bool(terminal)}\nreason: {reason}\n")
    append_jsonl(log, {"event": "ENGAGE", "ts": _now(), "reason": reason, "terminal": bool(terminal)})


def kill_block(sentinel: Path = KILL_SENTINEL, log: Path = KILL_LOG) -> tuple[bool, str]:
    """Should generation be blocked by the kill switch? Enforces the two-step reset:
    the file present blocks; and even after the file is deleted, generation stays blocked
    until /confirm_resume was logged for the engaged kill."""
    if is_killed(sentinel):
        return True, "KILL sentinel present — pilot halted"
    ev = last_kill_event(log)
    if ev and ev.get("event") == "ENGAGE":
        return True, "KILL file deleted but /confirm_resume not logged — two-step reset incomplete"
    return False, ""


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (_REPO / p)


def confirm_resume(reason: str, limits: dict | None = None,
                   log: Path = KILL_LOG) -> dict:
    """Step 1 of the two-step reset: log a /confirm_resume with an operator reason. Does NOT
    delete the KILL file — that manual deletion is the deliberate step 2. Refuses without a
    reason, and refuses a TERMINAL (cumulative) kill until a completed post-mortem exists."""
    if not reason or not reason.strip():
        raise ValueError("resume refused: /confirm_resume requires a non-empty operator reason")
    ev = last_kill_event(log)
    if not (ev and ev.get("event") == "ENGAGE"):
        raise ValueError("resume refused: there is no engaged kill to resume from")
    if ev.get("terminal"):
        pm = (limits or {}).get("POST_MORTEM_PATH")
        if not pm or not _resolve(pm).exists():
            raise ValueError(
                "resume refused: this was a TERMINAL cumulative-breach kill — the pilot is "
                "terminated. Resume is impossible until a completed post-mortem exists at "
                "POST_MORTEM_PATH in live_limits.yaml (deliberate friction).")
    rec = {"event": "RESUME_CONFIRM", "ts": _now(), "reason": reason}
    append_jsonl(log, rec)
    return rec


def kill_all_pending(state_path=None, intents_log=None) -> list[str]:
    """Set every PENDING intent to KILLED (called when the kill is detected)."""
    from src.live import intents as I
    sp = state_path or I.INTENT_STATE
    lp = intents_log or I.INTENTS_LOG
    killed = []
    for it in I.pending_intents(sp):
        I.set_status(it["card_id"], "KILLED", log_path=lp, state_path=sp, cause="kill_switch")
        killed.append(it["card_id"])
    return killed
