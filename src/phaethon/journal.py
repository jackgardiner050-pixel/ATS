"""Phaethon decision journal (item 1 foundation) — the append-only, hash-chained record
of Phaethon's decisions, exits, and boundary ceremonies.

This is HUMAN-SIDE machinery. It is never read by Phaethon's live prompt/context path
(NO_LIVE_PNL_LEARNING firewall — enforced by tests/test_constitutional_guards.py).

Record types (event field):
  ENTRY           {ts, event, ticker, thesis_category?, stated_conviction?, conviction_tier?}
  EXIT            {ts, event, ticker, thesis_category?, stated_conviction?, conviction_tier?,
                   override_direction? (hold|sell|None), hold_days, outcome (win|loss)}
  WINDOW_BOUNDARY {ts, event, prompt_version, lessons_adopted:[{lesson_id, forward_prediction,
                   adoption_stats}], prompt_hash}   ← the boundary-ceremony record
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.research.registry import append_hashchained, read_chain, verify_chain  # noqa: F401

EVENT_ENTRY = "ENTRY"
EVENT_EXIT = "EXIT"
EVENT_BOUNDARY = "WINDOW_BOUNDARY"

DEFAULT_JOURNAL = Path(__file__).resolve().parent.parent.parent / "data" / "phaethon" / "journal.jsonl"


def read_journal(path: str | Path = DEFAULT_JOURNAL) -> list[dict]:
    return read_chain(path)


def parse_ts(v) -> datetime:
    """Parse an ISO timestamp to an aware UTC datetime."""
    if isinstance(v, datetime):
        dt = v
    else:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def boundaries(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("event") == EVENT_BOUNDARY]


def last_boundary(records: list[dict]) -> dict | None:
    bs = boundaries(records)
    return bs[-1] if bs else None


def inception_ts(records: list[dict]) -> datetime | None:
    """Earliest record ts = Phaethon's inception for the first-ever review."""
    ts = [parse_ts(r["ts"]) for r in records if r.get("ts")]
    return min(ts) if ts else None


def exits_since_last_boundary(records: list[dict]) -> tuple[list[dict], dict | None]:
    """EXIT records logged after the last WINDOW_BOUNDARY (or all EXITs if no boundary yet).
    Returns (exits, last_boundary_or_None)."""
    lb = last_boundary(records)
    exits = [r for r in records if r.get("event") == EVENT_EXIT]
    if lb is not None:
        cutoff = parse_ts(lb["ts"])
        exits = [r for r in exits if parse_ts(r["ts"]) > cutoff]
    return exits, lb


# ─── append helpers (hash-chained) ───────────────────────────────────────────

def append_exit(record: dict, path: str | Path = DEFAULT_JOURNAL) -> dict:
    return append_hashchained(path, {**record, "event": EVENT_EXIT})


def append_boundary(prompt_version, lessons_adopted: list[dict], prompt_hash: str,
                    ts: str, path: str | Path = DEFAULT_JOURNAL) -> dict:
    return append_hashchained(path, {
        "ts": ts, "event": EVENT_BOUNDARY, "prompt_version": prompt_version,
        "lessons_adopted": lessons_adopted, "prompt_hash": prompt_hash,
    })
