"""Themis hook: a sleeve at stage >= S2 must reference a PASSED registered hypothesis.

A TESTING/REGISTERED (or missing) registry_ref at S2+ is a CI failure — you cannot promote
a sleeve to a capital-bearing stage on an unproven or unregistered hypothesis.

The check parses config/sleeves/*.yaml directly (no src.sleeves dependency, so it runs on
any branch). Logic is unit-tested with synthetic fixtures; the real config/sleeves is
enforced when the sleeve layer is present.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.research.registry import load_registry, add_entry

ROOT = Path(__file__).parent.parent
STAGES_REQUIRING_PASSED = {"S2", "S3"}


def sleeve_registry_violations(sleeves_dir, registry_entries) -> list[str]:
    by_id = {e["id"]: e for e in registry_entries}
    out = []
    for p in sorted(Path(sleeves_dir).glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        m = yaml.safe_load(p.read_text()) or {}
        if m.get("stage") in STAGES_REQUIRING_PASSED:
            ref = m.get("registry_ref")
            entry = by_id.get(ref)
            if entry is None:
                out.append(f"{m.get('sleeve_id')} @ {m.get('stage')}: registry_ref {ref!r} not in registry")
            elif entry.get("status") != "PASSED":
                out.append(f"{m.get('sleeve_id')} @ {m.get('stage')}: registry_ref {ref!r} is "
                           f"{entry.get('status')}, needs PASSED")
    return out


# ─── logic (synthetic fixtures) ──────────────────────────────────────────────

def _reg(tmp_path):
    reg = tmp_path / "registry.yaml"
    common = dict(created="2026-07-05", hypothesis="h", mechanism="m", universe="u",
                  window="w", metric="me", threshold="t", analysis_plan_sha="sha")
    add_entry({**common, "id": "P1", "status": "PASSED"}, path=reg)
    add_entry({**common, "id": "T1", "status": "TESTING"}, path=reg)
    return load_registry(reg)


def _sleeve(tmp_path, sleeve_id, stage, ref):
    d = tmp_path / "sleeves"; d.mkdir(exist_ok=True)
    (d / f"{sleeve_id}.yaml").write_text(yaml.safe_dump(
        {"sleeve_id": sleeve_id, "stage": stage, "registry_ref": ref}))
    return d


def test_s2_passed_ref_ok(tmp_path):
    d = _sleeve(tmp_path, "good_v1", "S2", "P1")
    assert sleeve_registry_violations(d, _reg(tmp_path)) == []
    print("  ✓ S2 → PASSED ref: no violation")


def test_s2_testing_ref_fails(tmp_path):
    d = _sleeve(tmp_path, "bad_v1", "S2", "T1")
    v = sleeve_registry_violations(d, _reg(tmp_path))
    assert len(v) == 1 and "needs PASSED" in v[0]
    print("  ✓ S2 → TESTING ref: CI violation")


def test_s2_missing_ref_fails(tmp_path):
    d = _sleeve(tmp_path, "bad_v2", "S3", "NOPE")
    v = sleeve_registry_violations(d, _reg(tmp_path))
    assert len(v) == 1 and "not in registry" in v[0]
    print("  ✓ S3 → unregistered ref: CI violation")


def test_s1_testing_ref_ok(tmp_path):
    d = _sleeve(tmp_path, "early_v1", "S1", "T1")
    assert sleeve_registry_violations(d, _reg(tmp_path)) == []      # S1 does not require PASSED
    print("  ✓ S1 → TESTING ref: allowed (not yet capital-bearing)")


# ─── real config/sleeves (enforced once the sleeve layer is present) ─────────

def test_real_sleeves_pass_discipline():
    sd = ROOT / "config" / "sleeves"
    manifests = [p for p in sd.glob("*.yaml") if not p.name.startswith("_")] if sd.exists() else []
    if not manifests:
        pytest.skip("no config/sleeves on this branch — Themis hook enforced at merge with the sleeve layer")
    violations = sleeve_registry_violations(sd, load_registry())
    assert not violations, "sleeve registry-discipline violations:\n" + "\n".join(violations)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
