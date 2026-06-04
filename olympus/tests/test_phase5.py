"""Phase 5 — Artemis discovery + discovery-driven loop.

Proves: Artemis surfaces from each source; candidates arrive NAKED (firewall — no signal travels);
the momentum screener's raw scored picks are still logged as the benchmark; the loop runs
discover→decide→execute(paper)→score; dedup + cap work; LiveBroker unreachable. Paper/advisory.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage, paper_portfolio as PP   # noqa: E402
from olympus.discovery import artemis                       # noqa: E402
from olympus.models.records import NakedCandidate           # noqa: E402
from olympus.adapters import execution as EX                # noqa: E402
import olympus.loop as loop                                 # noqa: E402


# ── injected offline data sources ─────────────────────────────────────────────
def _uptrend(n=250):
    import numpy as np
    close = pd.Series(np.linspace(100, 200, n)); r = pd.Series(np.linspace(0.05, 0.01, n))
    return pd.DataFrame({"Close": close, "High": close * (1 + r), "Low": close * (1 - r)})

def _fundamentals(t):                       # INTC/IBM look cheap+sound; others don't qualify
    return {"forwardPE": 12, "freeCashflow": 1e9, "debtToEquity": 50} if t in ("INTC", "IBM") \
        else {"forwardPE": 40, "freeCashflow": -1e9, "debtToEquity": 300}

def _context(t):                            # CSCO/TXN get "attention"
    return {"breadth": 20, "net_rating_drift": 2} if t in ("CSCO", "TXN") \
        else {"breadth": 5, "net_rating_drift": 0}


def _discover(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(storage, "SCREENER", tmp_path / "scr.jsonl")
    return artemis.discover(universe=["INTC", "IBM", "CSCO", "TXN", "KO", "JPM"],
                            price_fn=lambda t: _uptrend(), fundamentals_fn=_fundamentals,
                            context_fn=_context, **kw)


# ── Artemis surfaces from each source ─────────────────────────────────────────
def test_artemis_surfaces_from_each_source(tmp_path, monkeypatch):
    cands = _discover(monkeypatch, tmp_path)
    sources = " ".join(c.source for c in cands)
    for s in ("momentum", "value_quality", "context", "watchlist"):
        assert s in sources, f"no candidate from {s}"


# ── FIREWALL: candidates are naked, no signal travels ─────────────────────────
def test_candidates_are_naked():
    c = NakedCandidate("NVDA", "momentum", "2026-06-04")
    assert set(c.to_dict()) == {"ticker", "source", "discovery_date", "status"}
    for forbidden in ("score", "rs_3m_pct", "rank", "signal", "momentum_rank", "qualifies"):
        assert forbidden not in c.to_dict()


def test_no_screener_signal_in_decision_inputs(tmp_path, monkeypatch):
    # what the loop hands to the decision pipeline is bare (ticker, source) — no score
    monkeypatch.setattr(artemis, "discover", lambda **k: [NakedCandidate("MU", "momentum", "2026-06-04")])
    pairs = loop._discover_tickers(discover=True, fetch_prices=False)
    assert pairs == [("MU", "momentum")]                  # ticker + source only; no number


# ── screener raw picks still logged as the benchmark (unchanged) ──────────────
def test_screener_raw_picks_still_logged(tmp_path, monkeypatch):
    _discover(monkeypatch, tmp_path)                       # runs the momentum source
    picks = [e["detail"]["pick"] for e in storage.screener_picks() if e.get("detail", {}).get("pick")]
    assert picks and "rs_3m_pct" in picks[0]               # the RAW score survives in the benchmark ledger


# ── dedup + cap ───────────────────────────────────────────────────────────────
def test_dedup_and_cap(tmp_path, monkeypatch):
    cands = _discover(monkeypatch, tmp_path, top_n=4)
    tickers = [c.ticker for c in cands]
    assert len(tickers) == len(set(tickers)) <= 4          # no duplicates, capped


# ── LiveBroker unreachable ────────────────────────────────────────────────────
def test_livebroker_unreachable():
    with pytest.raises(RuntimeError):
        EX.make_broker("live")
    assert not hasattr(loop, "LiveBroker")


# ── loop: discover → decide → execute(paper) → score ──────────────────────────
def test_loop_discover_decide_execute_score(tmp_path, monkeypatch):
    for name, val in [("DECISIONS", "dec"), ("PAPER_FILLS", "fills"), ("SCREENER", "scr"),
                      ("OUTCOMES", "out")]:
        monkeypatch.setattr(storage, name, tmp_path / f"{val}.jsonl")
    monkeypatch.setattr(PP, "STATE", tmp_path / "pf.json")
    # seed the paper book OVER-band so the mandate trim demonstrably executes (paper)
    PP.save({"mode": "paper/simulated", "core_value": 70000.0, "cash": 0.0,
             "satellite": {"VRT": {"shares": 80.0, "last_price": 334.0, "cost_basis": 316.0},
                           "SMCI": {"shares": 300.0, "last_price": 50.0, "cost_basis": 42.0}}})
    # discovery returns naked candidates; no network in the loop
    monkeypatch.setattr(artemis, "discover",
                        lambda **k: [NakedCandidate("MU", "value_quality", "2026-06-04"),
                                     NakedCandidate("INTC", "context", "2026-06-04")])
    monkeypatch.setattr(loop, "_update_prices", lambda s: None)
    # rate_fresh would hit the network — give it offline, disciplined HOLDs
    monkeypatch.setattr(loop.oracle_adapter, "rate_fresh", lambda t: {
        "ticker": t, "bias": "HOLD", "conviction_pct": 52, "horizon": "6–12 months",
        "thesis_summary": "data-only", "evidence_grade": "weak",
        "benchmark_alternative": {"priced_in_stance": "MIXED", "assessment": "x"},
        "invalidation": "x", "review_by": "next quarter", "overlap_is_more_ai": False,
        "diversifying": True, "as_of_date": "2026-06-04"})

    summary = loop.run(discover=True, standalone=True, fetch_prices=False, record=True)
    assert summary["standalone_core_disregarded"] is True
    assert summary["discovery"]["n_candidates"] == 2
    assert {a["ticker"] for a in summary["candidate_actions"]} == {"MU", "INTC"}   # decided each
    assert summary["mandate"]["action"] == "trim" and summary["mandate"]["n_trims"] >= 1  # executed paper
    assert summary["paper_fills_chain_ok"] is True
