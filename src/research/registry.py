"""Append-only, hash-chained record store (the canonical registry pattern).

Every appended record carries `prev_hash` (the prior record's hash, or 64 zeros for
the genesis record) and `hash` = sha256(prev_hash + canonical-json(payload)), where
payload is the record WITHOUT the two chain fields. This makes any retroactive edit or
deletion detectable. Reused by the Phaethon journal and lessons ledger — do not
reimplement the chaining elsewhere.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.io_utils import append_jsonl

GENESIS_HASH = "0" * 64
_CHAIN_FIELDS = ("prev_hash", "hash")


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def record_hash(prev_hash: str, payload: dict) -> str:
    """sha256(prev_hash + canonical-json(payload)). payload excludes the chain fields."""
    body = {k: v for k, v in payload.items() if k not in _CHAIN_FIELDS}
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def read_chain(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def last_hash(path: str | Path) -> str:
    chain = read_chain(path)
    return chain[-1]["hash"] if chain else GENESIS_HASH


def append_hashchained(path: str | Path, record: dict) -> dict:
    """Append `record` with prev_hash/hash filled in. Returns the stored record."""
    prev = last_hash(path)
    stored = {**{k: v for k, v in record.items() if k not in _CHAIN_FIELDS},
              "prev_hash": prev}
    stored["hash"] = record_hash(prev, stored)
    append_jsonl(path, stored)
    return stored


def verify_chain(path: str | Path) -> tuple[bool, str | None]:
    """Return (ok, error). Verifies prev_hash linkage and each record's hash."""
    prev = GENESIS_HASH
    for i, rec in enumerate(read_chain(path)):
        if rec.get("prev_hash") != prev:
            return False, f"record {i}: prev_hash mismatch"
        if rec.get("hash") != record_hash(rec["prev_hash"], rec):
            return False, f"record {i}: hash mismatch (tampered)"
        prev = rec["hash"]
    return True, None
