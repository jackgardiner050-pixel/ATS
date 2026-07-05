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
# F7a — only entries that have INITIATED a test spend statistical credibility; REGISTERED
# (Stage-0) is free. This set is the correction denominator, NOT len(entries).
TESTING_OR_BEYOND = ("TESTING", "FAILED", "PASSED", "RETIRED")
# F5 — every entry must declare what a PASS licenses and the nearest overclaim it does not.
INTERPRETATION_SUBFIELDS = ("licenses", "does_not_license")
# forward-only transitions — a status may advance, never revert
_ALLOWED_TRANSITIONS = {
    "REGISTERED": {"TESTING", "RETIRED"},
    "TESTING": {"FAILED", "PASSED", "RETIRED"},
    "PASSED": {"RETIRED"},
    "FAILED": {"RETIRED"},
    "RETIRED": set(),
}


def entry_content_hash(entry: dict, prev_hash: str) -> str:
    """Hash over the IMMUTABLE fields only. interpretation_contract is deliberately NOT
    immutable (F5): it is backfilled onto 001-003 via an appended SCHEMA_MIGRATION, so
    keeping it out of the hash preserves those entries' content_hashes unchanged."""
    body = {k: entry.get(k) for k in IMMUTABLE_FIELDS}
    return record_hash(prev_hash, body)


def _load_doc(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"entries": [], "migrations": []}
    d = yaml.safe_load(p.read_text()) or {}
    return {"entries": d.get("entries", []), "migrations": d.get("migrations", [])}


def _save_doc(entries: list[dict], migrations: list[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc = {"entries": entries}
    if migrations:
        doc["migrations"] = migrations
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def load_registry_raw(path: str | Path = DEFAULT_REGISTRY) -> list[dict]:
    """Entries exactly as stored (NO migration overlay). Used by the WRITE path so a
    backfilled contract is never persisted back into an entry's record."""
    return _load_doc(path)["entries"]


def load_migrations(path: str | Path = DEFAULT_REGISTRY) -> list[dict]:
    return _load_doc(path)["migrations"]


def _overlay_interpretation(entries: list[dict], migrations: list[dict]) -> list[dict]:
    """Overlay backfilled interpretation_contracts (from SCHEMA_MIGRATION events) onto any
    entry that lacks one inline. Entry records are copied, never mutated in place."""
    backfill: dict[str, dict] = {}
    for mg in migrations:
        if mg.get("type") == "backfill_interpretation_contract":
            backfill.update(mg.get("contracts") or {})
    out = []
    for e in entries:
        e = dict(e)
        if not e.get("interpretation_contract") and e.get("id") in backfill:
            e["interpretation_contract"] = backfill[e["id"]]
        out.append(e)
    return out


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> list[dict]:
    """Entries WITH interpretation_contract resolved (inline or backfilled). Read path."""
    doc = _load_doc(path)
    return _overlay_interpretation(doc["entries"], doc["migrations"])


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


def verify_migration_chain(migrations: list[dict]) -> tuple[bool, str | None]:
    """SCHEMA_MIGRATION events are themselves an append-only hash chain."""
    prev = GENESIS_HASH
    for i, mg in enumerate(migrations):
        if mg.get("prev_hash") != prev:
            return False, f"migration {i}: prev_hash mismatch"
        body = {k: v for k, v in mg.items() if k not in ("prev_hash", "hash")}
        if mg.get("hash") != record_hash(mg["prev_hash"], body):
            return False, f"migration {i}: hash mismatch (tampered)"
        prev = mg["hash"]
    return True, None


def _validate_interpretation_contract(ic: object) -> None:
    if not isinstance(ic, dict):
        raise ValueError("interpretation_contract must be a mapping with "
                         "'licenses' and 'does_not_license'")
    for k in INTERPRETATION_SUBFIELDS:
        if not ic.get(k):
            raise ValueError(f"interpretation_contract missing '{k}' — declare, in plain "
                             "language, what a PASS licenses and the nearest overclaim it does not")


def add_entry(fields: dict, path: str | Path = DEFAULT_REGISTRY) -> dict:
    """Append a new hypothesis entry. Refuses if any immutable field OR the
    interpretation_contract (F5) is missing."""
    missing = [f for f in IMMUTABLE_FIELDS if not fields.get(f)]
    if missing:
        raise ValueError(f"cannot register: missing required field(s) {missing} — "
                         "a hypothesis needs id, a testable sentence, mechanism, universe, "
                         "window, metric, threshold, and a frozen analysis_plan_sha")
    ic = fields.get("interpretation_contract")
    if not ic:
        raise ValueError("cannot register: missing required interpretation_contract "
                         "{licenses, does_not_license} (F5)")
    _validate_interpretation_contract(ic)
    status = fields.get("status", "REGISTERED")
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUS}")
    doc = _load_doc(path)
    entries = doc["entries"]
    if any(e["id"] == fields["id"] for e in entries):
        raise ValueError(f"entry id {fields['id']!r} already exists (append-only)")
    prev = entries[-1]["content_hash"] if entries else GENESIS_HASH
    entry = {k: fields[k] for k in IMMUTABLE_FIELDS}
    entry["status"] = status
    entry["result_ref"] = fields.get("result_ref")
    entry["interpretation_contract"] = ic               # inline, required (not hashed — see F5)
    for opt in ("survival_prior", "strategic_fit"):     # F7d — optional queue inputs
        if fields.get(opt) is not None:
            entry[opt] = fields[opt]
    entry["status_events"] = [{"ts": fields["created"], "status": status}]
    entry["prev_hash"] = prev
    entry["content_hash"] = entry_content_hash(entry, prev)
    entries.append(entry)
    _save_doc(entries, doc["migrations"], path)
    return entry


def add_migration(migration: dict, path: str | Path = DEFAULT_REGISTRY) -> dict:
    """Append a SCHEMA_MIGRATION event (hash-chained). Used to backfill interpretation
    contracts onto pre-existing entries WITHOUT editing those entries (append-only)."""
    doc = _load_doc(path)
    migrations = doc["migrations"]
    body = {k: v for k, v in migration.items() if k not in ("prev_hash", "hash")}
    prev = migrations[-1]["hash"] if migrations else GENESIS_HASH
    rec = {**body, "prev_hash": prev}
    rec["hash"] = record_hash(prev, body)
    migrations.append(rec)
    _save_doc(doc["entries"], migrations, path)
    return rec


def advance_status(entry_id: str, new_status: str, result_ref: str | None = None,
                   ts: str = "", path: str | Path = DEFAULT_REGISTRY) -> dict:
    """Advance an entry's status (append an event, never edit). Forward-only."""
    if new_status not in VALID_STATUS:
        raise ValueError(f"invalid status {new_status!r}")
    doc = _load_doc(path)
    entries = doc["entries"]
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
            _save_doc(entries, doc["migrations"], path)  # content_hash unaffected
            return e
    raise ValueError(f"entry {entry_id!r} not found")


def correction_m(entries: list[dict]) -> int:
    """F7a — the multiple-testing denominator: entries at TESTING or beyond only."""
    return sum(1 for e in entries if e.get("status") in TESTING_OR_BEYOND)


def registry_stats(entries: list[dict]) -> dict:
    """Honesty dashboard. m = correction denominator (TESTING+); total_registered is
    informational (includes REGISTERED Stage-0 entries)."""
    from src.research.corrections import bonferroni_alpha
    m = correction_m(entries)
    resolved = [e for e in entries if e.get("status") in ("PASSED", "FAILED")]
    passed = [e for e in entries if e.get("status") == "PASSED"]
    return {"m": m, "total_registered": len(entries),
            "alpha": bonferroni_alpha(m) if m else None,
            "pass_rate": (len(passed) / len(resolved)) if resolved else 0.0,
            "passed": len(passed), "resolved": len(resolved)}


def queue_priority(entry: dict):
    """F7d — computed (never stored): stated survival prior × cheapness/strategic-fit
    factor if the entry provides one, else the prior alone. None if no prior stated."""
    prior = entry.get("survival_prior")
    if prior is None:
        return None
    return float(prior) * float(entry.get("strategic_fit", 1.0))


def queue(entries: list[dict]) -> list[dict]:
    """F7d — rank REGISTERED (not-yet-TESTING) entries by queue_priority, descending.
    Informational only; advancing to TESTING remains a human act."""
    reg = [e for e in entries if e.get("status") == "REGISTERED"]
    ranked = sorted(reg, key=lambda e: (queue_priority(e) is not None, queue_priority(e) or 0.0),
                    reverse=True)
    return [{"id": e["id"], "queue_priority": queue_priority(e),
             "survival_prior": e.get("survival_prior"),
             "strategic_fit": e.get("strategic_fit", 1.0)} for e in ranked]
