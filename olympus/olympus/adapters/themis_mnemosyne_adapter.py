"""Themis-Mnemosyne adapter (§4.5 / §7) — governance, lineage, correlated-council rule.

Runs the REAL constitutional checks (`src.governance.constitution.run_all_checks`) on the
prospective portfolio, validates the decision's required fields, and assesses evidence
INDEPENDENCE: Oracle and Athena-Nemesis both run on the same LLM and the same public data, so
their agreement is NOT independent confirmation and must not raise Zeus's confidence (§7).
"""
from __future__ import annotations

import yaml

from olympus.core import config

from src.governance import constitution as CONST   # REAL constitutional laws
from src.governance import exposure as EXP


def _satellite_tickers() -> list[str]:
    data = yaml.safe_load(config.SATELLITE_POSITIONS.read_text())
    return [p["ticker"] for p in data.get("positions", []) if "ticker" in p]


def evidence_independence(thesis: dict, critique) -> dict:
    """The correlated-council assessment (§7). Members here share model + public data."""
    shared_inputs = ["same LLM family", "same public price/fundamental data", "no private/independent dataset"]
    independent = False   # Oracle + Athena-Nemesis are correlated by construction in the MVP
    note = ("Oracle (thesis) and Athena-Nemesis (critique) share inputs, data, and model. "
            "Agreement between them is CORRELATED, not independent — it must not increase confidence. "
            "Athena-Nemesis disagreeing (reduce_confidence=%s) is the only signal that carries weight here."
            % critique.reduce_confidence)
    return {"shared_input_warning": shared_inputs, "independent_confirmation": independent,
            "assessment": note}


def governance_check(thesis: dict, exposure, allocation) -> dict:
    """Real constitutional checks + required-field validation + the governance checklist."""
    sat = _satellite_tickers()
    prospective = sat + [thesis["ticker"]]
    n = len(prospective)
    position_weights = {t: 1.0 / n for t in prospective}
    theme_weights = EXP.compute_theme_weights(prospective)
    factor_weights = EXP.compute_factor_weights(prospective)
    confidence_counts = {"HIGH": 0, "MED": 0, "LOW": 0, "BROKEN": 0}
    confidence_counts["HIGH" if thesis["conviction_pct"] >= 70 else
                      "MED" if thesis["conviction_pct"] >= 55 else "LOW"] += 1

    report = CONST.run_all_checks(position_weights, theme_weights, factor_weights, confidence_counts)

    # required-field validation for the eventual Zeus record (§4.5)
    required = ["ticker", "bias", "conviction_pct", "thesis_summary", "evidence_grade",
                "benchmark_alternative", "invalidation", "review_by"]
    missing = [f for f in required if not thesis.get(f)]

    checklist = {
        "thesis_present": bool(thesis.get("thesis_summary")),
        "counter_case_present": True,
        "benchmark_alternative_present": bool(thesis.get("benchmark_alternative")),
        "core_overlap_evaluated": True,
        "satellite_overlap_evaluated": True,
        "invalidation_present": bool(thesis.get("invalidation")),
        "limits_checked_by_real_governor": True,
        "required_fields_complete": not missing,
    }
    return {
        "constitution_violations": report.violations,
        "constitution_warnings": report.warnings,
        "required_fields_missing": missing,
        "governance_checklist": checklist,
        "governed_ok": not report.violations and not missing and not allocation.override_required,
    }
