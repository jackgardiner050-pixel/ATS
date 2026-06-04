"""Fail-closed loader for the locked Actionable-bar pre-registration.

The bar is pre-registered and LOCKED: its sha256 is checked on load. Any edit to the YAML (e.g.
an attempt to iteratively lower the bar) breaks the hash and raises SpecIntegrityError — the
recalibration is one-time by construction.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent


class SpecIntegrityError(RuntimeError):
    """The pre-registration file does not match its locked hash (or is missing)."""


@lru_cache(maxsize=None)
def load_spec(name: str = "actionable_bar_v1") -> dict:
    y = _HERE / f"{name}.yaml"
    h = _HERE / f"{name}.yaml.sha256"
    if not y.exists() or not h.exists():
        raise SpecIntegrityError(f"pre-registration {name} missing ({y} / {h}).")
    digest = hashlib.sha256(y.read_bytes()).hexdigest()
    expected = h.read_text().strip()
    if digest != expected:
        raise SpecIntegrityError(
            f"{name}: hash mismatch — the locked Actionable bar was edited "
            f"(got {digest[:12]}…, expected {expected[:12]}…). One-time lock: refusing.")
    return yaml.safe_load(y.read_text())
