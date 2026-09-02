"""Evidence contract schema v1 (workstream B-12).

Import models directly from this package:

    from src.contracts import EvidenceBase, RatingEvidence, ValuationRecord

The Oracle output adapter lives in `src.contracts.oracle_adapter` and is
intentionally NOT re-exported so `import src.contracts` stays free of
src/engine imports. Callers do: `from src.contracts.oracle_adapter import to_rating_evidence`.
"""
from __future__ import annotations

from .models import (
    DEFAULT_RATING_BANDS,
    SCHEMA_VERSION,
    AttackReport,
    EvidenceBase,
    ForecastRecord,
    RatingEvidence,
    ReconciliationRecord,
    Stage1Result,
    ValuationRecord,
)

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
