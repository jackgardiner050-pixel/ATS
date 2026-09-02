"""Post-hoc adapter: wrap Oracle's recommendation output in evidence contracts.

The "Oracle output" in this repo is the ``recommendation.json`` dict assembled
by ``src.orchestrator.run_pipeline`` (Stage 5), and may be post-mutated by
``scripts/run_universe.py:_update_recommendation_json`` which overwrites
``confidence`` with a signal-escalated tier and adds ``confidence_before_signals``
and ``signal_alignment``.

For names screened via ``run_universe.py``, the ``confidence`` (legacy) tier
will be post-escalation while ``confidence_reasons`` remain pre-escalation —
a known vintage mismatch. This adapter preserves both for auditability.

Shape example:

    {
      "ticker": "AGX",
      "company_name": "Argan Inc",
      "valuation_date": "20260902_134700",       # datetime.utcnow().strftime
      "current_price": 700.0,
      "rating": "STRONG_BUY",                     # classify_rating(...)
      "confidence": "HIGH",                       # assess_confidence(...) tier (post-escalation if via run_universe.py)
      "confidence_flags": ["methods_converge_tightly", ...],
      "confidence_before_signals": "MED",        # legacy tier before run_universe.py escalation (if present)
      "signal_alignment": 0.85,                  # signal alignment score (if present)
      "price_target_12m": 812.0,
      "expected_return": 0.16,
      "confidence_v2": "MED_HIGH",                # assess_confidence_v2(...) tier
      "confidence_v2_flags": [...],
      "fixed_numbers": { "dcf_price_gordon": ..., "dcf_price_exit": ..., ... },
      ...
    }

This module performs a **pure field mapping** from that dict into
``RatingEvidence`` / ``ValuationRecord``. It does NOT call ``classify_rating`` or
``assess_confidence`` and recomputes nothing — it only relabels what Oracle
already produced. It never imports or mutates protocol-locked code
(``src/engine/calculator.py``, ``src/paper_trading.py``).

Not wired into the live screen/loop in this round — provided as an adapter plus
a golden test proving the wrap is lossless and additive. Wiring is a follow-up.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .models import DEFAULT_RATING_BANDS, RatingEvidence, ValuationRecord

_ORACLE_TS_FORMAT = "%Y%m%d_%H%M%S"


def _parse_created_at(oracle_output: dict, created_at: datetime | None) -> datetime:
    if created_at is not None:
        return created_at
    raw = oracle_output.get("valuation_date")
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw, _ORACLE_TS_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _default_trace_id(oracle_output: dict) -> str:
    ticker = str(oracle_output.get("ticker", "UNK")).upper()
    stamp = oracle_output.get("valuation_date")
    if not stamp:
        stamp = datetime.now(timezone.utc).isoformat()
    return f"oracle:{ticker}:{stamp}"


def _envelope_kwargs(
    oracle_output: dict,
    *,
    trace_id: str | None,
    created_at: datetime | None,
    component: str,
    component_version: str,
    data_tier: str,
    consumer: str | None,
    upstream_trace_ids: list[str] | None,
) -> dict[str, Any]:
    """Fields common to every evidence record produced from an Oracle output."""
    run_dir = oracle_output.get("_run_dir")
    files = oracle_output.get("files") or {}
    source_ids = [str(v) for v in ([run_dir] if run_dir else []) + list(files.values())]

    ids = {
        "ticker": str(oracle_output.get("ticker", "")).upper() or None,
        "company_name": oracle_output.get("company_name"),
        "valuation_date": oracle_output.get("valuation_date"),
        "run_dir": run_dir,
    }

    return {
        "trace_id": trace_id or _default_trace_id(oracle_output),
        "ids": ids,
        "created_at": _parse_created_at(oracle_output, created_at),
        "pit_cutoff": None,  # Oracle output records no explicit PIT boundary today
        "data_tier": data_tier,
        "source_ids": source_ids,
        "component": component,
        "component_version": component_version,
        "prompt_version": None,   # Oracle rating math is LLM-free
        "model_version": None,
        "upstream_trace_ids": list(upstream_trace_ids or []),
        "consumer": consumer,
    }


def to_valuation_record(
    oracle_output: dict,
    *,
    trace_id: str | None = None,
    created_at: datetime | None = None,
    component: str = "oracle.valuation",
    component_version: str = "unknown",
    data_tier: str = "B",
    consumer: str | None = None,
    upstream_trace_ids: list[str] | None = None,
) -> ValuationRecord:
    """Map the valuation half of an Oracle output into a ``ValuationRecord``.

    Pure relabelling of ``oracle_output`` (and its nested ``fixed_numbers``).
    Nothing is recomputed.
    """
    fixed = oracle_output.get("fixed_numbers") or {}

    method_values: dict[str, float] = {}
    for src_key, dst_key in (
        ("dcf_price_gordon", "dcf_gordon"),
        ("dcf_price_exit", "dcf_exit"),
        ("dcf_price_blended", "dcf_blended"),
        ("comps_price_median_ev_ebitda", "comps_median_ev_ebitda"),
        ("comps_price_75th_ev_ebitda", "comps_75th_ev_ebitda"),
        ("comps_price_median_pe", "comps_median_pe"),
    ):
        if src_key in fixed and fixed[src_key] is not None:
            method_values[dst_key] = float(fixed[src_key])

    envelope = _envelope_kwargs(
        oracle_output,
        trace_id=trace_id,
        created_at=created_at,
        component=component,
        component_version=component_version,
        data_tier=data_tier,
        consumer=consumer,
        upstream_trace_ids=upstream_trace_ids,
    )
    if trace_id is None:
        envelope["trace_id"] = envelope["trace_id"] + ":valuation"

    return ValuationRecord(
        **envelope,
        price_target=oracle_output["price_target_12m"],
        expected_return=oracle_output["expected_return"],
        method_values=method_values,
        sector=oracle_output.get("sector"),
        sector_calibration_status=oracle_output.get("sector_calibration_status", "NA"),
    )


def to_rating_evidence(
    oracle_output: dict,
    *,
    trace_id: str | None = None,
    created_at: datetime | None = None,
    component: str = "oracle.rating",
    component_version: str = "unknown",
    data_tier: str = "B",
    consumer: str | None = None,
    valuation_ref: str | None = None,
    bands: dict[str, float] | None = None,
    upstream_trace_ids: list[str] | None = None,
) -> RatingEvidence:
    """Map an Oracle ``recommendation.json`` dict into a ``RatingEvidence``.

    Pure field mapping — no call to ``classify_rating`` / ``assess_confidence``,
    no recomputation. ``rating``, ``confidence_tier`` (from the legacy
    ``confidence`` tier), ``expected_return``, ``bands`` and ``confidence_reasons``
    (from ``confidence_flags``) are copied verbatim.

    ``bands``: the Oracle output does not persist the rating bands it used, so
    they are taken from the ``bands=`` argument, else an explicit ``rating_bands``
    / ``bands`` key on the output, else ``DEFAULT_RATING_BANDS`` (which mirrors the
    hardcoded fallback literal in ``src/engine/calculator.classify_rating``, the
    actual runtime source of truth).

    The richer 5-tier ``confidence_v2`` output does not fit the 4-tier
    ``confidence_tier`` Literal; it is preserved under ``uncertainty`` so nothing
    is dropped.
    """
    resolved_bands = (
        bands
        if bands
        else oracle_output.get("rating_bands")
        or oracle_output.get("bands")
        or dict(DEFAULT_RATING_BANDS)
    )

    uncertainty: dict[str, Any] = {}
    if "confidence_v2" in oracle_output:
        uncertainty["confidence_v2"] = oracle_output["confidence_v2"]
    if "confidence_v2_flags" in oracle_output:
        uncertainty["confidence_v2_flags"] = list(oracle_output.get("confidence_v2_flags") or [])
    if "confidence_before_signals" in oracle_output:
        uncertainty["confidence_before_signals"] = oracle_output["confidence_before_signals"]
    if "signal_alignment" in oracle_output:
        uncertainty["signal_alignment"] = oracle_output["signal_alignment"]

    # Detect when confidence_v2 and legacy confidence_tier disagree in direction
    contradiction_flags = []
    legacy_tier = oracle_output.get("confidence")
    v2_tier = oracle_output.get("confidence_v2")
    if (legacy_tier and v2_tier and
        legacy_tier not in ("BROKEN",) and v2_tier not in ("BROKEN",)):
        # Map v2's 5 tiers onto legacy 3 levels
        v2_to_legacy = {
            "HIGH": "HIGH",
            "MED_HIGH": "HIGH",
            "MED": "MED",
            "MED_LOW": "LOW",
            "LOW": "LOW",
        }
        collapsed_v2 = v2_to_legacy.get(v2_tier)
        if collapsed_v2 and collapsed_v2 != legacy_tier:
            contradiction_flags.append("confidence_v2_disagrees_with_legacy_tier")

    envelope = _envelope_kwargs(
        oracle_output,
        trace_id=trace_id,
        created_at=created_at,
        component=component,
        component_version=component_version,
        data_tier=data_tier,
        consumer=consumer,
        upstream_trace_ids=upstream_trace_ids,
    )
    if trace_id is None:
        envelope["trace_id"] = envelope["trace_id"] + ":rating"

    return RatingEvidence(
        **envelope,
        uncertainty=uncertainty or None,
        rating=oracle_output["rating"],
        confidence_tier=oracle_output["confidence"],
        confidence_reasons=list(oracle_output.get("confidence_flags") or []),
        expected_return=oracle_output["expected_return"],
        bands=resolved_bands,
        valuation_ref=valuation_ref,
        contradiction_flags=contradiction_flags,
    )


__all__ = ["to_rating_evidence", "to_valuation_record"]
