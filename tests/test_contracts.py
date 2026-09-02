"""Evidence contract schema v1 — model-level tests (workstream B-12)."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.contracts import (  # noqa: E402
    SCHEMA_VERSION,
    AttackReport,
    EvidenceBase,
    ForecastRecord,
    RatingEvidence,
    ReconciliationRecord,
    Stage1Result,
    ValuationRecord,
)


def _envelope() -> dict:
    """Minimal valid EvidenceBase field set."""
    return dict(
        trace_id="t-1",
        ids={"ticker": "AGX", "run_id": "r-1"},
        created_at=datetime(2026, 9, 2, 13, 47, tzinfo=timezone.utc),
        data_tier="B",
        source_ids=["runs/AGX/20260902_134700"],
        component="oracle.rating",
        component_version="3.0.0",
    )


# minimal payloads for each concrete model, on top of _envelope()
_MODELS = {
    EvidenceBase: {},
    ValuationRecord: dict(
        price_target=227.7,
        expected_return=0.11,
        method_values={"dcf_gordon": 169.1, "comps_median_ev_ebitda": 238.4},
    ),
    RatingEvidence: dict(
        rating="BUY",
        confidence_tier="MED",
        confidence_reasons=["thin_peer_cohort"],
        expected_return=0.11,
        bands={"strong_buy": 0.20, "buy": 0.10, "hold": -0.05, "sell": -0.20},
    ),
    Stage1Result: dict(
        verdict="CONTINUE",
        checks={"liquidity": "pass"},
        registry_ref="003",  # data_tier comes from _envelope() (also an EvidenceBase field)
    ),
    AttackReport: dict(
        attacks_run=["cherry_pick"],
        findings=[{"kind": "none"}],
        candidate_ref="cand-1",
    ),
    ReconciliationRecord: dict(
        status="MATCH",
        expected_actions=[{"a": 1}],
        observed_actions=[{"a": 1}],
        diffs=[],
    ),
    ForecastRecord: dict(
        horizon_days=63,
        predictions={"AGX": 0.1},
        model_ref="m-1",
    ),
}


@pytest.mark.parametrize("model,payload", list(_MODELS.items()), ids=lambda x: getattr(x, "__name__", ""))
def test_minimal_instantiation_and_roundtrip(model, payload):
    inst = model(**_envelope(), **payload)
    dumped = inst.model_dump()
    restored = model.model_validate(dumped)
    assert restored == inst
    assert restored.model_dump() == dumped


@pytest.mark.parametrize("model,payload", list(_MODELS.items()), ids=lambda x: getattr(x, "__name__", ""))
def test_json_mode_roundtrip(model, payload):
    inst = model(**_envelope(), **payload)
    restored = model.model_validate(inst.model_dump(mode="json"))
    assert restored == inst


@pytest.mark.parametrize("model,payload", list(_MODELS.items()), ids=lambda x: getattr(x, "__name__", ""))
def test_extra_forbid_rejects_unknown_key(model, payload):
    with pytest.raises(Exception) as exc:
        model(**_envelope(), **payload, totally_unexpected_key=1)
    assert "totally_unexpected_key" in str(exc.value)


@pytest.mark.parametrize("model,payload", list(_MODELS.items()), ids=lambda x: getattr(x, "__name__", ""))
def test_schema_version_default_present(model, payload):
    inst = model(**_envelope(), **payload)
    assert inst.schema_version == "contracts/v1"
    assert SCHEMA_VERSION == "contracts/v1"
    assert "schema_version" in inst.model_dump()


# ── EvidenceBase field validators ────────────────────────────────────────────
def test_confidence_out_of_unit_interval_rejected():
    for bad in (-0.01, 1.01, 5.0):
        with pytest.raises(Exception):
            EvidenceBase(**_envelope(), confidence=bad)
    # valid values accepted (including the boundaries and None)
    EvidenceBase(**_envelope(), confidence=0.0)
    EvidenceBase(**_envelope(), confidence=1.0)
    EvidenceBase(**_envelope(), confidence=None)


def test_data_tier_enum_enforced():
    env = _envelope()
    env["data_tier"] = "D"
    with pytest.raises(Exception):
        EvidenceBase(**env)


def test_failure_status_enum_enforced():
    with pytest.raises(Exception):
        EvidenceBase(**_envelope(), failure_status="exploded")
    assert EvidenceBase(**_envelope()).failure_status == "ok"


def test_missing_required_field_rejected():
    env = _envelope()
    del env["trace_id"]
    with pytest.raises(Exception):
        EvidenceBase(**env)


def test_rating_evidence_out_of_enum_rating_rejected():
    with pytest.raises(Exception):
        RatingEvidence(
            **_envelope(),
            rating="MEGA_BUY",
            confidence_tier="MED",
            confidence_reasons=[],
            expected_return=0.1,
            bands={},
        )


def test_pit_cutoff_accepts_date_and_none():
    a = EvidenceBase(**_envelope(), pit_cutoff=date(2026, 6, 30))
    assert a.pit_cutoff == date(2026, 6, 30)
    assert EvidenceBase(**_envelope()).pit_cutoff is None


def test_importable_from_package_root():
    from src.contracts import (  # noqa: F401
        AttackReport,
        EvidenceBase,
        ForecastRecord,
        RatingEvidence,
        ReconciliationRecord,
        Stage1Result,
        ValuationRecord,
    )
