"""Olympus v2 — the growth-discovery brain. PAPER/SIMULATED.

Proves: growth rationale BUYS a consensus leader when warranted (no priced-in veto); the three arms
partition correctly (A leaders ⊂ , C bottlenecks ⊂ , B a genuine mix); Hephaestus tags leader vs
second-order; the catalyst/IPO feed surfaces PUBLIC beneficiaries (never the private IPO); harvest-
into-core and the tight exit/thesis-break both fire; the growth path NEVER writes Oracle's ledger;
the sole venue is the internal PaperBroker (T212 never constructed); LiveBroker unreachable.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage, arm_portfolio as AP                     # noqa: E402
from olympus.core.constants import MAX_INITIAL                            # noqa: E402
from olympus.discovery import hephaestus, chronos, catalyst_feed, growth_discovery as GD  # noqa: E402
from olympus.adapters import oracle_adapter as OA, athena_nemesis_adapter as AN, hecate_adapter as HC  # noqa: E402
from olympus.adapters import execution as EX                              # noqa: E402
from olympus.members import mandate                                       # noqa: E402
from olympus.models.records import Critique                               # noqa: E402
from olympus import arms                                                  # noqa: E402
import olympus.growth_loop as GL                                          # noqa: E402


# ── Hephaestus tags leader vs second-order ────────────────────────────────────
def test_hephaestus_tags_leader_vs_bottleneck():
    cands = hephaestus.map_value_chain(enrich=False)
    nvda = [c for c in cands if c.ticker == "NVDA"]
    amkr = [c for c in cands if c.ticker == "AMKR" and c.theme == "ai_compute"]
    assert nvda and all(c.role == "leader" for c in nvda)                 # NVDA = obvious leader
    assert amkr and amkr[0].role == "bottleneck" and amkr[0].enabler     # AMKR = second-order enabler
    assert hephaestus.role_of("NVDA") == "leader"
    assert hephaestus.role_of("AMKR", theme="ai_compute") == "bottleneck"


# ── three arms partition correctly ────────────────────────────────────────────
def test_three_arms_partition():
    c = GD.discover(enrich=False)
    A = GD.for_arm(c, arms.allowed_roles("A"))
    B = GD.for_arm(c, arms.allowed_roles("B"))
    C = GD.for_arm(c, arms.allowed_roles("C"))
    assert all(x.role == "leader" for x in A)                             # A = leaders only
    assert all(x.role == "bottleneck" for x in C)                        # C = bottlenecks only
    roles_B = {x.role for x in B}
    assert "leader" in roles_B and "bottleneck" in roles_B              # B = a genuine mix
    assert chronos.is_frothy("quantum_compute")                          # froth flagged
    assert "IONQ" not in [x.ticker for x in A]                           # frothy top NOT bought


# ── catalyst/IPO feed surfaces beneficiaries, never the private IPO ───────────
def test_catalyst_feed_surfaces_beneficiaries_not_ipo():
    ben = catalyst_feed.beneficiaries()
    tickers = {c.ticker for c in ben}
    assert {"AMZN", "GOOGL", "MSFT"} & tickers                          # public holders surfaced
    assert not ({"ANTHROPIC", "OPENAI", "SPACEX"} & tickers)            # private companies NEVER as tickers
    anth = [c for c in ben if "Anthropic" in c.catalyst]
    assert anth and all(c.status == "attention" for c in anth)          # awareness only


# ── growth rationale BUYS a consensus leader (no priced-in veto) ──────────────
def _consensus_leader_thesis(ticker, *, role="leader", theme="ai_compute", enabler="", stage="mid",
                             client=None, tracker=None):
    """A durable, well-owned, at/above-target consensus leader — v1 would have vetoed this; v2 buys it."""
    grade = OA._growth_evidence_grade("durable", "accelerating", "confirming")
    return {"ticker": ticker, "bias": "BUY", "conviction_pct": 72, "horizon": "6-12 months",
            "thesis_summary": f"{ticker} consensus leader, durable accelerating growth",
            "evidence_grade": grade,
            "benchmark_alternative": {"priced_in_stance": "GROWTH", "growth_durability": "durable",
                                      "assessment": "durable/accelerating"},
            "invalidation": "growth decelerates or momentum rolls over", "review_by": "next quarter",
            "overlap_is_more_ai": False, "diversifying": True, "role": role, "theme": theme,
            "growth_durability": "durable", "growth_trend": "accelerating", "momentum_state": "confirming",
            "quality": "high", "as_of_date": "2026-06-04", "_raw": {"as_of_date": "2026-06-04"}}


def test_growth_buys_consensus_leader(monkeypatch):
    monkeypatch.setattr(OA, "rate_growth", _consensus_leader_thesis)
    from olympus.discovery import hephaestus as H
    cand = next(c for c in H.map_value_chain(enrich=False) if c.ticker == "NVDA")
    decision, thesis, alloc, cid = GL._govern_growth(cand, [], client=object(), tracker=None)
    assert thesis["evidence_grade"] == "strong"                          # durable+accelerating
    assert decision.decision == "BUY"                                    # consensus leader EARNS a buy
    assert alloc.target_allocation > 0


# ── harvest-into-core fires on a run-hard winner ──────────────────────────────
def test_harvest_into_core_fires():
    book = {"mode": "paper/simulated", "core_value": 9000.0, "cash": 0.0,
            "satellite": {"NVDA": {"shares": 10.0, "last_price": 160.0, "cost_basis": 100.0}}}  # +60%
    res = mandate.harvest_plan(book)
    assert res["n_harvests"] == 1 and res["orders"][0].side == "SELL"     # winner harvested
    assert res["per_position"][0]["run_hard"] is True


# ── tight exit / thesis-break fires ───────────────────────────────────────────
def test_exit_on_thesis_break_and_momentum_break():
    book = {"mode": "paper/simulated", "core_value": 9000.0, "cash": 0.0, "satellite": {
        "AAA": {"shares": 5.0, "last_price": 100.0, "cost_basis": 90.0, "high": 100.0},   # thesis-break
        "BBB": {"shares": 5.0, "last_price": 70.0, "cost_basis": 90.0, "high": 100.0}}}    # -30% from high
    theses = {"AAA": {"growth_durability": "peaking", "growth_trend": "decelerating", "momentum_state": "neutral"},
              "BBB": {"growth_durability": "durable", "growth_trend": "steady", "momentum_state": "confirming"}}
    res = mandate.exit_plan(book, theses)
    acted = {p["ticker"]: p["action"] for p in res["per_position"]}
    assert acted.get("AAA") == "EXIT"                                    # peaking/decel → exit
    assert acted.get("BBB") == "EXIT"                                    # -30% from high → momentum-break exit
    assert res["n_exits"] == 2


# ── growth path never writes Oracle's ledger; sole venue is PaperBroker ───────
def test_growth_path_does_not_write_oracle_ledger(monkeypatch, tmp_path):
    """rate_growth must not append to Oracle's forward-test ledger (byte-identical preserved)."""
    import olympus.adapters.oracle_adapter as OAD
    calls = {"logged": 0}
    monkeypatch.setattr(OAD.FT, "log_rating", lambda *a, **k: calls.__setitem__("logged", calls["logged"] + 1))
    monkeypatch.setattr(OAD, "_public_context", lambda t: f"ctx for {t}")
    monkeypatch.setattr(OAD.LLM if hasattr(OAD, "LLM") else __import__("olympus.adapters.oracle_llm", fromlist=["x"]),
                        "growth_thesis", lambda *a, **k: {"bias": "BUY", "conviction": 70,
                        "growth_durability": "durable", "growth_trend": "accelerating",
                        "momentum_state": "confirming", "invalidation": {"line": "x", "by_when": "Q3"},
                        "causal_thesis": "t", "quality": "high"})
    OAD.rate_growth("NVDA", role="leader", theme="ai_compute", client=object())
    assert calls["logged"] == 0                                          # Oracle ledger untouched


def test_paperbroker_is_sole_venue_live_unreachable():
    assert GL.PaperBroker().mode == EX.PAPER_MODE                        # PaperBroker is the venue
    assert "t212" not in GL.__dict__ and not any("t212" in str(v) for v in [GL.PaperBroker])
    with pytest.raises(Exception):
        EX.make_broker("live")                                          # live refused
    with pytest.raises(Exception):
        EX.LiveBroker()                                                 # never built
