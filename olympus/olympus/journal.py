"""Olympus journal (Phase 4) — trader-memory pattern, adapted (not forked).

The named `trader-memory-core` skill isn't installed locally, so this adapts the pattern onto
Mnemosyne / the existing decision ledger: every Zeus decision and every autonomous paper action
is journaled, dated, with its rationale, the council summary, the constraint that bound
confidence, and the mandate actions. It DERIVES from the real ledgers (no duplicate store).
Paper/advisory.
"""
from __future__ import annotations

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER


def entries() -> list[dict]:
    out = []
    for e in storage.decisions():
        if e.get("kind") == "GENESIS":
            continue
        zd = (e.get("detail") or {}).get("zeus_decision", {})
        out.append({
            "date": e["date"], "seq": e["seq"], "type": "decision",
            "ticker": zd.get("candidate_id", "").split("_")[-1], "decision": zd.get("decision"),
            "conviction": zd.get("conviction_pct"),
            "rationale": (zd.get("thesis_summary") or "")[:240],
            "council_summary": zd.get("evidence_independence", ""),
            "binding_constraint": zd.get("confidence_constrained_by", []),
            "counter_case": (zd.get("strongest_counter_case") or "")[:200],
        })
    for e in storage.fills():
        if e.get("kind") == "GENESIS":
            continue
        f = (e.get("detail") or {}).get("fill", {})
        out.append({
            "date": e["date"], "seq": e["seq"], "type": "paper_action",
            "ticker": f.get("ticker"), "action": f.get("side"), "shares": f.get("shares"),
            "reason": f.get("reason"), "is_mandate": "mandate" in (f.get("reason") or ""),
            "cost": f.get("cost_dollars"), "mode": f.get("mode"),
        })
    for e in storage.overrides():
        if e.get("kind") == "GENESIS":
            continue
        o = (e.get("detail") or {}).get("override", {})
        out.append({"date": e["date"], "seq": e["seq"], "type": "override",
                    "decision_id": o.get("decision_id"), "zeus": o.get("zeus_decision"),
                    "human": o.get("human_action"), "rationale": o.get("rationale")})
    return sorted(out, key=lambda x: (x["date"], x["type"]))


def render() -> str:
    L = ["# Olympus Journal", "*dated record of every decision + autonomous paper action "
         "(built on Mnemosyne / the decision ledger)*", ""]
    for j in entries():
        if j["type"] == "decision":
            L += [f"## {j['date']} · DECISION · {j['ticker']} → **{j['decision']}** "
                  f"(conviction {j.get('conviction')}%)",
                  f"- Rationale: {j['rationale']}",
                  f"- Constraint that bound confidence: {'; '.join(j['binding_constraint']) or 'none'}",
                  f"- Council: {j['council_summary'][:200]}",
                  f"- Counter-case: {j['counter_case']}", ""]
        elif j["type"] == "paper_action":
            tag = "MANDATE" if j["is_mandate"] else "TRADE"
            L += [f"## {j['date']} · {tag} ({j['mode']}) · {j['action']} {j['shares']} {j['ticker']}",
                  f"- {j['reason']} · cost ${j['cost']}", ""]
        else:
            L += [f"## {j['date']} · OVERRIDE · {j['decision_id']}: Zeus {j['zeus']} → human {j['human']}",
                  f"- {j['rationale']}", ""]
    if len(L) <= 3:
        L += ["_No journal entries yet._", ""]
    L += [f"> {ADVISORY_FOOTER}"]
    return "\n".join(L) + "\n"
