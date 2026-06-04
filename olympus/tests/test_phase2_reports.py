"""Phase 2 — real-seam tests for the five reports + the two new CLI write-commands.

Write-paths use temp ledgers (monkeypatched) so the real local ledgers aren't polluted, but
they still exercise the REAL pit_ledger primitive and the REAL Oracle harness / governance.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus import cli                                  # noqa: E402
from olympus.core import storage                          # noqa: E402
from olympus.reports import (exposure_report, forward_scorecard,                      # noqa: E402
                             override_audit, success_audit, quarterly_review)
from oracle import forward_test as FT                     # noqa: E402


# ── reports ───────────────────────────────────────────────────────────────────
def test_exposure_report_runs_real_engine():
    exp = exposure_report.build("ORCL")
    assert exp.factor_weights and exp.satellite_theme_weights      # real exposure engine output
    assert any("duplicate core" in w or "CORE NOT SUPPLIED" in w for w in exp.core_overlap_warnings)
    assert "ORCL" in exposure_report.render(exp)


def test_scorecard_wired_to_oracle_harness():
    sc = forward_scorecard.build(fetch=False)
    assert sc["policy"] is FT.VERDICT_POLICY                       # reuses the real harness policy
    assert sc["n_oracle_ratings"] >= 1 and sc["research_grade"] is True
    assert "RESEARCH-GRADE" in forward_scorecard.render(sc)


def test_scorecard_resolved_metrics_populate(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTCOMES", tmp_path / "out.jsonl")
    storage.append_outcome({"outcome_id": "o1", "decision_id": "d1", "measurement_date": "2027-01-01",
                            "asset_return": 12.0, "benchmark_return": 4.0, "etf_alternative_return": 6.0,
                            "relative_return": 8.0, "skill_luck_beta_classification": "skill",
                            "conviction": 72}, ticker="ZZZ")
    sc = forward_scorecard.build(fetch=False)
    assert sc["n_resolved"] == 1
    assert sc["metrics"]["hit_rate_pct"] == 100.0                  # 1/1 positive relative
    assert sc["calibration_by_band"]["70-80"] == 100.0


def test_override_audit_reads_real_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OVERRIDES", tmp_path / "ovr.jsonl")
    monkeypatch.setattr(storage, "DECISIONS", tmp_path / "dec.jsonl")
    storage.append_decision({"decision_id": "d1", "candidate_id": "c_ORCL", "decision": "HOLD"},
                            ticker="ORCL", decision="HOLD")
    storage.append_override({"decision_id": "d1", "zeus_decision": "HOLD", "human_action": "SKIP",
                            "rationale": "covered by core"}, ticker="ORCL")
    a = override_audit.build()
    assert a["n_overrides"] == 1 and a["rows"][0]["human_action"] == "SKIP"


def test_success_audit_classifies_major_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTCOMES", tmp_path / "out.jsonl")
    storage.append_outcome({"outcome_id": "o1", "decision_id": "d1", "asset_return": 30.0,
                            "benchmark_return": 5.0, "etf_alternative_return": 28.0,
                            "skill_luck_beta_classification": "beta"}, ticker="ZZZ")
    s = success_audit.build()
    assert s["n_major"] == 1 and "beta" in s["by_class"]


def test_quarterly_review_real_members():
    q = quarterly_review.build(fetch=False)
    assert len(q["member_usefulness"]) == 7                        # all MVP members accounted for
    assert "decision_counts" in q and "deferred_rejected" in q


# ── new CLI write-commands ────────────────────────────────────────────────────
def test_cli_override_add(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DECISIONS", tmp_path / "dec.jsonl")
    monkeypatch.setattr(storage, "OVERRIDES", tmp_path / "ovr.jsonl")
    storage.append_decision({"decision_id": "dX", "candidate_id": "c_ORCL", "decision": "HOLD"},
                            ticker="ORCL", decision="HOLD")
    rc = cli.main(["override", "add", "--decision", "dX", "--action", "SKIP", "--rationale", "core covers it"])
    assert rc == 0
    ovs = [e for e in storage.overrides() if e.get("kind") != "GENESIS"]
    assert ovs and ovs[-1]["detail"]["override"]["human_action"] == "SKIP"
    ok, errs = storage.verify(storage.OVERRIDES)
    assert ok and not errs                                         # real hash chain verifies


def test_cli_outcome_add(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTCOMES", tmp_path / "out.jsonl")
    rc = cli.main(["outcome", "add", "--decision", "dX", "--ticker", "ORCL",
                   "--asset-return", "-2.5", "--benchmark-return", "-0.7", "--etf-return", "-4.4",
                   "--classification", "unresolved"])
    assert rc == 0
    outs = [e for e in storage.outcomes() if e.get("kind") != "GENESIS"]
    assert outs and outs[-1]["detail"]["outcome"]["relative_return"] == -1.8
