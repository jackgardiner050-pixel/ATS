"""Rating change detection and alert formatting.

Compares this week's screener results against last week's saved snapshot.
Only freshly-screened tickers (status != SKIPPED) are candidates for change alerts.

Hard rule: never invents numbers — all figures come from the supplied data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = Path(__file__).parent.parent.parent / "data" / "last_digest_state.json"


# ─── Quiet hours ─────────────────────────────────────────────────────────────

def is_quiet_hours(
    quiet_start: str = "22:00",
    quiet_end: str = "07:00",
    now: Optional[datetime] = None,
) -> bool:
    """Return True if the current UTC time falls within the quiet window.

    quiet_start and quiet_end are "HH:MM" UTC strings.  The window wraps
    midnight if quiet_start > quiet_end (e.g. 22:00 → 07:00).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    def _minutes(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    current = now.hour * 60 + now.minute
    start = _minutes(quiet_start)
    end = _minutes(quiet_end)

    if start > end:  # wraps midnight
        return current >= start or current < end
    return start <= current < end


# ─── State persistence ────────────────────────────────────────────────────────

def load_last_state(path: Optional[Path] = None) -> dict:
    """Load the last-digest state snapshot. Returns {} if file missing."""
    p = path or _DEFAULT_STATE_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        log.warning("Could not load last_digest_state: %s", exc)
        return {}


def save_current_state(results: list[dict], path: Optional[Path] = None) -> None:
    """Persist current ratings snapshot for next week's change detection."""
    p = path or _DEFAULT_STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ratings = {
        r["ticker"]: {
            "rating": r.get("rating", "?"),
            "confidence": r.get("confidence", "?"),
        }
        for r in results
        if r.get("ok") and r.get("ticker")
    }
    state = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "ratings": ratings,
    }
    p.write_text(json.dumps(state, indent=2))


# ─── Change detection ─────────────────────────────────────────────────────────

def detect_changes(
    current_results: list[dict],
    last_state: dict,
) -> list[dict]:
    """Return a list of rating or confidence changes vs last snapshot.

    Only considers tickers that were freshly screened this run (status != SKIPPED).
    """
    prev_ratings = last_state.get("ratings", {})
    if not prev_ratings:
        return []  # no previous snapshot to compare against

    changes: list[dict] = []
    for r in current_results:
        if not r.get("ok") or r.get("status") in ("SKIPPED", "ERROR"):
            continue
        ticker = r["ticker"]
        prev = prev_ratings.get(ticker)
        if not prev:
            continue  # first time this ticker appeared — not a change

        old_rating = prev.get("rating", "?")
        old_conf = prev.get("confidence", "?")
        new_rating = r.get("rating", "?")
        new_conf = r.get("confidence", "?")

        if old_rating != new_rating or old_conf != new_conf:
            changes.append({
                "ticker": ticker,
                "old_rating": old_rating,
                "old_conf": old_conf,
                "new_rating": new_rating,
                "new_conf": new_conf,
                "momentum_quintile": r.get("momentum_quintile"),
                "revision_direction": r.get("revision_direction"),
                "alignment_score": r.get("alignment_score", ""),
            })

    return changes


def format_change_alert(change: dict) -> str:
    """Format a single rating change as a Telegram alert message."""
    ticker = change["ticker"]
    old = f"{change['old_rating']} [{change['old_conf']}]"
    new = f"{change['new_rating']} [{change['new_conf']}]"

    # Derive a brief reason
    score = change.get("alignment_score", "")
    rev = change.get("revision_direction", "")
    mom = change.get("momentum_quintile")

    reason_parts = []
    if score:
        reason_parts.append(score)
    if rev and rev not in ("FLAT", "NO_COVERAGE"):
        sym = "▲" if rev == "POSITIVE" else "▼"
        reason_parts.append(f"revisions {sym}")
    if mom:
        reason_parts.append(f"mom Q{mom}")
    reason = ", ".join(reason_parts) if reason_parts else "valuation update"

    lines = [
        f"🔔 Rating change — {ticker}",
        f"{old} → {new}",
        f"Trigger: {reason}",
        "",
        f"/ask {ticker} for context",
    ]
    return "\n".join(lines)
