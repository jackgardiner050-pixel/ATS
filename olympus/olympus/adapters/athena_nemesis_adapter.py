"""Athena-Nemesis adapter (§4.2) — wraps the EXISTING critique code in place.

Real critique via `awareness.athena.pre_mortem` (deterministic first-principles screen; the
LLM narrative is optional and gated, so the thin slice runs with no API key). The agent-side
LLM red team `src.governance.adversarial.run_adversarial_review` is the heavier counter-case
that plugs in here when an API key is present — referenced, not stubbed.
"""
from __future__ import annotations

from olympus.core import config  # noqa: F401  (sys.path)
from olympus.models.records import Critique

from awareness import athena   # the real pre-mortem critic


def critique(thesis: dict, *, candidate_id: str, use_llm: bool = False) -> Critique:
    idea = f"{thesis['bias']} {thesis['ticker']}: {thesis['thesis_summary']}"
    pm = athena.pre_mortem(idea, use_llm=use_llm)   # REAL deterministic screen (real keys below)

    failures = [f"{f['mode']}: {f['why']}" for f in pm.get("most_likely_failures", [])]
    retreads = [f"re-tread of {r['of']} — {r['verdict']} ({r['cite']})" for r in pm.get("retreads", [])]

    counter = pm.get("llm_narrative") or pm.get("honest_prior", "")
    if retreads:
        counter = "; ".join(retreads) + ". " + counter

    break_conditions = [thesis["invalidation"]] if thesis.get("invalidation") else []
    reduce_conf = bool(pm.get("is_retread")) or thesis.get("evidence_grade") == "weak" or len(failures) > 1

    return Critique(
        critique_id=f"crit_{candidate_id}",
        thesis_ref=candidate_id,
        counter_case=counter,
        hidden_assumptions=[f"thesis assumes the catalyst resolves in its favour "
                            f"(priced-in stance: {thesis.get('benchmark_alternative', {}).get('priced_in_stance')})"],
        evidence_gaps=pm.get("required_harness_tests", []) or
                      ["paid-data screens (revision breadth, concentration) unavailable"],
        failure_scenarios=failures or ["right-but-early: correct thesis, wrong timing"],
        thesis_break_conditions=break_conditions,
        reduce_confidence=reduce_conf,
    )
