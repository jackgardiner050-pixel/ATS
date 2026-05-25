"""Rule-based materiality and noise filters. Pure functions — no I/O.

Phase A: filters use rule logic only (item codes, thresholds).
Phase B: 8-K catalysts also pass through classifier.py (Haiku).

Hard rule: LLM never invents numbers — all decisions are rule-based or
use Haiku output only to classify, never to choose trade parameters.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def is_material_8k(catalyst: dict, phase_b_enabled: bool = False) -> bool:
    """Return True if an 8-K catalyst passes the materiality filter.

    Phase A: True if any high-priority item code (1.01, 2.01) is present.
    Phase B: True if Haiku classification says material=True AND confidence >= 0.6.
    """
    if phase_b_enabled:
        classification = catalyst.get("classification", {})
        if classification:
            return (
                classification.get("material", False)
                and float(classification.get("confidence", 0)) >= 0.6
            )
    # Phase A fallback: high-priority item codes
    return catalyst.get("high_priority", False)


def is_material_fda(catalyst: dict) -> bool:
    """FDA approvals are always material — no additional filter needed."""
    return catalyst.get("catalyst_type") == "FDA_APPROVAL"


def is_material_earnings(catalyst: dict, min_beat_pct: float = 5.0) -> bool:
    """Earnings beat is material if EPS beat ≥ threshold AND revenue also beat."""
    if catalyst.get("catalyst_type") != "EARNINGS_BEAT":
        return False
    beat_pct = catalyst.get("eps_beat_pct", 0)
    rev_beat = catalyst.get("revenue_beat", False)
    return float(beat_pct) >= min_beat_pct and rev_beat


def is_material_volume(catalyst: dict, min_ratio: float = 3.0) -> bool:
    """Volume spike is material if ratio ≥ threshold."""
    if catalyst.get("catalyst_type") != "VOLUME_SPIKE":
        return False
    return float(catalyst.get("volume_ratio", 0)) >= min_ratio


def is_negative_8k(catalyst: dict) -> bool:
    """Return True if an 8-K catalyst signals a negative event (for exit signal reversal).

    Phase A: True if item code 5.02 (leadership change) with no M&A items.
    Phase B: True if Haiku classification category is negative.
    """
    classification = catalyst.get("classification", {})
    if classification:
        cat = classification.get("category", "")
        return cat in ("earnings_miss", "regulatory_action", "executive_departure", "legal")
    # Phase A: 5.02 alone (departure without deal) is potentially negative
    items = set(catalyst.get("items", []))
    return "5.02" in items and not (items & {"1.01", "2.01"})


def passes_all_filters(
    catalyst: dict,
    phase_b_enabled: bool = False,
    min_earnings_beat_pct: float = 5.0,
    min_volume_ratio: float = 3.0,
) -> bool:
    """Return True if the catalyst passes its type-specific materiality filter."""
    ctype = catalyst.get("catalyst_type", "")
    if ctype == "8K":
        return is_material_8k(catalyst, phase_b_enabled)
    if ctype == "FDA_APPROVAL":
        return is_material_fda(catalyst)
    if ctype == "EARNINGS_BEAT":
        return is_material_earnings(catalyst, min_earnings_beat_pct)
    if ctype == "VOLUME_SPIKE":
        return is_material_volume(catalyst, min_volume_ratio)
    return False
