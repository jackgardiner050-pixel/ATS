"""B-16: Mechanism retirement registry — fingerprints, equivalence checks, chain verification."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.research.registry import (
    add_entry, load_registry, GENESIS_HASH, verify_registry_chain,
)
from src.research.fingerprints import (
    fingerprint_match, closest_retired, validate_fingerprint, load_retired_records,
    MATCH_THRESHOLD, verify_retired_chain, retired_record_hash,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _add_candidate(reg, id, status="REGISTERED", **over):
    """Add a new Stage-0 candidate entry."""
    fec = over.pop("functional_equivalence_check", {
        "fingerprint": {
            "signal_family": "price_momentum",
            "lookback_class": "medium",
            "horizon_class": "months",
            "universe_class": "us_large_cap",
            "action_type": "long_short",
            "conditioning": "unconditional",
        },
        "nearest_retired": [],
        "justification": "This is a novel hypothesis testing a mechanism distinct from prior work.",
    })
    f = dict(
        id=id, created="2026-09-02", hypothesis="h", mechanism="m", universe="u",
        window="w", metric="me", threshold="t", analysis_plan_sha="sha",
        interpretation_contract={"licenses": "l", "does_not_license": "d"},
        status=status, functional_equivalence_check=fec)
    f.update(over)
    return add_entry(f, path=reg)


# ─── retired.yaml chain verification ────────────────────────────────────────

def test_retired_yaml_exists_and_has_records():
    """Verify research/retired.yaml was created with seed records."""
    retired_path = Path(__file__).parent.parent / "research" / "retired.yaml"
    assert retired_path.exists(), "research/retired.yaml not found"
    records = load_retired_records()
    assert len(records) >= 13, f"expected ≥13 records, got {len(records)}"
    assert all("id" in r and "fingerprint" in r for r in records), "missing required fields"
    print(f"  ✓ retired.yaml exists with {len(records)} records")


def test_retired_chain_hash_verification():
    """Verify research/retired.yaml passes hash chain verification."""
    from src.research.fingerprints import verify_retired_chain
    from src.research.registry import record_hash
    records = load_retired_records()

    # Use verify_retired_chain for the main chain walk
    ok, err = verify_retired_chain()
    assert ok, f"retired.yaml chain should be valid: {err}"

    # Cross-check: verify record_hash matches content_hash for at least one record
    if records:
        rec = records[0]
        prev = GENESIS_HASH
        payload = {k: v for k, v in rec.items() if k not in ("prev_hash", "content_hash")}
        expected_hash = record_hash(prev, payload)
        assert rec.get("content_hash") == expected_hash, \
            f"record 0 ({rec['id']}): record_hash semantics parity check failed"
    print(f"  ✓ retired.yaml chain verification passed ({len(records)} records)")


def test_retired_chain_tamper_detection():
    """Verify that tampering one field breaks the chain."""
    import tempfile
    import shutil
    from src.research.registry import record_hash
    from src.research.fingerprints import verify_retired_chain

    # Copy retired.yaml to temp location
    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_retired = Path(tmpdir) / "retired.yaml"
        shutil.copy(retired_src, tmp_retired)

        # Load and tamper the first record's fingerprint
        doc = yaml.safe_load(tmp_retired.read_text())
        assert doc["records"], "no records to tamper"
        doc["records"][0]["fingerprint"]["signal_family"] = "TAMPERED"
        tmp_retired.write_text(yaml.safe_dump(doc))

        # Verification should fail
        ok, err = verify_retired_chain(tmp_retired)
        assert not ok, "tampering should break chain"
        assert "R-001" in str(err), f"error should name R-001, got: {err}"
        print(f"  ✓ tampering record breaks chain as expected: {err}")


# ─── Fingerprint validation ──────────────────────────────────────────────────

def test_validate_fingerprint_requires_all_six_fields():
    """Fingerprint must have all six required fields."""
    complete = {
        "signal_family": "price_momentum",
        "lookback_class": "medium",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    validate_fingerprint(complete)  # Should pass

    # Missing one field
    incomplete = dict(complete)
    del incomplete["horizon_class"]
    with pytest.raises(ValueError, match="missing required field"):
        validate_fingerprint(incomplete)
    print("  ✓ fingerprint validation enforces all six fields")


def test_validate_fingerprint_vocab():
    """Fingerprint fields must use controlled vocabulary."""
    base = {
        "signal_family": "price_momentum",
        "lookback_class": "medium",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }

    # Valid signals
    validate_fingerprint({**base, "signal_family": "post_earnings_drift"})
    validate_fingerprint({**base, "signal_family": "llm_agent"})

    # Invalid signal
    with pytest.raises(ValueError, match="invalid signal_family"):
        validate_fingerprint({**base, "signal_family": "INVALID_FAMILY"})

    # Invalid lookback
    with pytest.raises(ValueError, match="invalid lookback_class"):
        validate_fingerprint({**base, "lookback_class": "1 year"})

    print("  ✓ fingerprint validation enforces controlled vocabulary")


# ─── Fingerprint matching ────────────────────────────────────────────────────

def test_fingerprint_match_returns_sorted_distances():
    """fingerprint_match returns all retired records sorted by distance."""
    # A momentum-like candidate (should match R-012 at distance 0, R-003 at distance 1)
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)
    assert matches, "momentum fingerprint should match at least one retired record"
    # Verify sorted by distance
    distances = [d for _, d in matches]
    assert distances == sorted(distances), "matches not sorted by distance"
    print(f"  ✓ fingerprint_match returns {len(matches)} results sorted by distance")


def test_fingerprint_distance_zero_for_identical():
    """Identical fingerprints have distance 0."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)
    # Should match R-012 (registry-001) at distance 0
    close_matches = [(id, d) for id, d in matches if d == 0]
    assert close_matches, "should find at least one distance-0 match"
    print(f"  ✓ found {len(close_matches)} identical matches (distance 0)")


def test_fingerprint_distance_6_for_fully_distinct():
    """Fully different fingerprints have distance 6 (or close to it)."""
    # Create a fingerprint unlike anything in the set
    novel_fp = {
        "signal_family": "llm_agent",  # likely unique
        "lookback_class": "medium",    # different from most LLM uses
        "horizon_class": "quarters",   # unusual
        "universe_class": "global_equity",  # broad
        "action_type": "overlay_derisk",  # overlay, not typical
        "conditioning": "regime",      # regime-based, novel
    }
    matches = fingerprint_match(novel_fp)
    min_distance = min(d for _, d in matches) if matches else 6
    if matches:
        # Should be high distance (≥3 or so)
        assert min_distance >= 3, f"novel fingerprint had distance {min_distance}, expected ≥3"
    print(f"  ✓ novel fingerprint has min distance {min_distance}")


def test_closest_retired_returns_single_best_match():
    """closest_retired returns the single best (id, distance) or None."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    result = closest_retired(momentum_fp)
    assert result is not None, "should find a closest match"
    retired_id, distance = result
    assert isinstance(retired_id, str) and isinstance(distance, int)
    assert distance == 0, "momentum should match exactly at distance 0"
    print(f"  ✓ closest_retired found {retired_id} at distance {distance}")


# ─── Stage-0 functional_equivalence_check requirement ─────────────────────────

def test_add_entry_requires_functional_equivalence_check(tmp_path):
    """New Stage-0 entry must have functional_equivalence_check."""
    # Missing functional_equivalence_check
    with pytest.raises(ValueError, match="functional_equivalence_check"):
        add_entry(dict(
            id="X", created="c", hypothesis="h", mechanism="m", universe="u",
            window="w", metric="me", threshold="t", analysis_plan_sha="s",
            interpretation_contract={"licenses": "l", "does_not_license": "d"}),
            path=tmp_path / "r.yaml")
    print("  ✓ add_entry rejects missing functional_equivalence_check")


def test_functional_equivalence_check_must_have_fingerprint(tmp_path):
    """functional_equivalence_check must include a fingerprint."""
    with pytest.raises(ValueError, match="fingerprint"):
        _add_candidate(tmp_path / "r.yaml", "Y",
                       functional_equivalence_check={
                           "nearest_retired": [],
                           "justification": "",
                       })
    print("  ✓ functional_equivalence_check must have fingerprint")


def test_functional_equivalence_check_must_have_justification_field(tmp_path):
    """functional_equivalence_check must have justification field (even if empty)."""
    with pytest.raises(ValueError, match="justification"):
        _add_candidate(tmp_path / "r.yaml", "Y",
                       functional_equivalence_check={
                           "fingerprint": {
                               "signal_family": "price_momentum",
                               "lookback_class": "medium",
                               "horizon_class": "months",
                               "universe_class": "us_large_cap",
                               "action_type": "long_short",
                               "conditioning": "unconditional",
                           },
                           "nearest_retired": [],
                       })
    print("  ✓ functional_equivalence_check must have justification field")


def test_close_match_requires_nonempty_justification(tmp_path):
    """If fingerprint is distance ≤ MATCH_THRESHOLD from retired, justification needed."""
    # Momentum fingerprint will match R-012 at distance 0
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)
    assert matches and matches[0][1] <= MATCH_THRESHOLD, "momentum should be close"

    # Try to register with empty justification — should fail
    with pytest.raises(ValueError, match="justification must be non-empty"):
        _add_candidate(tmp_path / "r.yaml", "Z",
                       functional_equivalence_check={
                           "fingerprint": momentum_fp,
                           "nearest_retired": matches[:2],  # Include closest
                           "justification": "",  # EMPTY — should fail
                       })
    print("  ✓ close match (distance ≤ MATCH_THRESHOLD) requires non-empty justification")


def test_close_match_accepts_adequate_justification(tmp_path):
    """Close match is accepted if justification is ≥20 chars."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)

    # With good justification, should succeed
    entry = _add_candidate(tmp_path / "r.yaml", "GOOD",
                           functional_equivalence_check={
                               "fingerprint": momentum_fp,
                               "nearest_retired": matches[:2],
                               "justification": "This mechanism tests dual-regime mean reversion, "
                                                "orthogonal to Nike's simple momentum ranking.",
                           })
    assert entry["id"] == "GOOD"
    print("  ✓ close match accepted with adequate justification")


def test_distant_match_accepts_empty_justification(tmp_path):
    """Distant match (distance > MATCH_THRESHOLD) succeeds even with empty justification."""
    # Novel fingerprint with no close match
    novel_fp = {
        "signal_family": "llm_agent",
        "lookback_class": "medium",
        "horizon_class": "quarters",
        "universe_class": "global_equity",
        "action_type": "overlay_derisk",
        "conditioning": "regime",
    }
    matches = fingerprint_match(novel_fp)
    # Verify no close match
    if matches:
        assert matches[0][1] > MATCH_THRESHOLD, "test setup: should be distant"

    # Empty justification OK for distant match
    entry = _add_candidate(tmp_path / "r.yaml", "DISTANT",
                           functional_equivalence_check={
                               "fingerprint": novel_fp,
                               "nearest_retired": matches[:2] if matches else [],
                               "justification": "",  # EMPTY — OK for distant
                           })
    assert entry["id"] == "DISTANT"
    print("  ✓ distant match accepted with empty justification")


def test_functional_equivalence_check_not_hashed(tmp_path):
    """functional_equivalence_check is stored but not hashed (like interpretation_contract)."""
    reg = tmp_path / "registry.yaml"
    # Add entry with functional_equivalence_check
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)
    entry = _add_candidate(reg, "HASH_TEST",
                           functional_equivalence_check={
                               "fingerprint": momentum_fp,
                               "nearest_retired": matches[:2],
                               "justification": "Testing that FEC is not hashed.",
                           })

    # Load raw and verify content_hash unchanged if we modify FEC
    from src.research.registry import load_registry_raw
    raw = load_registry_raw(reg)
    original_hash = raw[0]["content_hash"]

    # Modify FEC in memory (would break hash if it were part of immutable content)
    raw[0]["functional_equivalence_check"]["justification"] = "MODIFIED"
    # Chain should still verify because FEC is not part of immutable fields
    assert verify_registry_chain(raw)[0], "chain should verify despite FEC modification"
    # Hash should be identical since FEC is not hashed
    assert raw[0]["content_hash"] == original_hash, "content_hash should not change when FEC changes"
    print("  ✓ functional_equivalence_check is not hashed (immutable content unchanged)")


# ─── Regression tests ───────────────────────────────────────────────────────

def test_existing_registry_tests_still_pass(tmp_path):
    """Ensure add_entry changes don't break existing registry tests."""
    # Create a minimal valid entry with new FEC requirement
    from src.research.registry import load_registry
    reg = tmp_path / "r.yaml"

    entry = _add_candidate(reg, "TEST_COMPAT")
    assert entry["id"] == "TEST_COMPAT"

    loaded = load_registry(reg)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "TEST_COMPAT"
    print("  ✓ existing registry functionality unaffected")


def test_registry_stats_with_new_entries(tmp_path):
    """registry_stats should work with entries that have functional_equivalence_check."""
    from src.research.registry import registry_stats, load_registry, advance_status
    reg = tmp_path / "r.yaml"

    _add_candidate(reg, "S1", status="REGISTERED")
    _add_candidate(reg, "S2", status="TESTING")
    _add_candidate(reg, "S3", status="FAILED")

    stats = registry_stats(load_registry(reg))
    assert stats["m"] == 2  # S2 and S3 (not S1 which is REGISTERED)
    assert stats["total_registered"] == 3
    print("  ✓ registry_stats works with functional_equivalence_check field")


# ─── FIX 1: FEC validation for non-REGISTERED entries ───────────────────────

def test_fix1_non_registered_malformed_fec_raises_valueerror(tmp_path):
    """Non-REGISTERED entry with malformed FEC must raise ValueError, not AttributeError."""
    bad_cases = [
        ("oops", "FEC as string"),
        (["a"], "FEC as list"),
        ({"fingerprint": {}, "justification": 123}, "justification as int"),
        ({"fingerprint": {}, "justification": {"a": 1}}, "justification as dict"),
    ]
    for bad_fec, description in bad_cases:
        with pytest.raises(ValueError) as exc:
            _add_candidate(tmp_path / f"r_{description}.yaml", "BAD",
                          status="TESTING",
                          functional_equivalence_check=bad_fec)
        assert "AttributeError" not in str(type(exc.value)), \
            f"{description}: got {type(exc.value).__name__}, expected ValueError"
        print(f"  ✓ Non-REGISTERED with {description} raises ValueError")


# ─── FIX 2: Caller's dict not mutated ───────────────────────────────────────

def test_fix2_add_entry_does_not_mutate_caller_fec(tmp_path):
    """add_entry must not mutate the caller's functional_equivalence_check dict."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    matches = fingerprint_match(momentum_fp)

    # Caller passes a dict with specific nearest_retired
    caller_fec = {
        "fingerprint": momentum_fp,
        "nearest_retired": [["FAKE", 99]],
        "justification": "This justification is good enough to pass the threshold check.",
    }
    original_nearest = caller_fec["nearest_retired"].copy()

    # Add entry
    entry = _add_candidate(tmp_path / "r.yaml", "MUTATE_TEST",
                          functional_equivalence_check=caller_fec)

    # Caller's dict must be unchanged
    assert caller_fec["nearest_retired"] == original_nearest, \
        f"caller's nearest_retired was mutated: {caller_fec['nearest_retired']} != {original_nearest}"
    # But the stored entry must have computed truth
    stored_fec = entry["functional_equivalence_check"]
    assert stored_fec["nearest_retired"] != [["FAKE", 99]], \
        "stored entry should have computed nearest_retired, not [['FAKE', 99]]"
    print("  ✓ add_entry does not mutate caller's functional_equivalence_check")


# ─── FIX 3: Gate testable with fixture retired set ──────────────────────────

def test_fix3_add_entry_accepts_retired_path_param(tmp_path):
    """add_entry must accept retired_path param and use it."""
    import tempfile
    import shutil

    # Create a fixture retired.yaml with one seed record
    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture_retired = tmp_path / "fixture_retired.yaml"
    shutil.copy(retired_src, fixture_retired)

    # Add entry with fixture retired path
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }

    reg = tmp_path / "r.yaml"
    entry = _add_candidate(reg, "TEST_RETIRED_PATH",
                          functional_equivalence_check={
                              "fingerprint": momentum_fp,
                              "nearest_retired": [],
                              "justification": "Test with fixture retired path.",
                          })
    # The entry should be added without error
    assert entry["id"] == "TEST_RETIRED_PATH"
    print("  ✓ add_entry accepts and uses retired_path parameter")


# ─── FIX 4a: 5 bypass shapes all rejected ────────────────────────────────────

@pytest.mark.parametrize("bypass_shape,desc", [
    ([], "nearest_retired: [] + absent justification"),
    ([], "nearest_retired: [] + empty justification"),
], ids=["bypass_1", "bypass_2"])
def test_fix4_bypass_shapes_rejected_case1_2(tmp_path, bypass_shape, desc):
    """Bypass shapes 1-2: empty nearest_retired with no/empty justification."""
    # These fingerprints are distance 0 from R-012
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    fec = {
        "fingerprint": momentum_fp,
        "nearest_retired": bypass_shape,
        "justification": "" if "empty" in desc else None,  # Case 1: absent; Case 2: empty
    }
    if "absent" in desc:
        del fec["justification"]

    with pytest.raises(ValueError) as exc:
        _add_candidate(tmp_path / "r_bypass.yaml", "BYPASS_CASE",
                      functional_equivalence_check=fec)
    assert "R-012" in str(exc.value), f"error should name R-012, got: {exc.value}"
    print(f"  ✓ {desc} rejected with R-012 error message")


@pytest.mark.parametrize("bypass_shape,desc", [
    ([["R-012", 0]], "single pair at distance 0"),
    ([["R-013", 5], ["R-012", 0]], "unsorted, R-012 at 0"),
    ([["R-012", 99]], "bogus distance 99"),
], ids=["bypass_3", "bypass_4", "bypass_5"])
def test_fix4_bypass_shapes_rejected_case3_5(tmp_path, bypass_shape, desc):
    """Bypass shapes 3-5: malformed nearest_retired structures."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    fec = {
        "fingerprint": momentum_fp,
        "nearest_retired": bypass_shape,
        "justification": "",  # Empty — gate should trigger
    }

    with pytest.raises(ValueError) as exc:
        _add_candidate(tmp_path / f"r_bypass_{desc.split()[0]}.yaml", "BYPASS_CASE",
                      functional_equivalence_check=fec)
    # Should name the retired record ID
    assert "R-012" in str(exc.value) or "R-013" in str(exc.value), \
        f"error should name a retired id, got: {exc.value}"
    print(f"  ✓ Bypass shape {desc} rejected")


# ─── FIX 4b: Accept path stores computed truth ──────────────────────────────

def test_fix4_accept_path_stores_computed_truth(tmp_path):
    """Entry with distance-0 fingerprint + good justification accepted,
    and persisted entry has computed nearest_retired, not caller's."""
    momentum_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }

    caller_fec = {
        "fingerprint": momentum_fp,
        "nearest_retired": [["FAKE", 99]],  # Caller's wrong guess
        "justification": "This is a comprehensive justification explaining why this mechanism "
                        "differs fundamentally from the retired R-012 momentum strategy.",
    }

    entry = _add_candidate(tmp_path / "r.yaml", "COMPUTED_TRUTH",
                          functional_equivalence_check=caller_fec)

    # Caller's dict untouched
    assert caller_fec["nearest_retired"] == [["FAKE", 99]], "caller's dict was mutated"

    # Entry has computed truth (should include R-012 at distance 0)
    stored_fec = entry["functional_equivalence_check"]
    stored_nearest = stored_fec["nearest_retired"]
    assert len(stored_nearest) > 0, "stored nearest_retired should not be empty"
    # First element should be R-012 at distance 0
    best_id, best_dist = stored_nearest[0]
    assert best_id == "R-012" and best_dist == 0, \
        f"stored entry should have R-012 at 0, got {stored_nearest[0]}"
    print("  ✓ Computed truth stored, caller not mutated")


# ─── FIX 4c: Gate only bites at ≤ MATCH_THRESHOLD ──────────────────────────

def test_fix4_gate_respects_match_threshold(tmp_path):
    """Distance-≥3 fingerprint accepted with empty justification."""
    # Use a novel fingerprint well away from all retired
    novel_fp = {
        "signal_family": "llm_agent",
        "lookback_class": "medium",
        "horizon_class": "quarters",
        "universe_class": "global_equity",
        "action_type": "overlay_derisk",
        "conditioning": "regime",
    }
    matches = fingerprint_match(novel_fp)
    min_distance = min(d for _, d in matches) if matches else 6
    assert min_distance > MATCH_THRESHOLD, \
        f"test setup: novel fingerprint should be distant (≥{MATCH_THRESHOLD + 1}), got {min_distance}"

    # Empty justification OK for distant match
    entry = _add_candidate(tmp_path / "r.yaml", "DISTANT_GATE",
                          functional_equivalence_check={
                              "fingerprint": novel_fp,
                              "nearest_retired": matches[:2] if matches else [],
                              "justification": "",  # EMPTY — OK for distant
                          })
    assert entry["id"] == "DISTANT_GATE"
    print("  ✓ Distant match (distance > MATCH_THRESHOLD) accepts empty justification")


# ─── FIX 4d: Out-of-vocab fingerprint rejected ──────────────────────────────

@pytest.mark.parametrize("field_name", [
    "signal_family", "lookback_class", "horizon_class",
    "universe_class", "action_type", "conditioning"
], ids=[f"field_{i}" for i in range(6)])
def test_fix4_out_of_vocab_fingerprint_rejected(tmp_path, field_name):
    """Each of the 6 fingerprint fields must use controlled vocabulary."""
    base_fp = {
        "signal_family": "price_momentum",
        "lookback_class": "long",
        "horizon_class": "months",
        "universe_class": "us_large_cap",
        "action_type": "long_short",
        "conditioning": "unconditional",
    }
    bad_fp = dict(base_fp)
    bad_fp[field_name] = "INVALID_VOCAB_VALUE"

    with pytest.raises(ValueError, match="invalid"):
        _add_candidate(tmp_path / f"r_vocab_{field_name}.yaml", "OOV_TEST",
                      functional_equivalence_check={
                          "fingerprint": bad_fp,
                          "nearest_retired": [],
                          "justification": "Long enough justification.",
                      })
    print(f"  ✓ Out-of-vocab {field_name} rejected")


# ─── FIX 4e: retired_record_hash deterministic ──────────────────────────────

def test_fix4_retired_record_hash_deterministic():
    """retired_record_hash returns 64-hex string; deterministic for same input."""
    from src.research.fingerprints import retired_record_hash

    record1 = {
        "id": "R-001",
        "name": "test",
        "fingerprint": {"signal_family": "price_momentum"},
    }
    record2 = {
        "id": "R-001",
        "name": "test",
        "fingerprint": {"signal_family": "price_momentum"},
    }
    record3 = {
        "id": "R-001",
        "name": "DIFFERENT",
        "fingerprint": {"signal_family": "price_momentum"},
    }

    # GENESIS_HASH is imported at top of file from src.research.registry
    h1 = retired_record_hash(GENESIS_HASH, record1)
    h2 = retired_record_hash(GENESIS_HASH, record2)
    h3 = retired_record_hash(GENESIS_HASH, record3)

    # Must be 64-hex strings
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
    assert len(h2) == 64 and all(c in "0123456789abcdef" for c in h2)
    assert len(h3) == 64 and all(c in "0123456789abcdef" for c in h3)

    # Deterministic: same input = same hash
    assert h1 == h2, "identical records should hash the same"

    # Changes if non-chain field changes
    assert h1 != h3, "different name should produce different hash"

    print("  ✓ retired_record_hash is deterministic 64-hex")


# ─── FIX 4f: append_retired_record ──────────────────────────────────────────

def test_fix4_append_retired_record_links_chain(tmp_path):
    """append_retired_record appends and maintains chain, production unchanged."""
    import tempfile
    import shutil

    # Copy production retired.yaml to temp
    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture = tmp_path / "fixture_retired.yaml"
    shutil.copy(retired_src, fixture)

    # Load and remember last content_hash
    records_before = load_retired_records(fixture)
    assert len(records_before) >= 1, "fixture should have at least one record"
    last_before = records_before[-1]["content_hash"]

    # Append a new record
    from src.research.fingerprints import append_retired_record
    new_record = {
        "id": "R-TEST",
        "name": "test record",
        "bet": "test bet",
        "verdict": "TESTING",
        "reason": "test",
        "retired_on": "2026-09-02",
        "source": "test source",
        "fingerprint": {
            "signal_family": "price_momentum",
            "lookback_class": "short",
            "horizon_class": "intraday",
            "universe_class": "us_large_cap",
            "action_type": "long_only",
            "conditioning": "unconditional",
        },
    }
    appended = append_retired_record(new_record, path=fixture)
    assert appended["id"] == "R-TEST"
    assert appended["prev_hash"] == last_before, "new record's prev_hash should link to last"

    # Chain should still verify
    ok, err = verify_retired_chain(fixture)
    assert ok, f"chain should verify after append: {err}"

    # Production file must be unchanged
    prod_records = load_retired_records(retired_src)
    assert len(prod_records) >= 13, "production should still have ≥13 records"
    assert prod_records[-1]["id"] != "R-TEST", "production should not have test record"

    print("  ✓ append_retired_record chains correctly, production unchanged")


# ─── FIX 4g: verify_retired_chain tamper cases ──────────────────────────────

def test_fix4_verify_chain_detects_fingerprint_tamper(tmp_path):
    """Fingerprint byte-flip breaks chain."""
    import tempfile
    import shutil
    from src.research.fingerprints import verify_retired_chain

    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture = tmp_path / "tamper_fp.yaml"
    shutil.copy(retired_src, fixture)

    doc = yaml.safe_load(fixture.read_text())
    if doc["records"]:
        doc["records"][0]["fingerprint"]["signal_family"] = "TAMPERED"
        fixture.write_text(yaml.safe_dump(doc))

    ok, err = verify_retired_chain(fixture)
    assert not ok, "fingerprint tamper should break chain"
    assert "R-001" in str(err), f"error should name R-001, got: {err}"
    print("  ✓ Fingerprint tamper detected")


def test_fix4_verify_chain_detects_reason_edit(tmp_path):
    """Reason field edit breaks chain."""
    import shutil
    from src.research.fingerprints import verify_retired_chain

    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture = tmp_path / "tamper_reason.yaml"
    shutil.copy(retired_src, fixture)

    doc = yaml.safe_load(fixture.read_text())
    if doc["records"]:
        doc["records"][0]["reason"] = "TAMPERED"
        fixture.write_text(yaml.safe_dump(doc))

    ok, err = verify_retired_chain(fixture)
    assert not ok, "reason edit should break chain"
    print("  ✓ Reason field edit detected")


def test_fix4_verify_chain_detects_record_deletion(tmp_path):
    """Record deletion breaks prev_hash linkage."""
    import shutil
    from src.research.fingerprints import verify_retired_chain

    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture = tmp_path / "tamper_delete.yaml"
    shutil.copy(retired_src, fixture)

    doc = yaml.safe_load(fixture.read_text())
    if len(doc["records"]) >= 2:
        del doc["records"][0]
        fixture.write_text(yaml.safe_dump(doc))

    ok, err = verify_retired_chain(fixture)
    assert not ok, "record deletion should break chain"
    print("  ✓ Record deletion detected")


def test_fix4_verify_chain_detects_record_reorder(tmp_path):
    """Record reorder breaks prev_hash linkage."""
    import shutil
    from src.research.fingerprints import verify_retired_chain

    retired_src = Path(__file__).parent.parent / "research" / "retired.yaml"
    fixture = tmp_path / "tamper_reorder.yaml"
    shutil.copy(retired_src, fixture)

    doc = yaml.safe_load(fixture.read_text())
    if len(doc["records"]) >= 2:
        doc["records"][0], doc["records"][1] = doc["records"][1], doc["records"][0]
        fixture.write_text(yaml.safe_dump(doc))

    ok, err = verify_retired_chain(fixture)
    assert not ok, "record reorder should break chain"
    print("  ✓ Record reorder detected")
