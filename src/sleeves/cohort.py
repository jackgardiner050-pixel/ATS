"""Generalized cohort validation for the sleeve layer.

This is the GENERALIZED superset of the protocol-locked paper_trading._validate_cohort
(which stays untouched, still accepting only legacy_pre_fix / cohort_1 for the Oracle
paper book) and phaethon.schema (phaethon_a / phaethon_b). It accepts:
  * the sleeve pattern  {sleeve_id}_c{n}   e.g. oracle_v1_c1, momentum_v2_c3
  * the existing literals: legacy_pre_fix, cohort_1, phaethon_*

Alias: cohort_1 is the legacy alias of oracle_v1_c1. Both are accepted; comparison is via
canonical_cohort(); stored cohort_1 records are NOT rewritten — new sleeve records are
written new-style (oracle_v1_c1) only.
"""
from __future__ import annotations

import re

SLEEVE_COHORT_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*_c\d+$")
PHAETHON_COHORT_RE = re.compile(r"^phaethon_[a-z0-9]+$")
LEGACY_LITERALS = ("legacy_pre_fix", "cohort_1")

# cohort_1 (locked Oracle book) == oracle_v1_c1 (new sleeve style). Comparison alias only.
COHORT_ALIASES = {"cohort_1": "oracle_v1_c1"}


def canonical_cohort(tag: str) -> str:
    """Resolve a legacy alias to its new-style form for EQUALITY comparison only.
    Never used to rewrite a stored record."""
    return COHORT_ALIASES.get(tag, tag)


def is_valid_cohort(tag: object) -> bool:
    if not isinstance(tag, str) or not tag:
        return False
    return (tag in LEGACY_LITERALS
            or bool(PHAETHON_COHORT_RE.match(tag))
            or bool(SLEEVE_COHORT_RE.match(tag)))


def validate_cohort(tag: object) -> None:
    if not is_valid_cohort(tag):
        raise ValueError(
            f"invalid cohort {tag!r}: expected {'{sleeve_id}_c{n}'} (e.g. oracle_v1_c1), "
            f"phaethon_*, or one of {LEGACY_LITERALS}")


def cohort_tag(sleeve_id: str, n: int = 1) -> str:
    """Canonical new-style cohort tag for a sleeve."""
    return f"{sleeve_id}_c{n}"


def same_cohort(a: str, b: str) -> bool:
    """True if two tags denote the same cohort (through the alias)."""
    return canonical_cohort(a) == canonical_cohort(b)
