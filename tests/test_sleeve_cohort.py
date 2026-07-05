"""Generalized sleeve cohort validation + OrderIntentDraft round-trip.

Proves the sleeve layer accepts {sleeve_id}_c{n} + the existing literals + phaethon_*,
and the cohort_1 ↔ oracle_v1_c1 alias — WITHOUT touching the locked paper_trading enum.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.sleeves.cohort import (
    is_valid_cohort, validate_cohort, cohort_tag, canonical_cohort, same_cohort,
)
from src.sleeves.base import Sleeve, OrderIntentDraft


def test_sleeve_pattern_accepted():
    for tag in ("oracle_v1_c1", "momentum_v2_c3", "pead_c10", "a_c1"):
        assert is_valid_cohort(tag), tag
    print("  ✓ {sleeve_id}_c{n} pattern accepted")


def test_existing_literals_accepted():
    for tag in ("legacy_pre_fix", "cohort_1", "phaethon_a", "phaethon_b"):
        assert is_valid_cohort(tag), tag
    print("  ✓ legacy_pre_fix / cohort_1 / phaethon_* still accepted")


def test_garbage_rejected():
    for tag in ("", "Oracle_C1", "random", "c1", "oracle_v1_cx", 123, None):
        assert not is_valid_cohort(tag), tag
    with pytest.raises(ValueError):
        validate_cohort("nope")
    print("  ✓ malformed cohorts rejected (no silent default)")


def test_cohort_1_aliases_oracle_v1_c1():
    assert canonical_cohort("cohort_1") == "oracle_v1_c1"
    assert same_cohort("cohort_1", "oracle_v1_c1")
    assert canonical_cohort("oracle_v1_c1") == "oracle_v1_c1"   # non-alias unchanged
    # accept BOTH, never rewrite: cohort_1 stays cohort_1 as a stored value
    assert is_valid_cohort("cohort_1") and is_valid_cohort("oracle_v1_c1")
    print("  ✓ cohort_1 ↔ oracle_v1_c1: both accepted, alias for comparison, no rewrite")


def test_cohort_tag_builder():
    assert cohort_tag("oracle_v1", 1) == "oracle_v1_c1"
    assert cohort_tag("momentum_v2", 3) == "momentum_v2_c3"
    print("  ✓ cohort_tag builder")


# ─── OrderIntentDraft round-trip through a concrete Sleeve ────────────────────

class _DemoSleeve(Sleeve):
    def generate_signals(self, screen_data):
        return [self.draft(t, "LONG", thesis="demo") for t in screen_data]


def test_draft_carries_sleeve_cohort_tag():
    s = _DemoSleeve({"sleeve_id": "momentum_v2"})
    drafts = s.generate_signals(["AAPL", "MSFT"])
    assert all(isinstance(d, OrderIntentDraft) for d in drafts)
    assert all(d.cohort == "momentum_v2_c1" for d in drafts)     # {sleeve_id}_c{n}
    assert [d.ticker for d in drafts] == ["AAPL", "MSFT"]
    print("  ✓ generate_signals → drafts tagged momentum_v2_c1")


def test_draft_rejects_invalid_cohort_and_side():
    with pytest.raises(ValueError):
        OrderIntentDraft(sleeve_id="x", cohort="BAD", ticker="A", side="LONG")
    with pytest.raises(ValueError):
        OrderIntentDraft(sleeve_id="x", cohort="oracle_v1_c1", ticker="A", side="sideways")
    print("  ✓ draft validates cohort + side at construction")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
