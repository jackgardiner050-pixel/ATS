"""Tyche (§4.4) — convert a governed decision into a proposed allocation.

The hard limits are NOT re-implemented here: Tyche calls the REAL governance engines —
`src.governance.concentration_governor.assess_proposed_position` (blocking limits + human
override) and `src.portfolio.survivability_engine.compute_survivability` (fragility gate).
No confidence level overrides survivability; the honest default size is 0% (research/watchlist).
"""
from __future__ import annotations

import yaml

from olympus.core import config
from olympus.core.constants import ALLOCATION_BANDS, MAX_INITIAL, MAX_SINGLE, band_for
from olympus.models.records import AllocationProposal

from src.governance import concentration_governor as CG   # REAL blocking limits
from src.portfolio import survivability_engine as SURV     # REAL fragility gate


def _satellite_tickers() -> list[str]:
    data = yaml.safe_load(config.SATELLITE_POSITIONS.read_text())
    return [p["ticker"] for p in data.get("positions", []) if "ticker" in p]


def _conf_tier(conviction_pct: int, reduce_confidence: bool) -> str:
    if reduce_confidence or conviction_pct < 55:
        return "LOW"
    return "HIGH" if conviction_pct >= 70 else "MED"


def size(thesis: dict, critique, *, candidate_id: str, satellite_tickers: list[str] | None = None) -> AllocationProposal:
    ticker = thesis["ticker"]
    # In the autonomous paper loop the satellite is the loop's OWN paper book; otherwise the
    # real/Themis book. Either way the REAL concentration governor runs on it.
    sat = satellite_tickers if satellite_tickers is not None else _satellite_tickers()
    tier = _conf_tier(thesis["conviction_pct"], critique.reduce_confidence)

    # REAL governance: would adding this name breach hard concentration limits?
    gov = CG.assess_proposed_position(sat, ticker, candidate_confidence_tier=tier)
    # REAL survivability of the prospective portfolio.
    surv = SURV.compute_survivability(sat + [ticker])
    surv_score = getattr(surv, "score", None)

    band = band_for(thesis["evidence_grade"], thesis["conviction_pct"])
    lo, hi = ALLOCATION_BANDS[band]

    breaches = list(gov.block_reasons)
    override_required = gov.override_required
    # Hard caps + the discipline gates collapse size to 0 when warranted.
    target = min(hi, MAX_SINGLE)
    initial = min(lo if lo > 0 else hi, MAX_INITIAL)
    if gov.is_blocked:
        target = initial = 0.0
    if isinstance(surv_score, (int, float)) and surv_score < 40:
        breaches.append(f"survivability {surv_score:.0f}/100 is fragile — no confidence overrides survivability")
        target = initial = min(target, 0.0)
    # A HOLD/REDUCE/EXIT thesis is not a new buy: size stays at 0 initial (manage existing only).
    if thesis["bias"] in ("HOLD", "REDUCE", "EXIT"):
        initial = 0.0

    return AllocationProposal(
        allocation_id=f"alloc_{candidate_id}", candidate_id=candidate_id, band=band,
        target_allocation=round(target, 4), initial_allocation=round(initial, 4),
        max_allocation=MAX_SINGLE, cash_impact=round(-initial, 4),
        limit_breaches=breaches, survivability_score=surv_score,
        override_required=override_required, override_instruction=gov.override_instruction,
    )
