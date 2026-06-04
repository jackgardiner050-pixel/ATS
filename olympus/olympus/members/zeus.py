"""Zeus (§4.6) — final one-page decision synthesis.

Zeus does NOT average member scores and does NOT treat correlated agreement as independent
evidence. It takes Oracle's bias as the anchor, then explicitly CONSTRAINS confidence by the
real findings: weak evidence, crowded/priced idea, high overlap, poor benchmark comparison,
theme concentration, or an unresolved counter-thesis. The honest dominant output is HOLD /
insufficient-evidence / buy-the-cheaper-ETF — Zeus is not tuned to manufacture BUYs.
"""
from __future__ import annotations

from datetime import date

from olympus.models.records import ZeusDecision


def decide(thesis: dict, critique, exposure, allocation, governance: dict,
           independence: dict, hermes_pathway: str, *, candidate_id: str) -> ZeusDecision:
    constraints = []
    if thesis["evidence_grade"] == "weak":
        constraints.append("weak evidence grade")
    if (thesis.get("benchmark_alternative") or {}).get("priced_in_stance") in ("CONSENSUS", "NON_CONSENSUS"):
        constraints.append("idea is largely priced (benchmark/priced-in gauge)")
    if exposure.core_overlap_warnings:
        constraints.append("core overlap — may duplicate existing passive exposure")
    if exposure.theme_exposure_status != "ok":
        constraints.append(f"satellite theme concentration {exposure.theme_exposure_status}")
    if critique.reduce_confidence:
        constraints.append("Athena-Nemesis recommends reducing confidence")
    if not independence["independent_confirmation"]:
        constraints.append("member agreement is correlated, not independent (no confidence uplift)")
    if governance["constitution_violations"]:
        constraints.append("constitutional violations present")

    # Decision: anchor on Oracle's bias; never upgrade a constrained idea to BUY.
    bias = thesis["bias"]
    decision = bias if bias in ("BUY", "HOLD", "REDUCE", "EXIT") else "HOLD"
    # The correlated-council note caps confidence UPLIFT; it does not, alone, block a buy. A BUY is
    # downgraded to HOLD only by SUBSTANTIVE constraints (weak evidence, priced-in, overlap, an
    # unresolved counter-thesis, a constitution violation) or zero size — so the loop isn't inert.
    substantive = [c for c in constraints if "correlated" not in c.lower()]
    if decision == "BUY" and (substantive or allocation.initial_allocation == 0.0):
        decision = "HOLD"   # discipline: substantively constrained or zero-size → do not buy

    # confidence band, constrained downward by the findings
    conv = thesis["conviction_pct"]
    band = "HIGH" if conv >= 70 else "MED" if conv >= 55 else "LOW"
    if len(constraints) >= 3 and band == "MED":
        band = "LOW"

    etf = exposure.etf_alternative
    benchmark = {**(thesis.get("benchmark_alternative") or {}), "etf_alternative": etf}

    return ZeusDecision(
        decision_id=f"zeus_{candidate_id}", candidate_id=candidate_id, thesis_ref=candidate_id,
        date=date.today().isoformat(), decision=decision, confidence_band=band,
        evidence_grade=thesis["evidence_grade"], confidence_constrained_by=constraints,
        thesis_summary=thesis["thesis_summary"], strongest_counter_case=critique.counter_case,
        key_risks=critique.failure_scenarios,
        current_allocation=0.0, target_allocation=allocation.target_allocation,
        max_allocation=allocation.max_allocation, benchmark_alternative=benchmark,
        core_overlap_warning=" · ".join(exposure.core_overlap_warnings) or "none",
        satellite_overlap_warning=" · ".join(exposure.satellite_overlap_warnings) or "none",
        factor_exposure=exposure.factor_weights,
        thesis_break_conditions=critique.thesis_break_conditions,
        review_date=thesis.get("review_by", ""),
        evidence_independence=independence["assessment"],
        hermes_pathway=hermes_pathway, human_authorisation_required=True,
    )
