"""Olympus ledgers — built on the REAL pit_ledger (no stub).

The decision and override ledgers are hash-chained, append-only, no-look-ahead JSONL files
written through `experimental_pot_engine.track.pit_ledger` — the same immutable primitive the
Oracle forward-test and the Nike/Iris tracks use. A decision recorded here is tamper-evident
and chronological by construction. Olympus records nothing it has not governed first.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from olympus.core import config  # wires sys.path to ~/labs on import

from experimental_pot_engine.track import pit_ledger as L  # the real ledger primitive

DECISIONS = config.LEDGER_DIR / "olympus_decisions.jsonl"
OVERRIDES = config.LEDGER_DIR / "olympus_overrides.jsonl"
ENGINE = "olympus_mvp"

# Map an Olympus decision to a valid pit_ledger kind (the exact decision is kept in detail).
_KIND = {"BUY": L.KIND_BUY, "HOLD": L.KIND_HOLD, "REDUCE": L.KIND_SELL, "EXIT": L.KIND_SELL}


def ensure_genesis(path=DECISIONS, note="Olympus MVP decision ledger — governed, paper-only.") -> Optional[dict]:
    if L.tip(path) is not None:
        return None
    return L.append_entry(path, engine=ENGINE, entry_date=date.today(), kind=L.KIND_GENESIS,
                          detail={"note": note, "paper_only": True, "broker_path": "NONE"},
                          record_class=L.LIVE_RECORD_CLASS)


def append_decision(zeus_decision: dict, *, ticker: str, decision: str,
                    data_as_of: Optional[str] = None) -> dict:
    """Append a governed Zeus decision to the real hash-chained decision ledger."""
    ensure_genesis(DECISIONS)
    return L.append_entry(
        DECISIONS, engine=ENGINE, entry_date=date.today(),
        kind=_KIND.get(decision, L.KIND_MARK), ticker=ticker,
        detail={"zeus_decision": zeus_decision, "paper_only": True,
                "human_authorisation_required": True},
        data_as_of=date.fromisoformat(data_as_of) if data_as_of else None,
        record_class=L.LIVE_RECORD_CLASS,
    )


def append_override(override: dict, *, ticker: str) -> dict:
    ensure_genesis(OVERRIDES, note="Olympus MVP human-override ledger.")
    return L.append_entry(OVERRIDES, engine=ENGINE, entry_date=date.today(),
                          kind=L.KIND_MARK, ticker=ticker, detail={"override": override},
                          record_class=L.LIVE_RECORD_CLASS)


def decisions() -> List[Dict]:
    return L.read_ledger(DECISIONS)


def verify() -> tuple:
    return L.verify_chain(DECISIONS)
