"""Phaethon holding/trade schema — cohort validation for the two arms.

Kept in src/phaethon (NOT paper_trading.VALID_COHORTS, which is protocol-locked): the
Phaethon cohorts phaethon_a / phaethon_b live here so the two systems' cohort spaces
stay separate and this doesn't require a lock re-registration.
"""
from __future__ import annotations

from src.phaethon import PHAETHON_COHORTS

_NUMBER = (int, float)
_HOLDING_SCHEMA = {"ticker": str, "cohort": str, "last": _NUMBER, "weight_pct": _NUMBER}


def validate_phaethon_holding(record: object) -> None:
    """Assert a Phaethon holding/trade record has the required keys/types and a valid
    Phaethon cohort. Raises ValueError otherwise (no silent defaulting)."""
    if not isinstance(record, dict):
        raise ValueError(f"phaethon record is not a mapping (got {type(record).__name__})")
    for key, types in _HOLDING_SCHEMA.items():
        if key not in record:
            raise ValueError(f"phaethon record missing required key '{key}'")
        if not isinstance(record[key], types):
            raise ValueError(f"phaethon key '{key}' has wrong type {type(record[key]).__name__}")
    if record["cohort"] not in PHAETHON_COHORTS:
        raise ValueError(
            f"phaethon record has invalid cohort {record['cohort']!r}; "
            f"expected one of {PHAETHON_COHORTS}")
