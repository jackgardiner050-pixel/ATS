"""Review-eligibility check (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY, step 1).

A boundary review is eligible only when BOTH floors are cleared — this is the
information-triggered (not calendar-triggered) cadence from the decision memo §5.1:
  ≥ REVIEW_MIN_CLOSED closed trades since the last WINDOW_BOUNDARY, AND
  ≥ REVIEW_MIN_WEEKS  weeks elapsed since it.
Both are required, not either. For the first-ever review, the reference point is
Phaethon's inception (earliest journal record).

HUMAN-SIDE ONLY — never imported by Phaethon's live context path.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.phaethon.journal import (
    exits_since_last_boundary, inception_ts, parse_ts,
)

REVIEW_MIN_CLOSED = 25     # closed trades since last review
REVIEW_MIN_WEEKS = 13.0    # weeks elapsed since last review (calendar floor)


def is_review_eligible(records: list[dict], now: datetime | None = None):
    """Return (eligible, closed_since_last, weeks_since_last, reason).

    Eligible iff closed_since_last >= REVIEW_MIN_CLOSED AND weeks_since_last >= REVIEW_MIN_WEEKS.
    Note (memo §5, kill-switch step 6): eligibility is computed even when learning is
    SUSPENDED — suspension blocks *adoption*, not observation. This function does not
    consult the suspension sentinel.
    """
    now = now or datetime.now(timezone.utc)
    exits, lb = exits_since_last_boundary(records)
    closed = len(exits)

    ref = parse_ts(lb["ts"]) if lb is not None else inception_ts(records)
    if ref is None:
        return False, closed, 0.0, "journal empty — no boundary or inception reference"

    weeks = round((now - ref).days / 7.0, 2)
    origin = "last boundary" if lb is not None else "inception (first-ever review)"
    gates = []
    if closed < REVIEW_MIN_CLOSED:
        gates.append(f"closed {closed} < {REVIEW_MIN_CLOSED}")
    if weeks < REVIEW_MIN_WEEKS:
        gates.append(f"weeks {weeks} < {REVIEW_MIN_WEEKS}")

    if not gates:
        reason = f"ELIGIBLE — {closed} closed and {weeks}w since {origin} (both floors met)"
        return True, closed, weeks, reason
    return False, closed, weeks, f"not eligible — {'; '.join(gates)} (since {origin})"
