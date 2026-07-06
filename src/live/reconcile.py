"""Reconciliation — every fill has a matching intent; positions = Σ fills; optional
cross-check against a manually exported broker statement (generic CSV, columns configured
in live_limits.yaml). ANY mismatch writes data/live/RECONCILE_BLOCK; card generation
refuses to run while that sentinel exists.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.live import LIVE_DATA

RECONCILE_BLOCK = LIVE_DATA / "RECONCILE_BLOCK"
_DEFAULT_COLS = {"ticker": "ticker", "qty": "qty", "price": "price", "date": "date"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_blocked(sentinel: Path = RECONCILE_BLOCK) -> bool:
    return Path(sentinel).exists()


def block(reason: str, sentinel: Path = RECONCILE_BLOCK) -> None:
    Path(sentinel).parent.mkdir(parents=True, exist_ok=True)
    Path(sentinel).write_text(f"RECONCILE_BLOCK {_now()}\n{reason}\n")


def clear_block(reason: str, sentinel: Path = RECONCILE_BLOCK) -> bool:
    if not reason or not reason.strip():
        raise ValueError("clearing RECONCILE_BLOCK requires a non-empty operator reason")
    if is_blocked(sentinel):
        Path(sentinel).unlink()
        return True
    return False


def positions_from_fills(fills: list[dict]) -> dict[str, float]:
    """Net signed quantity per ticker: BUY adds, SELL subtracts."""
    pos: dict[str, float] = {}
    for f in fills:
        q = float(f.get("qty", 0)) * (1 if f.get("side") == "BUY" else -1)
        pos[f["ticker"]] = pos.get(f["ticker"], 0.0) + q
    return {t: round(q, 6) for t, q in pos.items() if abs(q) > 1e-9}


def parse_broker_csv(path, cols: dict | None = None) -> list[dict]:
    cols = {**_DEFAULT_COLS, **(cols or {})}
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"ticker": r[cols["ticker"]], "qty": float(r[cols["qty"]]),
                         "price": r.get(cols["price"]), "date": r.get(cols["date"])})
    return rows


def broker_positions(broker_rows: list[dict]) -> dict[str, float]:
    pos: dict[str, float] = {}
    for r in broker_rows:
        pos[r["ticker"]] = pos.get(r["ticker"], 0.0) + float(r["qty"])
    return {t: round(q, 6) for t, q in pos.items() if abs(q) > 1e-9}


def reconcile(intents_state: dict, fills: list[dict],
              broker_rows: list[dict] | None = None) -> dict:
    """Returns {ok, mismatches, positions}. mismatches empty = reconciled."""
    mismatches: list[str] = []
    for f in fills:
        if f.get("card_id") not in intents_state:
            mismatches.append(f"fill {f.get('card_id')!r} ({f.get('ticker')}) has NO matching intent")
    positions = positions_from_fills(fills)
    if broker_rows is not None:
        bpos = broker_positions(broker_rows)
        for t in sorted(set(positions) | set(bpos)):
            if abs(positions.get(t, 0.0) - bpos.get(t, 0.0)) > 1e-6:
                mismatches.append(f"{t}: internal Σfills={positions.get(t, 0.0)} vs "
                                  f"broker={bpos.get(t, 0.0)}")
    return {"ok": not mismatches, "mismatches": mismatches, "positions": positions}


def reconcile_and_maybe_block(intents_state: dict, fills: list[dict],
                              broker_rows: list[dict] | None = None,
                              sentinel: Path = RECONCILE_BLOCK) -> dict:
    """Reconcile and, on ANY mismatch, write the RECONCILE_BLOCK sentinel."""
    r = reconcile(intents_state, fills, broker_rows)
    if not r["ok"] and not is_blocked(sentinel):
        block("; ".join(r["mismatches"]), sentinel)
    return r
