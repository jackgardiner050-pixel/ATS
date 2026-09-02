"""Evidence contract schema v1 — pydantic v2 models (workstream B-12).

Every component in the Olympus research pipeline emits a *record* that carries,
alongside its payload, a shared evidence envelope (`EvidenceBase`): provenance,
point-in-time boundary, data tier, versions, confidence / uncertainty, and
failure status. Downstream consumers (the council ledger, reconciliation,
attack harness, forecaster) can then reason about *how much to trust* a record
without re-deriving it.

`model_config = ConfigDict(extra="forbid")` on every model so a malformed record
fails loud rather than silently carrying an unexpected key.

Producing component / consuming backlog item is named in each model's docstring.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

SCHEMA_VERSION = "contracts/v1"

# DEFAULT_RATING_BANDS mirrors the hardcoded fallback literal used by
# src/engine/calculator.classify_rating when no bands= argument is supplied.
# The fallback literal (`{"strong_buy": 0.20, "buy": 0.10, "hold": -0.05, "sell": -0.20}`)
# is the actual runtime source of truth. config/settings.yaml:rating_bands currently agrees
# but is NOT read by any code path — it is dead config. Duplicated here so the adapter
# can populate RatingEvidence.bands when the Oracle output does not persist the bands it used.
# NOT imported from calculator — this module must not touch protocol-locked code.
DEFAULT_RATING_BANDS: dict[str, float] = {
    "strong_buy": 0.20,
    "buy": 0.10,
    "hold": -0.05,
    "sell": -0.20,
}


class EvidenceBase(BaseModel):
    """Shared evidence envelope wrapped around every pipeline record (B-12).

    Consumed by: every downstream contract below, and (droplet follow-up) the
    council ledger append validation in olympus/core/storage.py.
    """

    # protected_namespaces=() disables pydantic's default model_* field protection.
    # A no-op on pydantic ≥2.10 (installed: 2.13.4), kept only for <2.10 compat.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    # ── Identity / provenance ────────────────────────────────────────────────
    trace_id: str
    ids: dict                      # free-form identifiers, e.g. {ticker, run_id}
    created_at: datetime
    pit_cutoff: date | None = None  # point-in-time data boundary
    data_tier: Literal["A", "B", "C"]
    source_ids: list[str]
    component: str
    component_version: str
    prompt_version: str | None = None
    model_version: str | None = None
    schema_version: str = SCHEMA_VERSION

    # ── Lineage ──────────────────────────────────────────────────────────────
    upstream_trace_ids: list[str] = []

    # ── Confidence / uncertainty ─────────────────────────────────────────────
    confidence: float | None = None      # scalar in [0, 1] if present
    uncertainty: dict | None = None
    assumptions: list[str] = []
    contradiction_flags: list[str] = []
    abstention: bool = False
    stale_flags: list[str] = []
    failure_status: Literal["ok", "degraded", "failed"] = "ok"
    consumer: str | None = None

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {v!r}")
        return v


class ValuationRecord(EvidenceBase):
    """Deterministic valuation output — DCF + comps → price target (B-12).

    Produced by: the Oracle valuation layer (src/engine/calculator.py via
    src/agents/valuation.py), mapped post-hoc by contracts/oracle_adapter.py.
    Consumed by: RatingEvidence.valuation_ref, and downstream council sizing.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    price_target: float
    expected_return: float
    method_values: dict[str, float]  # dcf_gordon, dcf_exit, comps_median, ...
    sector: str | None = None
    sector_calibration_status: Literal["CALIBRATED", "UNCALIBRATED", "NA"] = "NA"


class RatingEvidence(EvidenceBase):
    """The Oracle judgement output — rating + confidence tier (B-12).

    Produced by: Oracle (src/engine/calculator.classify_rating /
    assess_confidence, assembled in src/orchestrator.run_pipeline), mapped
    post-hoc by contracts/oracle_adapter.to_rating_evidence.
    Consumed by: the council ledger / Zeus decision layer.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    rating: Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
    confidence_tier: Literal["HIGH", "MED", "LOW", "BROKEN"]
    confidence_reasons: list[str]
    expected_return: float
    bands: dict[str, float]
    valuation_ref: str | None = None  # trace_id of the ValuationRecord


class Stage1Result(EvidenceBase):
    """Stage-1 triage verdict — DEAD / CONTINUE gate (defined for B-15).

    Produced by: the Stage-1 screen (not yet wired in this repo).
    Consumed by: B-15.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    verdict: Literal["DEAD", "CONTINUE"]
    checks: dict[str, str]
    registry_ref: str


class AttackReport(EvidenceBase):
    """Adversarial attack-harness output over a candidate (defined for B-18).

    Produced by: the attack harness (not yet wired in this repo).
    Consumed by: B-18.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    attacks_run: list[str]
    findings: list[dict]
    miss_rate: float | None = None
    candidate_ref: str


class ReconciliationRecord(EvidenceBase):
    """Expected-vs-observed action reconciliation (defined for B-13).

    Produced by: the reconciliation job (not yet wired in this repo).
    Consumed by: B-13.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    status: Literal["MATCH", "EXPLAINED", "INVESTIGATE"]
    expected_actions: list[dict]
    observed_actions: list[dict]
    diffs: list[dict]


class ForecastRecord(EvidenceBase):
    """Forward-looking prediction record over a horizon (defined for B-19).

    Produced by: the forecaster (not yet wired in this repo).
    Consumed by: B-19.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    horizon_days: int
    predictions: dict
    metrics: dict | None = None
    model_ref: str


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_RATING_BANDS",
    "EvidenceBase",
    "ValuationRecord",
    "RatingEvidence",
    "Stage1Result",
    "AttackReport",
    "ReconciliationRecord",
    "ForecastRecord",
]
