"""Fills — the human reports what they executed (via /fill reply or the CLI).

A fill records a card_id, price, qty, ts (+ decision/card prices for slippage) to the
append-only data/live/fills.jsonl and advances the intent to FILLED. PENDING cards left
untouched for 2 trading days auto-EXPIRE (with an alert).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.io_utils import append_jsonl
from src.live import LIVE_DATA
from src.live.intents import INTENT_STATE, INTENTS_LOG, load_intent_state, set_status

FILLS_LOG = LIVE_DATA / "fills.jsonl"
EXPIRE_TRADING_DAYS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def record_fill(card_id: str, price: float, qty: float, ts: str | None = None,
                decision_price: float | None = None, card_price: float | None = None,
                fills_log: Path = FILLS_LOG, state_path: Path = INTENT_STATE,
                intents_log: Path = INTENTS_LOG) -> dict:
    """Record a human-reported fill and mark its intent FILLED."""
    state = load_intent_state(state_path)
    if card_id not in state:
        raise KeyError(f"no intent for card_id {card_id!r}")
    intent = state[card_id]
    fill = {"card_id": card_id, "ticker": intent["ticker"], "side": intent["side"],
            "price": float(price), "qty": float(qty), "ts": ts or _now(),
            "decision_price": decision_price if decision_price is not None else intent.get("meta", {}).get("decision_price"),
            "card_price": card_price if card_price is not None else intent.get("meta", {}).get("card_price"),
            "notional_gbp": intent.get("notional_gbp")}
    append_jsonl(fills_log, fill)
    set_status(card_id, "FILLED", log_path=intents_log, state_path=state_path,
               price=float(price), qty=float(qty))
    return fill


def load_fills(fills_log: Path = FILLS_LOG) -> list[dict]:
    import json
    p = Path(fills_log)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _trading_days_between(start: datetime, end: datetime) -> int:
    """Weekdays strictly after `start`'s date up to and including `end`'s date."""
    d, e, n = start.date(), end.date(), 0
    while d < e:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def expire_stale(now: datetime | None = None, max_trading_days: int = EXPIRE_TRADING_DAYS,
                 state_path: Path = INTENT_STATE, intents_log: Path = INTENTS_LOG) -> list[dict]:
    """EXPIRE any PENDING intent untouched for >= max_trading_days trading days. Returns the
    expired intents (the caller alerts on them)."""
    now = now or datetime.now(timezone.utc)
    expired = []
    for cid, intent in list(load_intent_state(state_path).items()):
        if intent.get("status") != "PENDING":
            continue
        if _trading_days_between(_parse(intent["ts"]), now) >= max_trading_days:
            set_status(cid, "EXPIRED", log_path=intents_log, state_path=state_path,
                       cause=f"untouched > {max_trading_days} trading days")
            expired.append(intent)
    return expired
