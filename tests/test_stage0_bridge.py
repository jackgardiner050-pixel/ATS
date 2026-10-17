"""B-22 — Phaethon → Stage-0 bridge."""
import pytest
import yaml

from src.phaethon.stage0_bridge import (
    rationale_to_stage0_candidate, write_stage0_candidates, RationaleContainsOutcome,
)

_RATIONALE = {
    "ticker": "MU",
    "thesis_category": "AI",
    "thesis_text": "HBM capacity is sold out through 2026; pricing power underappreciated.",
    "stated_conviction": "high",
    "horizon": "2-3 quarters",
}


def test_fixture_rationale_produces_valid_stage0_candidate():
    c = rationale_to_stage0_candidate(_RATIONALE, arm="B", prompt_version="pv-2026-07",
                                      date="2026-09-03")
    assert c["stage"] == 0 and c["status"] == "CANDIDATE"           # not a registry status
    assert c["candidate_id"] == "phaethon-b-mu-2026-09-03"
    assert c["source_provenance"] == {
        "phaethon_arm": "B", "prompt_version": "pv-2026-07", "date": "2026-09-03",
        "stated_conviction": "high", "thesis_category": "AI",
    }
    assert "HBM capacity" in c["mechanism"]
    assert c["proposed_fingerprint"]["signal_family"] == "thematic_momentum"
    assert set(("licenses", "does_not_license")) <= set(c["interpretation_contract"])
    # round-trips as YAML
    assert yaml.safe_load(yaml.safe_dump(c)) == c


@pytest.mark.parametrize("bad_key", [
    "outcome", "realized_pnl", "return_pct", "win", "hold_days", "drawdown_pct", "fills",
])
def test_rationale_carrying_an_outcome_is_refused(bad_key):
    r = dict(_RATIONALE, **{bad_key: 1})
    with pytest.raises(RationaleContainsOutcome):
        rationale_to_stage0_candidate(r, arm="A", prompt_version="pv", date="2026-09-03")


def test_write_emits_one_yaml_per_rationale(tmp_path):
    paths = write_stage0_candidates(
        [_RATIONALE, dict(_RATIONALE, ticker="NVDA")],
        arm="A", prompt_version="pv-1", date="2026-09-03", out_dir=tmp_path)
    assert len(paths) == 2 and all(p.exists() and p.suffix == ".yaml" for p in paths)
    loaded = yaml.safe_load(paths[0].read_text())
    assert loaded["status"] == "CANDIDATE" and loaded["source_provenance"]["phaethon_arm"] == "A"
    # written to a plain dir, NOT the hash-chained registry
    assert "registry.yaml" not in [p.name for p in tmp_path.iterdir()]


def test_missing_ticker_raises():
    with pytest.raises(ValueError):
        rationale_to_stage0_candidate({"thesis_text": "x"}, arm="A", prompt_version="pv")
