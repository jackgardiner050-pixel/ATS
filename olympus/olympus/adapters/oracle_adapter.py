"""Oracle adapter — wraps the EXISTING ~/labs/oracle in place (does not fork it).

Reads candidates straight from Oracle's real hash-chained forward-test ledger
(`oracle_forward_test.jsonl`). The thin slice runs against the ORCL entry already logged there,
so this exercises the genuine Oracle→Olympus seam against real data, not a fixture.
"""
from __future__ import annotations

from typing import Optional

from olympus.core import config  # noqa: F401  (wires ~/labs onto sys.path)
from olympus.core.constants import EVIDENCE_LABELS
from olympus.models.records import Candidate

from oracle import forward_test as FT   # the real Oracle module


def list_candidates() -> list[dict]:
    """Every name currently in Oracle's forward-test book (latest rating each)."""
    return [e["detail"]["rating"] for e in FT.open_ratings() if e.get("detail", {}).get("rating")]


def get_rating(ticker: str) -> Optional[dict]:
    for r in list_candidates():
        if r["ticker"].upper() == ticker.upper():
            return r
    return None


def _evidence_grade(rating: dict) -> str:
    """Derive an evidence grade from the real Oracle fields (priced-in + right-but-early)."""
    rbe = rating.get("right_but_early_risk", "MED")
    stance = (rating.get("priced_in") or {}).get("stance", "MIXED")
    if rbe == "HIGH" or stance == "MIXED":
        return "weak"
    if stance == "NON_CONSENSUS" and rbe == "LOW":
        return "strong"
    return "moderate"


def to_candidate(rating: dict) -> Candidate:
    return Candidate(
        candidate_id=f"oracle_{rating['as_of_date'].replace('-', '')}_{rating['ticker']}",
        ticker=rating["ticker"], name=rating["ticker"], asset_type="single_name",
        theme=(rating.get("overlap_with_core") or {}).get("text", "")[:60] or "unclassified",
        source="oracle:forward_test", discovery_date=rating["as_of_date"], status="actionable",
    )


def rate_fresh(ticker: str) -> dict:
    """Oracle reasons FROM SCRATCH on a naked discovered ticker — from PUBLIC data only.

    No pre-existing ledger entry, and crucially NO discovery signal (the momentum screener's
    score never reaches here). Bias is derived from free valuation/fundamentals. This is a
    DEGRADED, data-only path (no human/LLM causal thesis) — explicitly RESEARCH-GRADE — so the
    honest default is a low-conviction HOLD unless the public data clearly supports otherwise.
    """
    from datetime import date as _date
    from oracle import priced_in as PI
    pi, val, surv, info = PI.pull(ticker, [])          # free data; no peers
    fcf, fpe = info.get("freeCashflow"), info.get("forwardPE")
    fragile = isinstance(fcf, (int, float)) and fcf < 0
    rich = isinstance(fpe, (int, float)) and fpe > 30
    cheap = isinstance(fpe, (int, float)) and 0 < fpe < 18
    if cheap and not fragile:
        bias, conv, grade = "BUY", 56, "data-only"
    else:
        bias, conv, grade = "HOLD", (50 if (fragile and rich) else 52), "weak"
    return {
        "ticker": ticker, "bias": bias, "conviction_pct": conv, "horizon": "6–12 months",
        "thesis_summary": (f"Auto data-only rating for discovered candidate {ticker} (RESEARCH-GRADE; "
                           f"no causal thesis). Bias from PUBLIC valuation/fundamentals only — "
                           f"fwdPE={fpe}, FCF{'<0' if fragile else '≥0'}. The discovery source's signal is NOT used."),
        "evidence_grade": grade,
        "benchmark_alternative": {"priced_in_stance": pi.stance, "assessment": pi.assessment},
        "invalidation": "fundamentals deteriorate (FCF turns negative / leverage rises) or valuation re-rates",
        "review_by": "next quarter", "overlap_is_more_ai": False, "diversifying": True,
        "claim_labels": {"valuation": "Evidence", "fundamentals": "Evidence", "conviction_pct": "Opinion"},
        "as_of_date": _date.today().isoformat(),
        "_raw": {"ticker": ticker, "as_of_date": _date.today().isoformat(), "fresh": True},
    }


def thesis_view(rating: dict) -> dict:
    """A normalised thesis view for downstream members, with every claim evidence-labelled (§4.1)."""
    pi, ov = rating.get("priced_in") or {}, rating.get("overlap_with_core") or {}
    return {
        "ticker": rating["ticker"],
        "bias": rating["bias"],
        "conviction_pct": rating["conviction_pct"],
        "horizon": rating.get("horizon", ""),
        "thesis_summary": rating.get("causal_thesis", ""),
        "evidence_grade": _evidence_grade(rating),
        "benchmark_alternative": {"priced_in_stance": pi.get("stance"),
                                  "assessment": pi.get("assessment")},
        "invalidation": (rating.get("invalidation") or {}).get("line", ""),
        "review_by": (rating.get("invalidation") or {}).get("by_when", ""),
        "overlap_is_more_ai": ov.get("is_more_ai"),
        "diversifying": ov.get("diversifying"),
        # §4.1 labelling: causal thesis = Hypothesis; priced-in gauge = Evidence; the rest as given.
        "claim_labels": {"causal_thesis": "Hypothesis", "priced_in": "Evidence",
                         "conviction_pct": "Opinion", "valuation": "Evidence"},
        "evidence_labels_vocab": EVIDENCE_LABELS,
        "_raw": rating,
    }
