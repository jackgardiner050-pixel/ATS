"""Override audit (§12.4) — Zeus decision vs human action vs subsequent outcome.

Reads the real Olympus decision, override, and outcome ledgers and pairs them by decision_id.
A human is free to override Zeus; this report tracks whether the override helped.
"""
from __future__ import annotations

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER


def build() -> dict:
    decisions = {(_zd(e) or {}).get("decision_id"): _zd(e)
                 for e in storage.decisions() if e.get("kind") != "GENESIS"}
    overrides = [e["detail"]["override"] for e in storage.overrides()
                 if e.get("detail", {}).get("override")]
    outcomes = {o["decision_id"]: o for o in
                (e["detail"]["outcome"] for e in storage.outcomes() if e.get("detail", {}).get("outcome"))}
    rows = []
    for ov in overrides:
        did = ov.get("decision_id")
        zd = decisions.get(did, {})
        out = outcomes.get(did, {})
        rows.append({
            "decision_id": did,
            "zeus_decision": ov.get("zeus_decision") or zd.get("decision"),
            "human_action": ov.get("human_action"),
            "rationale": ov.get("rationale"),
            "outcome_relative_return_pct": out.get("relative_return"),
            "classification": out.get("skill_luck_beta_classification", "unresolved"),
        })
    return {"n_overrides": len(rows), "rows": rows}


def _zd(entry):
    return (entry.get("detail", {}) or {}).get("zeus_decision")


def render(a: dict) -> str:
    L = ["# Override Audit — Zeus vs Human", ""]
    if not a["rows"]:
        L += ["No human overrides recorded yet. (Zeus recommends; the human decides — "
              "`olympus override add` records a divergence.)"]
    for r in a["rows"]:
        L += [f"## {r['decision_id']}",
              f"- Zeus: **{r['zeus_decision']}** → Human: **{r['human_action']}**",
              f"- Rationale: {r['rationale']}",
              f"- Outcome (vs ACWI): {r['outcome_relative_return_pct']}% · {r['classification']}", ""]
    L += ["", f"> {ADVISORY_FOOTER}"]
    return "\n".join(L) + "\n"
