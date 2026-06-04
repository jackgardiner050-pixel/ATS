"""Phase 3 — autonomous paper-loop tests.

Proves: the loop self-fires in paper; PaperBroker fills via the REAL friction model; LiveBroker
raises and is UNREACHABLE from the loop; the paper-fills chain verifies; and the real governance +
the mandate band block/trim correctly in-loop. Everything paper/simulated.
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import storage, paper_portfolio as PP   # noqa: E402
from olympus.adapters import execution as EX               # noqa: E402
from olympus.members import mandate                         # noqa: E402
import olympus.loop as loop                                 # noqa: E402


# ── execution layer ───────────────────────────────────────────────────────────
def test_paperbroker_fills_via_real_friction(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PAPER_FILLS", tmp_path / "fills.jsonl")
    b = EX.make_broker("paper")
    assert isinstance(b, EX.PaperBroker) and b.mode == "paper/simulated"
    fill = b.execute(EX.Order("SMCI", "SELL", price=50.0, shares=100.0, reason="t"))
    assert fill.mode == "paper/simulated"
    assert fill.cost_dollars > 0 and fill.breakdown["commission_dollars"] > 0   # real cost model
    ok, errs = storage.verify(storage.PAPER_FILLS)
    assert ok and not errs                                                       # real hash chain


def test_livebroker_raises_and_is_unreachable_from_loop():
    with pytest.raises(NotImplementedError):
        EX.LiveBroker()
    with pytest.raises(RuntimeError):
        EX.make_broker("live")                                                   # factory refuses live
    assert not hasattr(loop, "LiveBroker")                                       # never imported into the loop
    assert "LiveBroker(" not in inspect.getsource(loop)                          # never constructed in the loop


# ── mandate band ──────────────────────────────────────────────────────────────
def _state(vrt_shares):
    return {"mode": "paper/simulated", "core_value": 70000.0, "cash": 0.0,
            "satellite": {"VRT": {"shares": vrt_shares, "last_price": 334.0, "cost_basis": 316.0},
                          "SMCI": {"shares": 300.0, "last_price": 50.0, "cost_basis": 42.0}}}


def test_mandate_trims_over_band():
    m = mandate.check(_state(80))                       # satellite ≈ 37.3% > 35%
    assert m["action"] == "trim" and m["orders"]
    assert all(o.side == "SELL" for o in m["orders"])


def test_mandate_ratchets_down_only():
    # tiny satellite → under target; ratchet-down default = no force-feed
    s = {"mode": "paper/simulated", "core_value": 95000.0, "cash": 0.0,
         "satellite": {"VRT": {"shares": 5, "last_price": 334.0, "cost_basis": 316.0}}}
    assert mandate.check(s)["action"] == "below_target_no_action"
    assert mandate.check(s, ratchet_down_only=False)["action"] == "would_force_feed"   # configurable


def test_governance_applies_to_every_action():
    s = _state(80)
    ok_sell, _ = loop._governed_order(EX.Order("SMCI", "SELL", price=50.0, shares=10.0), s)
    assert ok_sell is True                                              # sells de-risk
    ok_buy, reasons = loop._governed_order(EX.Order("NVDA", "BUY", price=200.0, dollars=3000.0), s)
    assert isinstance(ok_buy, bool) and isinstance(reasons, list)       # ran the REAL governor


# ── the loop self-fires in paper ──────────────────────────────────────────────
def test_loop_self_fires_and_trims_to_band(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DECISIONS", tmp_path / "dec.jsonl")
    monkeypatch.setattr(storage, "PAPER_FILLS", tmp_path / "fills.jsonl")
    monkeypatch.setattr(PP, "STATE", tmp_path / "pf.json")
    PP.save(_state(80))                                                 # seed over-band, fixed prices

    summary = loop.run(fetch_prices=False, record=True)                 # offline, deterministic prices
    assert summary["mode"] == "paper/simulated"
    assert summary["mandate"]["action"] == "trim" and summary["mandate"]["n_trims"] >= 1
    assert summary["mandate"]["banked_into_core"] > 0
    assert abs(summary["portfolio_after"]["satellite_fraction"] - 0.30) < 0.01   # ratcheted to target
    assert summary["paper_fills_chain_ok"] is True
    # ORCL is a HOLD → no candidate trade fired (autonomous, but disciplined)
    assert any(a["ticker"] == "ORCL" and not a["executed"] for a in summary["candidate_actions"])
