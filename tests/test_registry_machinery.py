"""F7a (TESTING+ denominator), F5 (interpretation_contract + migration backfill),
F7d (queue by prior) — the adversarial-self-review machinery fixes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.research.registry import (
    add_entry, advance_status, load_registry, load_registry_raw, load_migrations,
    registry_stats, correction_m, queue, verify_registry_chain, verify_migration_chain,
)


def _add(reg, id, status="REGISTERED", **over):
    f = dict(id=id, created="2026-07-06", hypothesis="h", mechanism="m", universe="u",
             window="w", metric="me", threshold="t", analysis_plan_sha="sha",
             interpretation_contract={"licenses": "l", "does_not_license": "d"}, status=status)
    # Add default functional_equivalence_check for REGISTERED entries (B-16)
    if status == "REGISTERED" and "functional_equivalence_check" not in over:
        f["functional_equivalence_check"] = {
            "fingerprint": {
                "signal_family": "price_momentum",
                "lookback_class": "medium",
                "horizon_class": "months",
                "universe_class": "us_large_cap",
                "action_type": "long_short",
                "conditioning": "unconditional",
            },
            "nearest_retired": [],
            "justification": "This is a novel hypothesis testing a distinct mechanism.",
        }
    f.update(over)
    return add_entry(f, path=reg)


# ─── F7a: REGISTERED does not spend credibility; TESTING does ────────────────

def test_registered_does_not_inflate_alpha_but_testing_does(tmp_path):
    reg = tmp_path / "r.yaml"
    _add(reg, "A", status="TESTING")
    a1 = registry_stats(load_registry(reg))["alpha"]

    _add(reg, "B", status="REGISTERED")                 # Stage-0 — free
    s2 = registry_stats(load_registry(reg))
    assert s2["m"] == 1 and s2["alpha"] == a1           # alpha UNCHANGED
    assert s2["total_registered"] == 2                  # but shown informationally

    advance_status("B", "TESTING", path=reg)            # initiating the test spends credibility
    s3 = registry_stats(load_registry(reg))
    assert s3["m"] == 2 and s3["alpha"] != a1           # alpha CHANGED
    print("  ✓ REGISTERED entry doesn't move alpha; advancing it to TESTING does")


def test_correction_m_excludes_registered():
    entries = [{"status": "REGISTERED"}, {"status": "TESTING"}, {"status": "FAILED"},
               {"status": "PASSED"}, {"status": "RETIRED"}]
    assert correction_m(entries) == 4                   # everything except REGISTERED
    print("  ✓ correction_m = TESTING+ count")


# ─── F5: interpretation_contract required + append-only backfill ─────────────

def test_add_entry_requires_interpretation_contract(tmp_path):
    with pytest.raises(ValueError, match="interpretation_contract"):
        add_entry(dict(id="X", created="c", hypothesis="h", mechanism="m", universe="u",
                       window="w", metric="me", threshold="t", analysis_plan_sha="s"),
                  path=tmp_path / "r.yaml")
    print("  ✓ new entry without interpretation_contract fails to load")


def test_interpretation_contract_needs_both_subfields(tmp_path):
    with pytest.raises(ValueError, match="does_not_license"):
        _add(tmp_path / "r.yaml", "Y", interpretation_contract={"licenses": "only one"})
    print("  ✓ interpretation_contract needs licenses AND does_not_license")


def test_committed_backfill_is_append_only_and_complete():
    raw = load_registry_raw()
    assert all("interpretation_contract" not in e for e in raw)     # entries NEVER edited
    assert verify_registry_chain(raw)[0], "entry chain broke"       # 001-003 hashes intact
    assert verify_migration_chain(load_migrations())[0], "migration chain broke"
    overlaid = load_registry()
    for e in overlaid:                                              # all resolve a contract
        ic = e.get("interpretation_contract")
        assert ic and ic["licenses"] and ic["does_not_license"], e["id"]
    print("  ✓ 001-003 backfilled via SCHEMA_MIGRATION: entries untouched, chains valid, all have contracts")


# ─── F7d: queue ranks REGISTERED by prior × fit, descending ──────────────────

def test_queue_orders_by_prior_desc(tmp_path):
    reg = tmp_path / "r.yaml"
    _add(reg, "low", survival_prior=0.2)
    _add(reg, "high", survival_prior=0.9)
    _add(reg, "mid", survival_prior=0.5)
    assert [r["id"] for r in queue(load_registry(reg))] == ["high", "mid", "low"]
    print("  ✓ queue orders REGISTERED entries by prior, descending")


def test_queue_uses_strategic_fit(tmp_path):
    reg = tmp_path / "r.yaml"
    _add(reg, "a", survival_prior=0.5, strategic_fit=2.0)          # 1.0
    _add(reg, "b", survival_prior=0.8)                             # 0.8
    assert [r["id"] for r in queue(load_registry(reg))] == ["a", "b"]
    print("  ✓ queue_priority = prior × strategic_fit")


def test_queue_excludes_non_registered(tmp_path):
    reg = tmp_path / "r.yaml"
    _add(reg, "reg", survival_prior=0.5)
    _add(reg, "test", status="TESTING", survival_prior=0.9)
    assert [r["id"] for r in queue(load_registry(reg))] == ["reg"]   # TESTING not queued
    print("  ✓ queue is REGISTERED-only (does not advance anything)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
