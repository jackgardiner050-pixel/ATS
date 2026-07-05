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


# ─── Hypothesis registry (research/registry.yaml — append-only, content hash chain) ──
#
# The pre-registration ledger of falsifiable hypotheses (the honest denominator m for
# multiple-testing correction). Entries are APPEND-ONLY: `status` may advance (forward
# only) and `result_ref` may attach with the terminal status, but the IMMUTABLE core
# (hypothesis/mechanism/plan/…) can never be edited — enforced by an entry-content hash
# chain reusing record_hash() above. Editing e.g. a hypothesis breaks verify_registry_chain.

import yaml  # noqa: E402

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent.parent / "research" / "registry.yaml"

IMMUTABLE_FIELDS = ("id", "created", "hypothesis", "mechanism", "universe", "window",
                    "metric", "threshold", "analysis_plan_sha")
VALID_STATUS = ("REGISTERED", "TESTING", "FAILED", "PASSED", "RETIRED")
# forward-only transitions — a status may advance, never revert
_ALLOWED_TRANSITIONS = {
    "REGISTERED": {"TESTING", "RETIRED"},
    "TESTING": {"FAILED", "PASSED", "RETIRED"},
    "PASSED": {"RETIRED"},
    "FAILED": {"RETIRED"},
    "RETIRED": set(),
}


def entry_content_hash(entry: dict, prev_hash: str) -> str:
    """Hash over the IMMUTABLE fields only (status/result_ref advance, so are excluded)."""
    body = {k: entry.get(k) for k in IMMUTABLE_FIELDS}
    return record_hash(prev_hash, body)


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text()) or {}).get("entries", [])


def _save_registry(entries: list[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump({"entries": entries}, sort_keys=False, allow_unicode=True))


def verify_registry_chain(entries: list[dict]) -> tuple[bool, str | None]:
    """Recompute each entry's content hash from its immutable fields; verify linkage."""
    prev = GENESIS_HASH
    for i, e in enumerate(entries):
        who = e.get("id", i)
        if e.get("prev_hash") != prev:
            return False, f"entry {who}: prev_hash mismatch (insert/reorder/delete)"
        if e.get("content_hash") != entry_content_hash(e, e["prev_hash"]):
            return False, f"entry {who}: content_hash mismatch (an immutable field was edited)"
        prev = e["content_hash"]
    return True, None


def add_entry(fields: dict, path: str | Path = DEFAULT_REGISTRY) -> dict:
    """Append a new hypothesis entry. Refuses if any immutable field is missing/empty."""
    missing = [f for f in IMMUTABLE_FIELDS if not fields.get(f)]
    if missing:
        raise ValueError(f"cannot register: missing required field(s) {missing} — "
                         "a hypothesis needs id, a testable sentence, mechanism, universe, "
                         "window, metric, threshold, and a frozen analysis_plan_sha")
    status = fields.get("status", "REGISTERED")
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUS}")
    entries = load_registry(path)
    if any(e["id"] == fields["id"] for e in entries):
        raise ValueError(f"entry id {fields['id']!r} already exists (append-only)")
    prev = entries[-1]["content_hash"] if entries else GENESIS_HASH
    entry = {k: fields[k] for k in IMMUTABLE_FIELDS}
    entry["status"] = status
    entry["result_ref"] = fields.get("result_ref")
    entry["status_events"] = [{"ts": fields["created"], "status": status}]
    entry["prev_hash"] = prev
    entry["content_hash"] = entry_content_hash(entry, prev)
    entries.append(entry)
    _save_registry(entries, path)
    return entry


def advance_status(entry_id: str, new_status: str, result_ref: str | None = None,
                   ts: str = "", path: str | Path = DEFAULT_REGISTRY) -> dict:
    """Advance an entry's status (append an event, never edit). Forward-only."""
    if new_status not in VALID_STATUS:
        raise ValueError(f"invalid status {new_status!r}")
    entries = load_registry(path)
    for e in entries:
        if e["id"] == entry_id:
            cur = e.get("status", "REGISTERED")
            if new_status not in _ALLOWED_TRANSITIONS.get(cur, set()):
                raise ValueError(f"illegal transition {cur} → {new_status} (forward-only)")
            e["status"] = new_status
            if result_ref:
                e["result_ref"] = result_ref
            e.setdefault("status_events", []).append(
                {"ts": ts, "status": new_status, "result_ref": result_ref})
            _save_registry(entries, path)   # content_hash unaffected — immutable core intact
            return e
    raise ValueError(f"entry {entry_id!r} not found")


def registry_stats(entries: list[dict]) -> dict:
    """The honesty dashboard: m (total ever), current Bonferroni alpha, pass rate."""
    from src.research.corrections import bonferroni_alpha
    m = len(entries)
    resolved = [e for e in entries if e.get("status") in ("PASSED", "FAILED")]
    passed = [e for e in entries if e.get("status") == "PASSED"]
    return {"m": m, "alpha": bonferroni_alpha(m) if m else None,
            "pass_rate": (len(passed) / len(resolved)) if resolved else 0.0,
            "passed": len(passed), "resolved": len(resolved)}
