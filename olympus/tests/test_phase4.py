"""Phase 4 — journaling/post-mortem + the walled-off screener benchmark.

Proves: the journal records decisions; post-mortem classifies a resolved decision; the screener
runs (and fails loud on missing data) and is PROVABLY firewalled from the decision members; and
the scorecard carries the new naive-screener benchmark arm. Everything paper/advisory.
"""
import inspect
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage                       # noqa: E402
from olympus import journal, postmortem                # noqa: E402
from olympus.benchmark import screener                 # noqa: E402
from olympus.reports import forward_scorecard, monthly_rollup  # noqa: E402


# ── journal ───────────────────────────────────────────────────────────────────
def test_journal_records_decisions_with_context(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DECISIONS", tmp_path / "dec.jsonl")
    storage.append_decision({"decision_id": "d1", "candidate_id": "c_ORCL", "decision": "HOLD",
                             "thesis_summary": "thesis text", "evidence_independence": "correlated",
                             "confidence_constrained_by": ["weak evidence"],
                             "strongest_counter_case": "counter"}, ticker="ORCL", decision="HOLD")
    es = journal.entries()
    d = [e for e in es if e["type"] == "decision"][0]
    assert d["binding_constraint"] == ["weak evidence"] and d["council_summary"] == "correlated"


# ── post-mortem ───────────────────────────────────────────────────────────────
def test_postmortem_classifies_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "POSTMORTEMS", tmp_path / "pm.jsonl")
    postmortem.record(decision_id="d1", ticker="ORCL", verdict="worked", classification="skill",
                      why="thesis played out", thesis_drift="none")
    pms = postmortem.build()
    assert pms and pms[0]["verdict"] == "worked" and pms[0]["classification"] == "skill"
    with pytest.raises(AssertionError):
        postmortem.record(decision_id="d2", ticker="X", verdict="bogus", classification="skill",
                          why="", thesis_drift="")


# ── screener: runs + fails loud ───────────────────────────────────────────────
def _uptrend_df(n=250):
    import numpy as np
    close = pd.Series(np.linspace(100, 200, n))
    r = pd.Series(np.linspace(0.05, 0.01, n))          # range contracts over time (VCP)
    return pd.DataFrame({"Close": close, "High": close * (1 + r), "Low": close * (1 - r)})


def test_screener_runs_on_injected_data():
    picks = screener.screen(universe=["AAA", "BBB"], top_n=2, price_fn=lambda t: _uptrend_df())
    assert picks and all(p["qualifies"] for p in picks)   # uptrend + contracting + RS>0


def test_screener_fails_loud_on_missing_data():
    with pytest.raises(screener.ScreenerDataError):
        screener.screen(universe=["AAA"], price_fn=lambda t: pd.DataFrame({"Close": [1, 2, 3]}))


# ── HARD FIREWALL: screener absent from every decision member ─────────────────
def test_screener_firewalled_from_decision_loop():
    import olympus.loop as loop
    from olympus.members import zeus, tyche
    from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter
    members = [loop, zeus, tyche, oracle_adapter, athena_nemesis_adapter, hecate_adapter]
    for m in members:
        assert not hasattr(m, "screener"), f"{m.__name__} must not reference the screener"
        src = inspect.getsource(m)
        assert "benchmark.screener" not in src and "import screener" not in src, \
            f"{m.__name__} must not import the walled-off screener"


# ── scorecard benchmark arm (c) ───────────────────────────────────────────────
def test_scorecard_has_naive_screener_arm():
    sc = forward_scorecard.build(fetch=False)
    arm = sc["naive_screener_arm"]
    assert "screener_beats_passive" in arm and "olympus_vs_screener" in arm


def test_monthly_rollup_proposals_flagged_for_human():
    r = monthly_rollup.build(fetch=False)
    assert "proposed_rule_changes" in r          # proposals only — never auto-applied
    assert isinstance(r["proposed_rule_changes"], list)
