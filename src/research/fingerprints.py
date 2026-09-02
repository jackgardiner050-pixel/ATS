"""Mechanism fingerprinting & retirement-registry matching.

Fingerprints characterize a mechanism by six controlled-vocabulary fields, enabling
early detection of functional equivalence to already-retired mechanisms.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

# Distance threshold: fingerprints at distance ≤ MATCH_THRESHOLD warrant a written
# justification in the functional_equivalence_check per B-16 §E.6.
MATCH_THRESHOLD = 2

# Default path to retired.yaml
RETIRED_PATH = Path(__file__).resolve().parent.parent.parent / "research" / "retired.yaml"

# Controlled vocabulary — used consistently across fingerprints and retired.yaml
SIGNAL_FAMILIES = (
    "price_momentum", "mean_reversion", "post_earnings_drift", "event_8k",
    "catalyst_momentum", "fx_carry", "fx_trend", "fx_value", "value_cross_sectional",
    "crash_derisk_overlay", "volatility_premium", "thematic_momentum", "llm_agent",
)

LOOKBACK_CLASSES = ("none", "short", "medium", "long")  # ≤1m, 1-12m, >12m
HORIZON_CLASSES = ("intraday", "days", "weeks", "months", "quarters")
UNIVERSE_CLASSES = (
    "us_large_cap", "us_all_cap", "us_events", "g10_fx", "global_equity", "single_stock_vol",
)
ACTION_TYPES = ("long_only", "long_short", "market_neutral", "overlay_derisk", "basket_select")
CONDITIONINGS = (
    "unconditional", "earnings_event", "8k_event", "catalyst", "regime", "drawdown_trigger",
)


def validate_fingerprint(fp: dict) -> None:
    """Raise ValueError if fingerprint has invalid or missing fields."""
    required = ("signal_family", "lookback_class", "horizon_class", "universe_class",
                "action_type", "conditioning")
    missing = [k for k in required if k not in fp]
    if missing:
        raise ValueError(f"fingerprint missing required field(s): {missing}")

    if fp["signal_family"] not in SIGNAL_FAMILIES:
        raise ValueError(f"invalid signal_family '{fp['signal_family']}'; "
                         f"expected one of {SIGNAL_FAMILIES}")
    if fp["lookback_class"] not in LOOKBACK_CLASSES:
        raise ValueError(f"invalid lookback_class '{fp['lookback_class']}'")
    if fp["horizon_class"] not in HORIZON_CLASSES:
        raise ValueError(f"invalid horizon_class '{fp['horizon_class']}'")
    if fp["universe_class"] not in UNIVERSE_CLASSES:
        raise ValueError(f"invalid universe_class '{fp['universe_class']}'")
    if fp["action_type"] not in ACTION_TYPES:
        raise ValueError(f"invalid action_type '{fp['action_type']}'")
    if fp["conditioning"] not in CONDITIONINGS:
        raise ValueError(f"invalid conditioning '{fp['conditioning']}'")


def _load_retired_yaml(path: str | Path) -> dict:
    """Load retired.yaml as YAML, return {records: [...]}."""
    p = Path(path)
    if not p.exists():
        return {"records": []}
    d = yaml.safe_load(p.read_text()) or {}
    return {"records": d.get("records", [])}


def load_retired_records(path: str | Path = None) -> list[dict]:
    """Load retired mechanism records. Default path: research/retired.yaml."""
    if path is None:
        path = RETIRED_PATH
    doc = _load_retired_yaml(path)
    return doc["records"]


def _fingerprint_distance(fp1: dict, fp2: dict) -> int:
    """Hamming distance: count fields that differ between two fingerprints."""
    fields = ("signal_family", "lookback_class", "horizon_class", "universe_class",
              "action_type", "conditioning")
    return sum(1 for f in fields if fp1.get(f) != fp2.get(f))


def fingerprint_match(candidate_fp: dict,
                      retired_path: str | Path = None) -> list[tuple[str, int]]:
    """Compare candidate fingerprint against retired mechanisms.

    Returns list of (retired_id, distance) sorted by ascending distance, where
    distance = number of differing fields (0 = identical, 6 = fully distinct).
    """
    validate_fingerprint(candidate_fp)

    records = load_retired_records(retired_path)
    matches = []
    for rec in records:
        retired_fp = rec.get("fingerprint", {})
        if not retired_fp:
            continue
        dist = _fingerprint_distance(candidate_fp, retired_fp)
        matches.append((rec["id"], dist))

    return sorted(matches, key=lambda x: x[1])


def closest_retired(candidate_fp: dict,
                    retired_path: str | Path = None) -> tuple[str, int] | None:
    """Find the single closest retired mechanism, or None if no matches."""
    matches = fingerprint_match(candidate_fp, retired_path)
    return matches[0] if matches else None


# ─── Chain verification for retired.yaml (reuses registry.py semantics) ──

def _canonical(payload: dict) -> str:
    """Canonical JSON: sorted keys, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def retired_record_hash(prev_hash: str, record: dict) -> str:
    """Hash a retired record: sha256(prev_hash + canonical-json(payload)).

    NOTE: This hashes the FULL record payload (all fields). This is distinct from
    registry.entry_content_hash which hashes only immutable fields. We name it
    'content_hash' to mirror the chain field names, but document that it is a
    full-payload hash.
    """
    # Remove chain fields from payload before hashing
    body = {k: v for k, v in record.items() if k not in ("prev_hash", "content_hash")}
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def verify_retired_chain(path: str | Path = RETIRED_PATH) -> tuple[bool, str | None]:
    """Verify the retired.yaml chain: genesis prev_hash, linkage, and content hashes.

    Returns (ok, error_msg). If broken, error_msg names the problematic record.
    """
    GENESIS_HASH = "0" * 64
    prev = GENESIS_HASH
    records = load_retired_records(path)
    for i, rec in enumerate(records):
        rec_id = rec.get("id", f"record {i}")
        if rec.get("prev_hash") != prev:
            return False, f"record {i} ({rec_id}): prev_hash mismatch"
        if rec.get("content_hash") != retired_record_hash(rec["prev_hash"], rec):
            return False, f"record {i} ({rec_id}): content_hash mismatch (tampered)"
        prev = rec["content_hash"]
    return True, None


def append_retired_record(record: dict, path: str | Path = RETIRED_PATH) -> dict:
    """Append a retired record to the chain, filling prev_hash and content_hash.

    Returns the stored record with chain fields filled in.
    """
    GENESIS_HASH = "0" * 64
    doc = _load_retired_yaml(path)
    records = doc["records"]

    # Get previous hash
    prev = records[-1]["content_hash"] if records else GENESIS_HASH

    # Build stored record (excluding chain fields, then add them)
    stored = {k: v for k, v in record.items() if k not in ("prev_hash", "content_hash")}
    stored["prev_hash"] = prev
    stored["content_hash"] = retired_record_hash(prev, stored)

    # Append to YAML
    records.append(stored)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump({"records": records}, sort_keys=False, allow_unicode=True))

    return stored
