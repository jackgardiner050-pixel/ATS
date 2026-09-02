"""Golden test: wrapping Oracle output in RatingEvidence is lossless + additive.

The fixture tests/fixtures/oracle_recommendation_AGX.json is hand-constructed
to mirror the Stage-5 recommendation.json shape (src/orchestrator.py run_pipeline).
Rating-bearing keys are faithful; deliberately omits Stage-5 keys the adapter ignores:
stress_adjusted_pt, stress_adjusted_upside, upside_gate, fragility_score, dcf_stress,
net_debt_ebitda, model_outputs, notes, and the run_universe.py signal keys.
"""
import json
import sys
from pathlib import Path

import pydantic
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.contracts import DEFAULT_RATING_BANDS, RatingEvidence  # noqa: E402
from src.contracts.oracle_adapter import (  # noqa: E402
    to_rating_evidence,
    to_valuation_record,
)

FIXTURE = Path(__file__).parent / "fixtures" / "oracle_recommendation_AGX.json"


@pytest.fixture
def oracle_output() -> dict:
    return json.loads(FIXTURE.read_text())


# ── (a) lossless: rating-bearing fields copied verbatim ──────────────────────
def test_rating_fields_byte_identical_to_source(oracle_output):
    ev = to_rating_evidence(oracle_output)
    assert ev.rating == oracle_output["rating"]
    assert ev.confidence_tier == oracle_output["confidence"]
    assert ev.expected_return == oracle_output["expected_return"]
    assert ev.confidence_reasons == oracle_output["confidence_flags"]
    assert ev.confidence_reasons is not oracle_output["confidence_flags"]  # copied
    # bands: Oracle output does not persist them -> canonical default
    assert ev.bands == DEFAULT_RATING_BANDS


def test_confidence_v2_preserved_not_dropped(oracle_output):
    # 5-tier confidence_v2 does not fit the 4-tier confidence_tier Literal;
    # it must survive somewhere rather than being silently discarded.
    ev = to_rating_evidence(oracle_output)
    assert ev.uncertainty["confidence_v2"] == oracle_output["confidence_v2"]
    assert ev.uncertainty["confidence_v2_flags"] == oracle_output["confidence_v2_flags"]


def test_bands_argument_and_output_key_override_default(oracle_output):
    custom = {"strong_buy": 0.25, "buy": 0.12, "hold": 0.0, "sell": -0.15}
    assert to_rating_evidence(oracle_output, bands=custom).bands == custom
    with_key = dict(oracle_output, rating_bands=custom)
    assert to_rating_evidence(with_key).bands == custom


# ── (b) round-trip through model_dump() preserves them ───────────────────────
def test_model_dump_roundtrip_preserves_rating_fields(oracle_output):
    ev = to_rating_evidence(oracle_output)
    dumped = ev.model_dump()
    restored = RatingEvidence.model_validate(dumped)
    assert restored == ev
    for f in ("rating", "confidence_tier", "expected_return", "bands", "confidence_reasons"):
        assert getattr(restored, f) == getattr(ev, f)
    # json-mode round-trip too
    assert RatingEvidence.model_validate(ev.model_dump(mode="json")) == ev


# ── (c) malformed records fail loud ─────────────────────────────────────────
def test_missing_required_field_raises(oracle_output):
    bad = dict(oracle_output)
    bad.pop("rating")
    with pytest.raises(KeyError):
        to_rating_evidence(bad)


def test_out_of_enum_rating_raises():
    with pytest.raises(pydantic.ValidationError):
        RatingEvidence(
            trace_id="t", ids={}, created_at="2026-09-02T00:00:00Z",
            data_tier="B", source_ids=[], component="c", component_version="v",
            rating="BUY_BUY_BUY", confidence_tier="MED", confidence_reasons=[],
            expected_return=0.1, bands={},
        )


def test_extra_forbid_violation_raises():
    with pytest.raises(pydantic.ValidationError) as exc:
        RatingEvidence(
            trace_id="t", ids={}, created_at="2026-09-02T00:00:00Z",
            data_tier="B", source_ids=[], component="c", component_version="v",
            rating="BUY", confidence_tier="MED", confidence_reasons=[],
            expected_return=0.1, bands={}, price_target_12m=999.0,  # not a field here
        )
    assert "price_target_12m" in str(exc.value)


# ── the wrap is additive: envelope is populated, payload untouched ───────────
def test_envelope_is_additive_only(oracle_output):
    ev = to_rating_evidence(oracle_output, consumer="zeus.council")
    assert ev.schema_version == "contracts/v1"
    assert ev.component == "oracle.rating"
    assert ev.ids["ticker"] == "AGX"
    assert ev.consumer == "zeus.council"
    assert ev.prompt_version is None and ev.model_version is None  # rating math is LLM-free
    assert ev.pit_cutoff is None
    assert "runs/AGX/20260902_134700" in ev.source_ids


def test_valuation_record_maps_method_values(oracle_output):
    vr = to_valuation_record(oracle_output)
    fixed = oracle_output["fixed_numbers"]
    assert vr.price_target == oracle_output["price_target_12m"]
    assert vr.expected_return == oracle_output["expected_return"]
    assert vr.method_values["dcf_gordon"] == fixed["dcf_price_gordon"]
    assert vr.method_values["dcf_exit"] == fixed["dcf_price_exit"]
    assert vr.method_values["comps_median_ev_ebitda"] == fixed["comps_price_median_ev_ebitda"]
    assert vr.sector is None
    assert vr.sector_calibration_status == "NA"
    assert vr.model_validate(vr.model_dump()) == vr


def test_rating_and_valuation_trace_ids_differ(oracle_output):
    ev = to_rating_evidence(oracle_output)
    vr = to_valuation_record(oracle_output)
    assert ev.trace_id != vr.trace_id
    assert ev.trace_id.endswith(":rating")
    assert vr.trace_id.endswith(":valuation")


# ── FIX 1: confidence_v2_flags is copied, not aliased ──────────────────────
def test_confidence_v2_flags_is_copied_not_aliased(oracle_output):
    """Mutating oracle_output after to_rating_evidence must NOT change ev.uncertainty."""
    ev = to_rating_evidence(oracle_output)
    original_flags = list(ev.uncertainty["confidence_v2_flags"])

    # Mutate the source list
    oracle_output["confidence_v2_flags"].append("mutated_flag")

    # Evidence must be unchanged (copied, not aliased)
    assert ev.uncertainty["confidence_v2_flags"] == original_flags
    assert "mutated_flag" not in ev.uncertainty["confidence_v2_flags"]


# ── FIX 2: confidence_v2 vs legacy-tier disagreement detection ─────────────
def test_confidence_v2_disagrees_with_legacy_tier_agx_fixture(oracle_output):
    """AGX fixture has confidence=MED and confidence_v2=MED_HIGH → should flag."""
    ev = to_rating_evidence(oracle_output)
    # fixture: confidence="MED", confidence_v2="MED_HIGH"
    # MED_HIGH maps to HIGH, which disagrees with MED legacy tier
    assert "confidence_v2_disagrees_with_legacy_tier" in ev.contradiction_flags


def test_confidence_v2_agrees_with_legacy_tier_no_flag():
    """When v2 and legacy tiers agree after mapping, no flag."""
    oracle = json.loads(FIXTURE.read_text())
    # Construct a case where v2=MED matches legacy MED
    oracle["confidence"] = "MED"
    oracle["confidence_v2"] = "MED"
    ev = to_rating_evidence(oracle)
    assert "confidence_v2_disagrees_with_legacy_tier" not in ev.contradiction_flags


def test_confidence_v2_disagrees_no_flag_if_broken():
    """No flag if either tier is BROKEN."""
    oracle = json.loads(FIXTURE.read_text())
    oracle["confidence"] = "BROKEN"
    oracle["confidence_v2"] = "HIGH"
    ev = to_rating_evidence(oracle)
    assert "confidence_v2_disagrees_with_legacy_tier" not in ev.contradiction_flags


# ── FIX 4: confidence_before_signals and signal_alignment are preserved ────
def test_confidence_before_signals_and_signal_alignment_preserved():
    """Keys from run_universe.py post-mutation are carried into uncertainty."""
    oracle = json.loads(FIXTURE.read_text())
    oracle["confidence_before_signals"] = "MED"
    oracle["signal_alignment"] = 0.85

    ev = to_rating_evidence(oracle)
    assert ev.uncertainty["confidence_before_signals"] == "MED"
    assert ev.uncertainty["signal_alignment"] == 0.85
