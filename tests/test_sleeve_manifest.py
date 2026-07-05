"""Sleeve manifest validation matrix + oracle_v1 retrofit ↔ OBSERVATION_PROTOCOL §5."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.sleeves.manifest import validate_manifest, load_manifest, load_all, ManifestError

ROOT = Path(__file__).parent.parent


def _valid():
    return {
        "sleeve_id": "test_v1", "thesis": "a testable thesis", "registry_ref": "001",
        "strategy_module": "src.paper_trading", "cadence": "weekly",
        "kill_criteria": ["excess < -10%"], "stage": "S1", "created": "2026-07-05",
        "locked": True,
        "correlation_prior": {"expected_overlap_sleeves": [], "declared_dominant_factor": "value"},
    }


# ─── validation matrix ───────────────────────────────────────────────────────

def test_valid_manifest_loads_and_applies_default_benchmark():
    m = validate_manifest(_valid())
    assert m["benchmark"] == "SPY_TR"          # default applied
    print("  ✓ valid manifest loads; benchmark defaults to SPY_TR")


def test_missing_kill_criteria_refused_with_admission_rule():
    d = _valid(); del d["kill_criteria"]
    with pytest.raises(ManifestError, match="ADMISSION"):
        validate_manifest(d)
    print("  ✓ missing kill_criteria → refused, admission rule quoted")


def test_missing_registry_ref_refused_with_admission_rule():
    d = _valid(); del d["registry_ref"]
    with pytest.raises(ManifestError, match="ADMISSION"):
        validate_manifest(d)
    print("  ✓ missing registry_ref → refused, admission rule quoted")


def test_empty_kill_criteria_refused():
    d = _valid(); d["kill_criteria"] = []
    with pytest.raises(ManifestError, match="ADMISSION"):
        validate_manifest(d)
    print("  ✓ empty kill_criteria → refused")


def test_bad_stage_enum_refused():
    d = _valid(); d["stage"] = "S9"
    with pytest.raises(ManifestError, match="stage"):
        validate_manifest(d)


def test_wrong_type_refused():
    d = _valid(); d["sleeve_id"] = 123
    with pytest.raises(ManifestError, match="wrong type"):
        validate_manifest(d)


def test_nested_correlation_prior_required_subfield():
    d = _valid(); del d["correlation_prior"]["declared_dominant_factor"]
    with pytest.raises(ManifestError, match="declared_dominant_factor"):
        validate_manifest(d)
    print("  ✓ enum / type / nested-subfield all enforced")


# ─── oracle_v1 retrofit ↔ protocol doc §5 (parse both, compare) ──────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("**", "").replace("`", "")).strip()


def _doc_kill_bullets() -> list[str]:
    """Extract the §5 KILL bullets, joining wrapped continuation lines into each bullet."""
    text = (ROOT / "docs" / "OBSERVATION_PROTOCOL.md").read_text()
    block = text.split("**KILL", 1)[1].split("**CONTINUE", 1)[0]
    bullets: list[str] = []
    for ln in block.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("- "):
            bullets.append(s[2:])
        elif bullets and not s.startswith("**"):
            bullets[-1] += " " + s          # indented continuation of the current bullet
    return [_norm(b) for b in bullets]


def test_oracle_v1_loads_stage_and_alias():
    m = load_manifest(ROOT / "config" / "sleeves" / "oracle_v1.yaml")
    assert m["sleeve_id"] == "oracle_v1" and m["stage"] == "S2"
    assert m["benchmark"] == "SPY_TR" and m["registry_ref"]
    from src.sleeves.cohort import same_cohort
    assert same_cohort("cohort_1", "oracle_v1_c1")     # legacy alias holds
    print("  ✓ oracle_v1 loads (S2); cohort_1 ↔ oracle_v1_c1 alias holds")


def test_oracle_kill_criteria_match_protocol_section5_verbatim():
    m = load_manifest(ROOT / "config" / "sleeves" / "oracle_v1.yaml")
    manifest_kills = [_norm(k) for k in m["kill_criteria"]]
    doc_kills = _doc_kill_bullets()
    assert manifest_kills == doc_kills, f"\nmanifest={manifest_kills}\ndoc={doc_kills}"
    print(f"  ✓ oracle_v1 kill_criteria == §5 KILL bullets verbatim ({len(doc_kills)} gates)")


def test_all_sleeves_load():
    sleeves = load_all()
    assert "oracle_v1" in sleeves
    print(f"  ✓ load_all() → {sorted(sleeves)}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
