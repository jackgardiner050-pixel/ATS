"""Monthly roll-up (Phase 4) — decisions, outcomes, calibration, proposed rule changes.

Summarises the month and PROPOSES rule changes — flagged for human approval, NEVER auto-applied
(observational learning only, per the constitution). Builds on the journal, post-mortems, and
the forward scorecard.
"""
from __future__ import annotations

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER
from olympus.reports import forward_scorecard
from olympus import journal, postmortem


def build(*, fetch: bool = True) -> dict:
    j = journal.entries()
    decisions = [x for x in j if x["type"] == "decision"]
    actions = [x for x in j if x["type"] == "paper_action"]
    pms = postmortem.build()
    sc = forward_scorecard.build(fetch=fetch)

    # PROPOSED rule changes — derived from observation, never applied. Human decides.
    proposals = []
    if sc["research_grade"]:
        proposals.append("Insufficient resolved decisions — make NO rule changes; keep collecting (research-grade).")
    worked = [p for p in pms if p["verdict"] == "worked"]
    luck = [p for p in pms if p["classification"] == "luck"]
    if luck:
        proposals.append(f"{len(luck)} winner(s) classified LUCK — do NOT raise sizing on the pattern; treat as noise.")
    if decisions and all(d["decision"] == "HOLD" for d in decisions):
        proposals.append("All decisions were HOLD/'buy the ETF' — the disciplined null. Consider whether the "
                         "candidate pipeline is too narrow (observation only).")

    return {
        "n_decisions": len(decisions), "decision_mix": _mix(decisions),
        "n_paper_actions": len(actions), "n_postmortems": len(pms),
        "postmortem_verdicts": _verdicts(pms),
        "calibration_by_band": sc["calibration_by_band"], "research_grade": sc["research_grade"],
        "proposed_rule_changes": proposals,
    }


def _mix(decisions):
    m = {}
    for d in decisions:
        m[d["decision"]] = m.get(d["decision"], 0) + 1
    return m


def _verdicts(pms):
    v = {}
    for p in pms:
        v[p["verdict"]] = v.get(p["verdict"], 0) + 1
    return v


def render(r: dict) -> str:
    L = [
        "# Olympus Monthly Roll-up", "",
        f"## Decisions: {r['n_decisions']}  ·  mix {r['decision_mix']}",
        f"## Autonomous paper actions: {r['n_paper_actions']}",
        f"## Post-mortems: {r['n_postmortems']}  ·  verdicts {r['postmortem_verdicts']}",
        f"## Calibration by confidence band: {r['calibration_by_band']}",
        f"## Research-grade: {r['research_grade']}",
        "",
        "## Proposed rule changes (FLAGGED FOR HUMAN APPROVAL — never auto-applied)",
        *([f"- {p}" for p in r["proposed_rule_changes"]] or ["- none"]),
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
