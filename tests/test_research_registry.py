"""Hypothesis registry: append-only, content-hash chain, honesty stats."""
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.research.registry import (
    load_registry, registry_stats, verify_registry_chain, add_entry, advance_status,
    DEFAULT_REGISTRY,
)

ROOT = Path(__file__).parent.parent


# ─── the committed registry (ACCEPTANCE after resolution A: m=3, alpha=0.05/3) ──

def test_committed_registry_stats_m3_alpha_bonferroni():
    # After reconciliation (resolution A): 001 momentum, 002 PEAD, 003 Oracle/Cohort-1.
    s = registry_stats(load_registry())
    assert s["m"] == 3
    assert s["alpha"] == 0.05 / 3          # recomputed Bonferroni, not a hardcoded guess
    assert s["pass_rate"] == 0.0           # 0 PASSED of 2 resolved (003 is TESTING)
    print(f"  ✓ registry stats: m={s['m']}, alpha={s['alpha']:.6f} (=0.05/3), pass_rate={s['pass_rate']}")


def test_entry_003_oracle_testing():
    e = {x["id"]: x for x in load_registry()}["003"]
    assert e["status"] == "TESTING"
    assert e["result_ref"] == "docs/OBSERVATION_PROTOCOL.md"   # no result yet — window mid-flight
    assert "STRONG_BUY" in e["hypothesis"] and "SPY TR" in e["hypothesis"]
    print("  ✓ entry 003 Oracle/Cohort-1: TESTING, result_ref → protocol doc")


def test_committed_registry_chain_valid():
    ok, err = verify_registry_chain(load_registry())
    assert ok, err
    print("  ✓ committed 001/002/003 chain verifies")


def test_retroactive_entries_present_and_failed():
    e = {x["id"]: x for x in load_registry()}
    assert e["001"]["status"] == "FAILED" and "momentum" in e["001"]["hypothesis"].lower()
    assert e["001"]["result_ref"] == "research/momentum_validation/MEMO_momentum.md"
    assert e["002"]["status"] == "FAILED" and e["002"]["result_ref"] == "swing-bot/backtest/PEAD_RESULTS.md"
    print("  ✓ 001 momentum + 002 PEAD retroactive, FAILED, result_ref set")


# ─── ACCEPTANCE: tampering with 001's hypothesis breaks the chain ────────────

def test_tampering_hypothesis_breaks_chain():
    entries = load_registry()
    entries[0]["hypothesis"] = entries[0]["hypothesis"] + " (tampered)"
    ok, err = verify_registry_chain(entries)
    assert not ok and "content_hash mismatch" in err
    print(f"  ✓ tamper 001.hypothesis → chain breaks: {err}")


# ─── append-only + forward-only status ───────────────────────────────────────

def _tmp_registry(tmp_path):
    p = tmp_path / "registry.yaml"
    shutil.copy2(DEFAULT_REGISTRY, p)
    return p


def test_add_entry_refuses_missing_fields(tmp_path):
    with pytest.raises(ValueError, match="missing required"):
        add_entry({"id": "999", "created": "2026-07-05", "hypothesis": "x"}, path=_tmp_registry(tmp_path))
    print("  ✓ add_entry refuses an incomplete hypothesis")


def test_duplicate_id_refused(tmp_path):
    reg = _tmp_registry(tmp_path)
    full = dict(id="001", created="2026-07-05", hypothesis="h", mechanism="m", universe="u",
                window="w", metric="me", threshold="t", analysis_plan_sha="sha")
    with pytest.raises(ValueError, match="already exists"):
        add_entry(full, path=reg)
    print("  ✓ duplicate id refused (append-only)")


def test_status_forward_only_and_chain_survives(tmp_path):
    reg = _tmp_registry(tmp_path)
    add_entry(dict(id="T04", created="2026-07-05", hypothesis="h", mechanism="m", universe="u",
                   window="w", metric="me", threshold="t", analysis_plan_sha="sha",
                   status="REGISTERED"), path=reg)
    advance_status("T04", "TESTING", path=reg)
    advance_status("T04", "PASSED", result_ref="runs/x.md", path=reg)
    with pytest.raises(ValueError, match="illegal transition"):
        advance_status("T04", "TESTING", path=reg)     # PASSED can't revert
    entries = load_registry(reg)
    ok, err = verify_registry_chain(entries)            # status events don't break the chain
    assert ok, err
    e3 = {x["id"]: x for x in entries}["T04"]
    assert e3["status"] == "PASSED" and len(e3["status_events"]) == 3
    print("  ✓ status advances forward-only; append events keep the content chain intact")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
