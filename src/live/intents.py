"""Order intents (Hermes E1) — the proposal record. Append-only log + current state.

An OrderIntent is a PROPOSAL for a human to execute; it is never a live order and never
touches a paper cohort file. BUY/SELL only — SELL closes a held position; there is no
SHORT (constitution NO_SHORT_SELLING).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.io_utils import append_jsonl, atomic_write_text
from src.live import LIVE_DATA

SIDES = ("BUY", "SELL")                                  # no SHORT (NO_SHORT_SELLING)
STATUSES = ("PENDING", "FILLED", "EXPIRED", "KILLED")

INTENTS_LOG = LIVE_DATA / "intents.jsonl"                # append-only
INTENT_STATE = LIVE_DATA / "intent_state.yaml"          # current {card_id: intent}


@dataclass
class OrderIntent:
    card_id: str
    ts: str
    ticker: str
    side: str
    notional_gbp: float
    limit_guidance: float | None
    source_rule: str
    cohort: str
    status: str = "PENDING"
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.side not in SIDES:
            raise ValueError(f"side must be BUY or SELL (no SHORT), got {self.side!r}")
        if self.status not in STATUSES:
            raise ValueError(f"invalid status {self.status!r}; expected one of {STATUSES}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_intent(ticker: str, side: str, notional_gbp: float, source_rule: str, cohort: str,
               limit_guidance: float | None = None, ts: str | None = None,
               card_id: str | None = None, **meta) -> OrderIntent:
    return OrderIntent(card_id=card_id or uuid.uuid4().hex[:12], ts=ts or _now(),
                       ticker=ticker, side=side, notional_gbp=float(notional_gbp),
                       limit_guidance=limit_guidance, source_rule=source_rule,
                       cohort=cohort, status="PENDING", meta=meta)


def load_intent_state(path: Path = INTENT_STATE) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text()) or {}).get("intents", {})


def save_intent_state(state: dict, path: Path = INTENT_STATE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump({"intents": state}, sort_keys=False, allow_unicode=True))


def record_intent(intent: OrderIntent, log_path: Path = INTENTS_LOG,
                  state_path: Path = INTENT_STATE) -> OrderIntent:
    """Append the intent to the immutable log and set it PENDING in current state."""
    append_jsonl(log_path, {"event": "INTENT", **asdict(intent)})
    state = load_intent_state(state_path)
    state[intent.card_id] = asdict(intent)
    save_intent_state(state, state_path)
    return intent


def set_status(card_id: str, status: str, log_path: Path = INTENTS_LOG,
               state_path: Path = INTENT_STATE, **event) -> dict:
    """Advance an intent's status (append a status event; update current state)."""
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}")
    state = load_intent_state(state_path)
    if card_id not in state:
        raise KeyError(f"unknown card_id {card_id!r}")
    state[card_id]["status"] = status
    save_intent_state(state, state_path)
    append_jsonl(log_path, {"event": "STATUS", "card_id": card_id, "status": status,
                            "ts": _now(), **event})
    return state[card_id]


def pending_intents(state_path: Path = INTENT_STATE) -> list[dict]:
    return [i for i in load_intent_state(state_path).values() if i.get("status") == "PENDING"]
