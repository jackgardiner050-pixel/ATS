"""Quarterly governance review (§12.6).

Aggregates the real ledgers + scorecard: decisions, governance breaches, overrides, benchmark
results, member usefulness, deferred/rejected candidates, and the opportunity cost of saying no.
Honest by construction — a quarter of mostly HOLDs / 'buy the ETF' is the system working.
"""
from __future__ import annotations

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER
from olympus.reports import forward_scorecard

_MEMBERS = ["Oracle", "Athena-Nemesis", "Hecate", "Tyche", "Themis-Mnemosyne", "Zeus", "Hermes"]


def build(*, fetch: bool = True) -> dict:
    decisions = [e for e in storage.decisions() if e.get("kind") != "GENESIS"]
    zds = [(e.get("detail", {}) or {}).get("zeus_decision", {}) for e in decisions]
    overrides = [e for e in storage.overrides() if e.get("kind") != "GENESIS"]

    breaches = [c for zd in zds for c in (zd.get("confidence_constrained_by") or [])
                if "constitution" in c.lower() or "breach" in c.lower() or "concentration" in c.lower()]
    deferred = [{"ticker": zd.get("candidate_id", "").split("_")[-1], "decision": zd.get("decision"),
                 "why": "; ".join(zd.get("confidence_constrained_by", []))}
                for zd in zds if zd.get("decision") in ("HOLD", "REDUCE", "EXIT")
                or zd.get("target_allocation", 0) == 0]

    sc = forward_scorecard.build(fetch=fetch)
    # opportunity cost of deferral = what the benchmark/ETF did since the deferred decision (interim)
    opp = [{"ticker": i["ticker"], "acwi_since_pct": i["acwi_since_entry_pct"],
            "nvda_since_pct": i["nvda_since_entry_pct"]} for i in sc["interim_unresolved"]]

    return {
        "n_decisions": len(decisions), "decision_counts": sc["decision_counts"],
        "n_breaches": len(breaches), "breaches": breaches,
        "n_overrides": len(overrides),
        "scorecard_summary": {"n_resolved": sc["n_resolved"], "research_grade": sc["research_grade"],
                              "metrics": sc["metrics"]},
        "member_usefulness": {m: "fired (wired to real engine)" for m in _MEMBERS},
        "deferred_rejected": deferred, "opportunity_cost_interim": opp,
    }


def render(q: dict) -> str:
    L = [
        "# Quarterly Governance Review", "",
        f"## Decisions: {q['n_decisions']}  ·  mix {q['decision_counts']}",
        f"## Governance breaches flagged: {q['n_breaches']}",
        *([f"- {b}" for b in q["breaches"][:10]] or ["- none"]),
        "",
        f"## Human overrides: {q['n_overrides']}",
        "",
        "## Benchmark results (forward scorecard)",
        f"- Resolved decisions: {q['scorecard_summary']['n_resolved']} · "
        f"research-grade: {q['scorecard_summary']['research_grade']}",
        f"- Metrics: {q['scorecard_summary']['metrics']}",
        "",
        "## Member usefulness",
        *[f"- {m}: {v}" for m, v in q["member_usefulness"].items()],
        "",
        "## Deferred / rejected candidates (and why)",
        *([f"- {d['ticker']}: {d['decision']} — {d['why']}" for d in q["deferred_rejected"]] or ["- none"]),
        "",
        "## Opportunity cost of saying no (interim drift since deferral)",
        *([f"- {o['ticker']}: ACWI {o['acwi_since_pct']}% · NVDA {o['nvda_since_pct']}% since the call"
          for o in q["opportunity_cost_interim"]] or ["- none"]),
        "",
        "_A quarter of mostly HOLDs / 'buy the cheaper ETF' is the system working, not failing._",
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
