"""Observational feed (v2) — the continually-updating thematic read. OBSERVATIONAL, HUMAN-GATED.

On a schedule it refreshes the theme / bottleneck / catalyst view and LOGS its theme-calls to a
ledger so the thematic read can later be GRADED (was it any good?). It can optionally ask an LLM to
PROPOSE updates to the curated themes file — but it only writes proposals to a separate file; it
NEVER edits `growth_themes.yaml` itself. No self-modification: a human reviews and applies changes.
"""
from __future__ import annotations

import json
from datetime import date

from olympus.core import config
from olympus.discovery.hephaestus import load_themes
from olympus.discovery import catalyst_feed

THEME_CALLS = config.DATA_DIR / "theme_calls.jsonl"        # append-only log of each refresh's read
THEME_PROPOSALS = config.DATA_DIR / "theme_proposals.jsonl"  # human-gated proposals, never auto-applied


def snapshot() -> dict:
    """The current thematic read — one logged 'call' per theme, plus the catalyst awareness list."""
    data = load_themes()
    today = date.today().isoformat()
    calls = []
    for theme, spec in (data.get("themes") or {}).items():
        calls.append({
            "date": today, "theme": theme, "stage": spec.get("stage", "mid"),
            "leaders": [str(t).upper() for t in (spec.get("leaders") or [])],
            "bottlenecks": [str(b.get("ticker")).upper() for b in (spec.get("bottlenecks") or [])
                            if isinstance(b, dict) and b.get("ticker")],
            "n_catalysts": len(spec.get("catalysts") or []),
        })
    return {"as_of": today, "theme_calls": calls, "catalysts": catalyst_feed.upcoming(),
            "mode": "paper/observational"}


def refresh(*, record: bool = True) -> dict:
    """Refresh + LOG the theme-calls (so the read can be graded later). Observational only."""
    snap = snapshot()
    if record:
        THEME_CALLS.parent.mkdir(parents=True, exist_ok=True)
        with THEME_CALLS.open("a") as f:
            for call in snap["theme_calls"]:
                f.write(json.dumps(call) + "\n")
    return snap


def theme_call_history() -> list[dict]:
    if not THEME_CALLS.exists():
        return []
    return [json.loads(l) for l in THEME_CALLS.read_text().splitlines() if l.strip()]


def propose_update(proposal: dict, *, by: str = "observational_feed") -> dict:
    """Record a PROPOSED theme-map change for human review — never edits growth_themes.yaml.

    A proposal is e.g. {action: add_bottleneck, theme: ai_power_grid, ticker: ..., rationale: ...}.
    """
    rec = {**proposal, "proposed_on": date.today().isoformat(), "by": by,
           "status": "PROPOSED_AWAITING_HUMAN", "auto_applied": False}
    THEME_PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    with THEME_PROPOSALS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
