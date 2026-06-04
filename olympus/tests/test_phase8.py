"""Phase 8 — recalibrated Actionable bar (pre-registered, LOCKED, one-time).

Proves: the new bar applies (6.6 → BUY, 6.4 → HOLD); the bar is FIXED config not iteratively
tuned (its sha256 is locked → SpecIntegrityError on any edit); near-bar names earn SMALL
conviction-weighted positions; the pruned universe has no dead tickers (CIVI gone); deploy opens
a paper book when a BUY survives; the demo venue fails over to a CLEARLY-LABELLED internal sim
(never faking demo); LiveBroker stays unreachable. Mocked Oracle (no LLM key). Paper/advisory.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage, paper_portfolio as PP                    # noqa: E402
from olympus.core import constants as C                                    # noqa: E402
from olympus.core.constants import band_for                                # noqa: E402
from olympus.preregistration import spec as SPEC                           # noqa: E402
from olympus.preregistration.spec import SpecIntegrityError               # noqa: E402
from olympus.models.records import Critique, NakedCandidate                # noqa: E402
from olympus.members import zeus                                           # noqa: E402
from olympus.adapters import oracle_adapter as OA, athena_nemesis_adapter as AN, hecate_adapter as HC  # noqa: E402
from olympus.adapters import execution as EX                              # noqa: E402
from olympus.discovery import artemis                                      # noqa: E402
from olympus import journal                                               # noqa: E402
import olympus.loop as loop                                               # noqa: E402


# ── A. the new bar applies: 6.6 → BUY, 6.4 → HOLD ─────────────────────────────
def test_band_for_uses_locked_65_bar():
    assert C.ACTIONABLE_CONVICTION == 65                       # 6.5 on the 10-scale
    assert band_for("moderate", 66) == "actionable"           # 6.6 → BUY-eligible
    assert band_for("moderate", 64) == "research"             # 6.4 → below bar → HOLD
    assert band_for("moderate", 65) == "actionable"           # exactly at the bar earns a small position
    # full size still needs ≥75 AND strong evidence
    assert band_for("moderate", 80) == "actionable"           # strong conviction, weak evidence → small
    assert band_for("strong", 80) == "high_conviction"        # ≥75 + strong → full band
    assert band_for("weak", 90) == "research"                 # weak evidence vetoes regardless


def _zeus_inputs(conviction, evidence="moderate", initial=0.02):
    thesis = {"bias": "BUY", "conviction_pct": conviction, "evidence_grade": evidence,
              "thesis_summary": "clean", "invalidation": "FCF turns negative", "review_by": "Q3",
              "benchmark_alternative": {"priced_in_stance": "MIXED"}}
    critique = Critique("c", "cand", "counter", [], [], ["risk"], ["break"], reduce_confidence=False)
    exposure = type("E", (), {"core_overlap_warnings": [], "satellite_overlap_warnings": [],
                              "theme_exposure_status": "ok", "factor_weights": {}, "etf_alternative": {}})()
    allocation = type("A", (), {"initial_allocation": initial, "target_allocation": 0.02,
                                "max_allocation": 0.03})()
    governance = {"constitution_violations": []}
    independence = {"independent_confirmation": True, "assessment": "independent"}
    return thesis, critique, exposure, allocation, governance, independence


def test_zeus_66_buys_64_holds():
    # 6.6, evidence moderate, non-zero allocation → BUY survives (soft constraints no longer veto)
    t, c, e, a, g, i = _zeus_inputs(66, initial=0.012)
    d = zeus.decide(t, c, e, a, g, i, "advisory", candidate_id="cand")
    assert d.decision == "BUY" and d.conviction_pct == 66
    # 6.4 → below the bar → band_for gives 'research' → zero allocation → hard_block → HOLD
    t2, c2, e2, _, g2, i2 = _zeus_inputs(64)
    zero_alloc = type("A", (), {"initial_allocation": 0.0, "target_allocation": 0.0, "max_allocation": 0.0})()
    d2 = zeus.decide(t2, c2, e2, zero_alloc, g2, i2, "advisory", candidate_id="cand")
    assert d2.decision == "HOLD" and d2.conviction_pct == 64          # conviction still recorded truthfully


def test_no_invalidation_still_blocks_buy():
    # the bar moved, but a falsifiable invalidation line is STILL required for any BUY
    t, c, e, a, g, i = _zeus_inputs(70, initial=0.02)
    t["invalidation"] = ""
    d = zeus.decide(t, c, e, a, g, i, "advisory", candidate_id="cand")
    assert d.decision == "HOLD"


# ── B. the bar is FIXED config, not iteratively tuned (locked hash) ───────────
def test_bar_is_locked_one_time():
    spec = SPEC.load_spec("actionable_bar_v1")
    assert spec["actionable_conviction_pct"] == 65
    assert spec["lock"]["one_time"] is True
    assert "do NOT iteratively lower" in spec["lock"]["do_not_lower_further"].replace("Do NOT", "do NOT")


def test_editing_the_bar_breaks_the_lock(tmp_path, monkeypatch):
    """Any attempt to iteratively lower the bar changes the YAML → hash mismatch → refused."""
    y = (Path(SPEC.__file__).resolve().parent / "actionable_bar_v1.yaml")
    tampered = tmp_path / "actionable_bar_v1.yaml"
    sha = tmp_path / "actionable_bar_v1.yaml.sha256"
    tampered.write_text(y.read_text().replace("actionable_conviction_pct: 65",
                                              "actionable_conviction_pct: 55"))   # try to lower further
    sha.write_text((Path(SPEC.__file__).resolve().parent / "actionable_bar_v1.yaml.sha256").read_text())
    monkeypatch.setattr(SPEC, "_HERE", tmp_path)
    SPEC.load_spec.cache_clear()
    with pytest.raises(SpecIntegrityError):
        SPEC.load_spec("actionable_bar_v1")
    SPEC.load_spec.cache_clear()                              # restore the real (locked) spec for other tests


# ── C. pruned universe: no dead tickers ───────────────────────────────────────
def test_universe_has_no_dead_tickers():
    assert "CIVI" not in artemis.UNIVERSE                     # delisted/404 → pruned
    assert len(artemis.UNIVERSE) == len(set(artemis.UNIVERSE))


def test_artemis_skips_a_404_symbol_without_aborting():
    """A single dead/404 symbol fails-loud-SKIP — it must not abort the whole discovery run."""
    def fundamentals(t):
        if t == "DEADX":
            raise artemis.DiscoveryDataError("404 not found")
        return {"forwardPE": 12.0, "freeCashflow": 1e9, "debtToEquity": 50.0,
                "currentPrice": 50.0, "averageDailyVolume10Day": 1_000_000}
    out = artemis._value_quality_source(["DEADX", "GOOD"], fundamentals)
    assert out == ["GOOD"]                                     # survived the bad symbol


# ── D. deploy opens a book when a BUY survives ────────────────────────────────
def _seed_below_target():
    return {"mode": "paper/simulated", "core_value": 90000.0, "cash": 0.0,
            "satellite": {t: {"shares": 1.0, "last_price": 2000.0, "cost_basis": 2000.0}
                          for t in ("AA", "BB", "CC")}}


def _mock_members(monkeypatch, convictions):
    def rate(t, client=None, tracker=None):
        c = convictions.get(t, 50)
        return {"ticker": t, "bias": "BUY" if c >= 60 else "HOLD", "conviction_pct": c,
                "horizon": "6-12 months", "thesis_summary": f"thesis {t}", "evidence_grade": "moderate",
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


def test_near_bar_name_opens_a_small_book(tmp_path, monkeypatch):
    """A 66-conviction (just over the 6.5 bar) name BUYS and earns a SMALL conviction-weighted size."""
    _ledgers(monkeypatch, tmp_path)
    PP.save(_seed_below_target())
    monkeypatch.setattr(artemis, "discover", lambda **k: [
        NakedCandidate("MU", "value_quality", "2026-06-04")])
    _mock_members(monkeypatch, {"MU": 66})                     # just over the bar

    s = loop.run(discover=True, standalone=True, fetch_prices=False, record=True, oracle_client=object())
    assert s["positions_opened"] == 1                          # it OPENED a book
    dep = s["deploy_toward_target"]
    per = {p["ticker"]: p["size_frac"] for p in dep["per_position"]}
    assert 0 < per["MU"] <= C.MAX_INITIAL                      # SMALL, within the initial cap
    # 66 is near the floor → size near the band floor (1%), not the ceiling (3%)
    assert per["MU"] <= 0.015
    convs = {j["ticker"]: j["conviction"] for j in journal.entries() if j["type"] == "decision"}
    assert convs.get("MU") == 66                               # true conviction recorded


def test_sub_bar_name_holds(tmp_path, monkeypatch):
    _ledgers(monkeypatch, tmp_path)
    PP.save(_seed_below_target())
    monkeypatch.setattr(artemis, "discover", lambda **k: [
        NakedCandidate("XX", "value_quality", "2026-06-04")])
    _mock_members(monkeypatch, {"XX": 64})                     # just under the bar
    s = loop.run(discover=True, standalone=True, fetch_prices=False, record=True, oracle_client=object())
    assert s["positions_opened"] == 0
    assert all(a["decision"] == "HOLD" for a in s["candidate_actions"])


# ── C/demo. unavailable demo → CLEARLY-LABELLED internal sim (never faked) ────
def test_demo_unavailable_falls_back_to_labelled_sim(tmp_path, monkeypatch):
    from olympus.adapters.t212_demo import T212Unavailable
    _ledgers(monkeypatch, tmp_path)
    PP.save(_seed_below_target())
    monkeypatch.setattr(artemis, "discover", lambda **k: [NakedCandidate("MU", "value_quality", "2026-06-04")])
    _mock_members(monkeypatch, {"MU": 66})

    def _no_demo(mode):
        if mode == "t212_demo":
            raise T212Unavailable("no valid Invest-API demo key")
        return EX.make_broker(mode)
    monkeypatch.setattr(loop, "make_broker", _no_demo)

    s = loop.run(discover=True, standalone=True, fetch_prices=False, record=True,
                 broker_mode="t212_demo", oracle_client=object())
    assert "NOT demo" in s["execution_venue"]                  # clearly labelled, not faked
    assert "internal_sim" in s["execution_venue"]
    assert "unavailable" in s["demo_status"].lower()


# ── E. LiveBroker stays unreachable ───────────────────────────────────────────
def test_live_broker_unreachable():
    with pytest.raises(Exception):
        EX.make_broker("live")                                 # 'live' is refused
    with pytest.raises(Exception):
        EX.LiveBroker()                                        # construction itself raises (never built)
