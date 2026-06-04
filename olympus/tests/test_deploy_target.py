"""Deploy-toward-target — conviction-weighted, honest, never forced (paper).

From a below-target standalone start the loop opens an initial paper book in its top-conviction
discovered names, sized by conviction within the bands; a deliberately weak candidate set results
in UNDER-deployment, not forced buys. The journal shows each position's true conviction; the
scorecard begins tracking. Mock Oracle (no LLM key). Paper/advisory.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage, paper_portfolio as PP   # noqa: E402
from olympus.models.records import Critique, NakedCandidate  # noqa: E402
from olympus.adapters import oracle_adapter as OA, athena_nemesis_adapter as AN, hecate_adapter as HC  # noqa: E402
from olympus import journal                                # noqa: E402
import olympus.loop as loop                                # noqa: E402


def _below_target_seed():
    # core 90k + 5 small satellite names (2k each) = 10% satellite → below the 30% target
    return {"mode": "paper/simulated", "core_value": 90000.0, "cash": 0.0,
            "satellite": {t: {"shares": 1.0, "last_price": 2000.0, "cost_basis": 2000.0}
                          for t in ("AA", "BB", "CC", "DD", "EE")}}


def _mock_members(monkeypatch, convictions: dict):
    """Oracle returns a clean thesis per ticker with the given conviction; critique/Hecate clean."""
    def rate(t, client=None, tracker=None):
        c = convictions.get(t, 50)
        bias = "BUY" if c >= 60 else "HOLD"
        return {"ticker": t, "bias": bias, "conviction_pct": c, "horizon": "6-12 months",
                "thesis_summary": f"clean thesis for {t}", "evidence_grade": "moderate",
                "benchmark_alternative": {"priced_in_stance": "MIXED", "etf_alternative": {}},
                "invalidation": "FCF turns negative", "review_by": "next quarter",
                "overlap_is_more_ai": False, "diversifying": True,
                "as_of_date": "2026-06-04", "_raw": {"as_of_date": "2026-06-04"}}
    monkeypatch.setattr(OA, "rate_causal", rate)
    monkeypatch.setattr(AN, "critique", lambda thesis, candidate_id: Critique(
        "c", candidate_id, "counter", [], [], ["x"], ["break"], reduce_confidence=False))
    monkeypatch.setattr(HC, "assess", lambda ticker, candidate_id: type("E", (), {
        "core_overlap_warnings": [], "satellite_overlap_warnings": [], "theme_exposure_status": "ok",
        "factor_weights": {}, "etf_alternative": {}, "candidate_ticker": ticker})())
    monkeypatch.setattr(loop, "_update_prices", lambda s: None)
    monkeypatch.setattr(loop, "_price", lambda t, s: 50.0)


def _ledgers(monkeypatch, tmp):
    for nm, v in [("DECISIONS", "d"), ("PAPER_FILLS", "f"), ("OUTCOMES", "o"), ("SCREENER", "s")]:
        monkeypatch.setattr(storage, nm, tmp / f"{v}.jsonl")
    monkeypatch.setattr(PP, "STATE", tmp / "pf.json")


def test_deploys_toward_target_by_conviction(tmp_path, monkeypatch):
    _ledgers(monkeypatch, tmp_path)
    PP.save(_below_target_seed())
    from olympus.discovery import artemis
    monkeypatch.setattr(artemis, "discover", lambda **k: [
        NakedCandidate("MU", "value_quality", "2026-06-04"),
        NakedCandidate("INTC", "context", "2026-06-04"),
        NakedCandidate("KO", "watchlist", "2026-06-04")])
    _mock_members(monkeypatch, {"MU": 68, "INTC": 64, "KO": 61})

    s = loop.run(discover=True, standalone=True, fetch_prices=False, record=True, oracle_client=object())
    dep = s["deploy_toward_target"]
    assert s["positions_opened"] >= 1 and dep["deployed_value"] > 0           # it DEPLOYED
    assert dep["satellite_fraction_planned"] > dep["satellite_fraction_before"]  # moved toward target
    # conviction-weighted: highest conviction (MU 68) got the largest size
    per = {p["ticker"]: p["size_frac"] for p in dep["per_position"]}
    assert per.get("MU", 0) >= per.get("KO", 0)
    # band-capped → still under 30% (deploy TOWARD, not forced)
    assert dep["under_deployed"] is True and dep["gap_to_target"] > 0
    # journal shows each position's TRUE conviction
    jt = journal.entries()
    convs = {j["ticker"]: j["conviction"] for j in jt if j["type"] == "decision"}
    assert convs.get("MU") == 68 and convs.get("KO") == 61


def test_weak_set_under_deploys_not_forced(tmp_path, monkeypatch):
    _ledgers(monkeypatch, tmp_path)
    PP.save(_below_target_seed())
    from olympus.discovery import artemis
    monkeypatch.setattr(artemis, "discover", lambda **k: [
        NakedCandidate("MU", "value_quality", "2026-06-04"),
        NakedCandidate("INTC", "context", "2026-06-04")])
    _mock_members(monkeypatch, {"MU": 50, "INTC": 48})                        # weak → HOLD, no buys

    s = loop.run(discover=True, standalone=True, fetch_prices=False, record=True, oracle_client=object())
    dep = s["deploy_toward_target"]
    assert s["positions_opened"] == 0                                         # NOT forced
    assert dep["deployed_value"] == 0.0 and dep["under_deployed"] is True
    assert dep["gap_to_target"] > 0.15                                        # large honest gap to 30%
    assert all(a["decision"] == "HOLD" for a in s["candidate_actions"])
