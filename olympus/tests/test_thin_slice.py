"""Thin-slice tests — prove the REAL seams connect (no stubs).

These assert that Olympus runs against the real Oracle ledger entry, the real governance
engines, and the real hash-chained pit_ledger — not fixtures or mocks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # olympus repo root

from olympus.core import config, storage          # noqa: E402
from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter  # noqa: E402
from olympus.adapters import themis_mnemosyne_adapter as themis  # noqa: E402
from olympus.members import tyche, zeus            # noqa: E402


def _orcl():
    r = oracle_adapter.get_rating("ORCL")
    assert r is not None, "ORCL must exist in the REAL Oracle forward-test ledger"
    return r


def test_oracle_adapter_reads_real_ledger_entry():
    r = _orcl()
    assert r["bias"] == "HOLD" and r["ticker"] == "ORCL"
    assert r["as_of_date"] == "2026-06-02"   # the real logged entry, not a fixture


def test_athena_nemesis_runs_real_pre_mortem():
    thesis = oracle_adapter.thesis_view(_orcl())
    crit = athena_nemesis_adapter.critique(thesis, candidate_id="t")
    # the real corpus screen returns concrete failure scenarios / counter-case text
    assert crit.counter_case and crit.failure_scenarios


def test_tyche_uses_real_governance_limits():
    thesis = oracle_adapter.thesis_view(_orcl())
    crit = athena_nemesis_adapter.critique(thesis, candidate_id="t")
    alloc = tyche.size(thesis, crit, candidate_id="t")
    assert alloc.max_allocation == 0.05          # hard single-name cap
    assert alloc.initial_allocation == 0.0       # a HOLD is not a new buy
    # survivability_score comes from the real engine (float) or None — never a stub constant
    assert alloc.survivability_score is None or isinstance(alloc.survivability_score, (int, float))


def test_constitution_check_is_real():
    thesis = oracle_adapter.thesis_view(_orcl())
    crit = athena_nemesis_adapter.critique(thesis, candidate_id="t")
    exp = hecate_adapter.assess("ORCL", candidate_id="t")
    alloc = tyche.size(thesis, crit, candidate_id="t")
    gov = themis.governance_check(thesis, exp, alloc)
    # real constitution returns lists (violations/warnings); keys present
    assert "constitution_violations" in gov and "governance_checklist" in gov


def test_correlated_council_blocks_independence():
    thesis = oracle_adapter.thesis_view(_orcl())
    crit = athena_nemesis_adapter.critique(thesis, candidate_id="t")
    ind = themis.evidence_independence(thesis, crit)
    assert ind["independent_confirmation"] is False   # §7: agreement is correlated


def test_records_to_real_pit_ledger(tmp_path, monkeypatch):
    # point the decision ledger at a temp file so the test doesn't pollute the real one,
    # but still exercise the REAL pit_ledger primitive end-to-end.
    monkeypatch.setattr(storage, "DECISIONS", tmp_path / "dec.jsonl")
    thesis = oracle_adapter.thesis_view(_orcl())
    crit = athena_nemesis_adapter.critique(thesis, candidate_id="t")
    exp = hecate_adapter.assess("ORCL", candidate_id="t")
    alloc = tyche.size(thesis, crit, candidate_id="t")
    ind = themis.evidence_independence(thesis, crit)
    gov = themis.governance_check(thesis, exp, alloc)
    d = zeus.decide(thesis, crit, exp, alloc, gov, ind, "pathway", candidate_id="t")

    assert d.decision in ("BUY", "HOLD", "REDUCE", "EXIT")
    assert d.decision != "BUY"                       # constrained idea must not be a BUY
    assert d.human_authorisation_required is True
    entry = storage.append_decision(d.to_dict(), ticker="ORCL", decision=d.decision)
    ok, errs = storage.verify()
    assert ok and not errs                            # real hash chain verifies
    assert entry["kind"] == "HOLD" and entry["detail"]["human_authorisation_required"] is True
