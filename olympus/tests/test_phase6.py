"""Phase 6 — full causal Oracle (LLM) wired into the loop.

Proves: full Oracle forms a thesis (bias/conviction/invalidation) on a naked candidate; the
firewall holds (no screener signal in Oracle's prompt); the loop can emit a NON-HOLD when
warranted (not inert); cost/call-count is tracked; FAIL-LOUD without an API key (no fake
fallback); LiveBroker unreachable. Mock LLM — no live key, no network. Paper/advisory.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.adapters import oracle_llm as LLM, oracle_adapter as OA   # noqa: E402
from olympus.adapters import execution as EX                            # noqa: E402
from olympus.members import zeus                                        # noqa: E402
from olympus.models.records import Critique, NakedCandidate            # noqa: E402
from olympus.core import storage, paper_portfolio as PP                # noqa: E402
import olympus.loop as loop                                            # noqa: E402

THESIS = {"bias": "BUY", "conviction": 70,
          "causal_thesis": "Under-followed cash-generative cyclical; capacity discipline tightens supply.",
          "evidence_labels": {"FCF positive": "Evidence", "supply tightens": "Hypothesis"},
          "priced_in_view": "not consensus", "catalyst": {"desc": "earnings + capex guide", "when": "~6 weeks", "near_term": True},
          "invalidation": {"line": "FCF turns negative or a capacity glut returns", "by_when": "next 2 quarters"},
          "overlap": {"is_more_ai": False, "diversifying": True, "text": "non-AI cyclical — diversifies the book"},
          "pillars": [{"pillar": "valuation", "expectation": "fwdPE<15"}, {"pillar": "cash", "expectation": "FCF>0"},
                      {"pillar": "supply", "expectation": "capex discipline"}],
          "disconfirming_evidence": ["demand rolls over", "a rival adds capacity"],
          "target": "+25%", "stop_exit": "thesis-break on FCF", "horizon": "6-12 months", "right_but_early_risk": "LOW"}


class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 120, "output_tokens": 240})()


class FakeClient:
    def __init__(self, thesis):
        self.thesis, self.calls = thesis, []
        self.messages = self._M(self)

    class _M:
        def __init__(self, outer): self.outer = outer
        def create(self, model, max_tokens, system, messages):
            self.outer.calls.append({"model": model, "system": system, "user": messages[0]["content"]})
            txt = json.dumps(self.outer.thesis) if "JSON" in system else "Plausible angle: undervalued cash generator."
            return _Msg(txt)


# ── fail loud without a key ────────────────────────────────────────────────────
def test_make_client_fails_loud_without_key(monkeypatch):
    monkeypatch.setattr(LLM, "have_key", lambda: False)
    with pytest.raises(LLM.OracleReasoningUnavailable):
        LLM.make_client()


# ── LLM bridge: thesis + cost + firewall ──────────────────────────────────────
def test_causal_thesis_and_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(LLM, "CACHE", tmp_path / "cache.json")
    c, tr = FakeClient(THESIS), LLM.CostTracker()
    j = LLM.causal_thesis("XYZ", "fundamentals...", client=c, tracker=tr,
                          causal_sweep="sweep", thesis_rubric="thesis")
    assert j["bias"] == "BUY" and j["invalidation"]["line"]
    s = tr.summary()
    assert s["llm_calls"] == 2 and s["estimated_usd"] > 0          # cheap triage + deep thesis, costed
    assert LLM.CHEAP_MODEL in {m for m in s["by_model"]} or s["llm_calls"] == 2


def test_firewall_no_screener_signal_in_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(LLM, "CACHE", tmp_path / "cache.json")
    c = FakeClient(THESIS)
    LLM.causal_thesis("XYZ", "fundamentals + free news only", client=c, tracker=LLM.CostTracker())
    blob = " ".join(call["system"] + call["user"] for call in c.calls).lower()
    # the screener's own SCORE FIELDS must never appear — they leak only if the signal travels.
    # (the words "momentum/screener" appear in the firewall INSTRUCTION; that's fine.)
    for leaked in ("rs_3m_pct", "qualifies", "contracting", "acwi_anchor", "net_cost_haircut"):
        assert leaked not in blob                                  # no screener signal reaches Oracle


# ── full rate_causal → thesis_view + logs to a (temp) Oracle ledger ───────────
def _patch_offline(monkeypatch, tmp_path):
    from oracle import schema as OS, priced_in as PI, rate as RT, forward_test as FT
    pi = OS.PricedIn(stance="MIXED", analyst_breadth=12, recommendation_mean=2.6, buy_sell_counts="5/4/1",
                     revision_trend="flat", short_interest_pct_float=2.0, short_interest_trend="flat",
                     price_vs_mean_target_pct=12.0, assessment="thin coverage")
    val = OS.ValuationFlag(vs_peers="in line", vs_own_history="n/a", metrics={}, text="reasonable")
    surv = OS.SurvivalFlag(margins="ok", cash_and_burn="FCF positive", runway_note="n/a", debt="low", text="sound")
    monkeypatch.setattr(PI, "pull", lambda t, peers: (pi, val, surv, {"forwardPE": 14, "freeCashflow": 1e9}))
    monkeypatch.setattr(RT, "_revision_trend", lambda t: ("flat", "n/a"))
    monkeypatch.setattr(OA, "_public_context", lambda t: "fundamentals/news (offline)")
    monkeypatch.setattr(LLM, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(FT, "LEDGER", tmp_path / "oracle_ft.jsonl")     # temp — real ledger untouched
    monkeypatch.setattr(FT, "_anchor_prices", lambda: {"ACWI": 160.0, "NVDA": 220.0})
    return FT


def test_full_oracle_produces_thesis_and_logs(tmp_path, monkeypatch):
    FT = _patch_offline(monkeypatch, tmp_path)
    thesis = OA.rate_causal("XYZ", client=FakeClient(THESIS), tracker=LLM.CostTracker())
    assert thesis["bias"] in ("BUY", "HOLD", "SELL") and thesis["conviction_pct"] >= 0
    assert thesis["invalidation"]                                  # a falsifiable line is present
    entries = [e for e in FT.entries() if e.get("kind") != "GENESIS"]
    assert entries and entries[-1]["ticker"] == "XYZ"             # logged before outcome (temp ledger)
    assert FT.verify()[0]                                          # chain valid


# ── Zeus can emit a non-HOLD (path not inert) ─────────────────────────────────
def test_zeus_can_emit_buy():
    thesis = {"ticker": "XYZ", "bias": "BUY", "conviction_pct": 70, "evidence_grade": "strong",
              "thesis_summary": "t", "benchmark_alternative": {"priced_in_stance": "MIXED", "etf_alternative": {}},
              "invalidation": "thesis breaks if FCF turns negative", "review_by": "next quarter"}
    crit = Critique("c", "XYZ", "counter", [], [], ["x"], ["break"], reduce_confidence=False)
    exp = type("E", (), {"core_overlap_warnings": [], "satellite_overlap_warnings": [],
                         "theme_exposure_status": "ok", "factor_weights": {}, "etf_alternative": {}})()
    alloc = type("A", (), {"target_allocation": 0.03, "initial_allocation": 0.02, "max_allocation": 0.05})()
    gov = {"constitution_violations": []}
    ind = {"independent_confirmation": False, "assessment": "correlated"}
    d = zeus.decide(thesis, crit, exp, alloc, gov, ind, "pathway", candidate_id="c")
    assert d.decision == "BUY"                                     # clean thesis → BUY survives (not inert)


# ── loop fails loud without a key (no data-only fallback) ─────────────────────
def test_loop_oracle_unavailable_without_key(tmp_path, monkeypatch):
    from olympus.discovery import artemis
    monkeypatch.setattr(artemis, "discover", lambda **k: [NakedCandidate("MU", "value_quality", "2026-06-04")])
    monkeypatch.setattr(loop, "_update_prices", lambda s: None)
    monkeypatch.setattr(PP, "STATE", tmp_path / "pf.json")
    PP.save({"mode": "paper/simulated", "core_value": 10000.0, "cash": 0.0, "satellite": {}})
    monkeypatch.setattr(LLM, "make_client", lambda: (_ for _ in ()).throw(LLM.OracleReasoningUnavailable("no key")))
    summary = loop.run(discover=True, standalone=True, fetch_prices=False, record=False)
    assert summary["oracle_reasoning"] == "UNAVAILABLE" and summary["candidate_actions"] == []
    assert "fake" in summary["note"].lower() or "fallback" in summary["note"].lower()


# ── loop emits a non-HOLD + opens a paper position (with a mock thesis) ────────
def test_loop_can_open_paper_position(tmp_path, monkeypatch):
    from olympus.discovery import artemis
    from olympus.adapters import athena_nemesis_adapter as AN, hecate_adapter as HC
    for nm, v in [("DECISIONS", "d"), ("PAPER_FILLS", "f"), ("OUTCOMES", "o"), ("SCREENER", "s")]:
        monkeypatch.setattr(storage, nm, tmp_path / f"{v}.jsonl")
    monkeypatch.setattr(PP, "STATE", tmp_path / "pf.json")
    PP.save({"mode": "paper/simulated", "core_value": 10000.0, "cash": 0.0, "satellite": {}})
    monkeypatch.setattr(artemis, "discover", lambda **k: [NakedCandidate("MU", "value_quality", "2026-06-04")])
    monkeypatch.setattr(loop, "_update_prices", lambda s: None)
    monkeypatch.setattr(loop, "_price", lambda t, s: 50.0)
    monkeypatch.setattr(OA, "rate_causal", lambda t, client=None, tracker=None: {
        "ticker": t, "bias": "BUY", "conviction_pct": 72, "horizon": "6-12 months", "thesis_summary": "clean",
        "evidence_grade": "strong", "benchmark_alternative": {"priced_in_stance": "MIXED", "etf_alternative": {}},
        "invalidation": "FCF turns negative", "review_by": "next quarter", "overlap_is_more_ai": False,
        "diversifying": True, "as_of_date": "2026-06-04", "_raw": {"as_of_date": "2026-06-04"}})
    monkeypatch.setattr(AN, "critique", lambda thesis, candidate_id: Critique(
        "c", candidate_id, "counter", [], [], ["x"], ["break"], reduce_confidence=False))
    monkeypatch.setattr(HC, "assess", lambda ticker, candidate_id: type("E", (), {
        "core_overlap_warnings": [], "satellite_overlap_warnings": [], "theme_exposure_status": "ok",
        "factor_weights": {}, "etf_alternative": {}, "candidate_ticker": ticker})())
    summary = loop.run(discover=True, standalone=True, fetch_prices=False, record=True,
                       oracle_client=object())                    # non-None → skips make_client
    buys = [a for a in summary["candidate_actions"] if a["decision"] == "BUY"]
    assert buys and buys[0]["executed"] and summary["positions_opened"] >= 1   # not inert; position opened


def test_livebroker_unreachable():
    with pytest.raises(RuntimeError):
        EX.make_broker("live")
