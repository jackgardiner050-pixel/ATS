"""Olympus post-mortem (Phase 4) — signal-postmortem pattern, adapted (not forked).

When a decision/position resolves (or at review), classify it vs its thesis (worked / didn't /
why), tag skill vs luck vs beta vs factor, and note thesis drift. Written to a hash-chained
post-mortem ledger; it FEEDS the success audit and calibration (which read the outcome ledger —
the post-mortem adds the narrative verdict + drift on top). Never auto-applies anything.
"""
from __future__ import annotations

from datetime import date

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER
from olympus.models.records import ForwardOutcome   # noqa: F401  (shared vocab)

VERDICTS = ("worked", "didnt_work", "partial", "unresolved")
CLASSES = ("skill", "luck", "beta", "factor", "unresolved")


def record(*, decision_id: str, ticker: str, verdict: str, classification: str,
           why: str, thesis_drift: str, notes: str = "") -> dict:
    assert verdict in VERDICTS, f"verdict must be one of {VERDICTS}"
    assert classification in CLASSES, f"classification must be one of {CLASSES}"
    pm = {"postmortem_id": f"pm_{decision_id}_{date.today().isoformat()}", "decision_id": decision_id,
          "ticker": ticker, "verdict": verdict, "classification": classification, "why": why,
          "thesis_drift": thesis_drift, "notes": notes, "date": date.today().isoformat()}
    return storage.append_postmortem(pm, ticker=ticker)


def build() -> list[dict]:
    return [e["detail"]["postmortem"] for e in storage.postmortems()
            if e.get("detail", {}).get("postmortem")]


def render() -> str:
    pms = build()
    L = ["# Olympus Post-Mortems", "*resolved decisions classified vs thesis — feeds success audit + calibration*", ""]
    if not pms:
        L += ["_No post-mortems recorded yet. (When a decision resolves: `olympus postmortem add`.)_", ""]
    for p in pms:
        L += [f"## {p['date']} · {p['ticker']} ({p['decision_id']}) — **{p['verdict'].upper()}** · {p['classification']}",
              f"- Why: {p['why']}",
              f"- Thesis drift: {p['thesis_drift']}",
              *([f"- Notes: {p['notes']}"] if p.get("notes") else []), ""]
    L += [f"> {ADVISORY_FOOTER}"]
    return "\n".join(L) + "\n"
