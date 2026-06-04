"""Olympus autonomous paper-execution loop (Phase 3) — paper/simulated only.

Self-fires the full pipeline with NO human in each paper trade:
  Oracle → Athena-Nemesis → Hecate → Tyche → Zeus → execution(PaperBroker) → record → feedback,
then enforces the 70/30 mandate (trim the satellite back to 30% past the 35% band, bank into
core). The REAL governance (concentration governor + constitution) gates every autonomous action,
so the paper test exercises the real discipline, not a bypass.

The loop only ever obtains a broker via make_broker("paper") and asserts paper mode — it never
imports or constructs LiveBroker, so a real order is physically unreachable from here.
"""
from __future__ import annotations

from olympus.core import config, storage, paper_portfolio as PP
from olympus.adapters.execution import make_broker, PaperBroker, Order, PAPER_MODE
from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter
from olympus.adapters import themis_mnemosyne_adapter as themis
from olympus.adapters import hermes_adapter
from olympus.members import tyche, zeus, mandate
from olympus.reports import forward_scorecard

from src.governance import concentration_governor as CG   # REAL blocking limits (every action)


def _govern_candidate(ticker: str):
    rating = oracle_adapter.get_rating(ticker)
    thesis = oracle_adapter.thesis_view(rating)
    cid = oracle_adapter.to_candidate(rating).candidate_id
    crit = athena_nemesis_adapter.critique(thesis, candidate_id=cid)
    exp = hecate_adapter.assess(ticker, candidate_id=cid)
    alloc = tyche.size(thesis, crit, candidate_id=cid)
    ind = themis.evidence_independence(thesis, crit)
    gov = themis.governance_check(thesis, exp, alloc)
    path = hermes_adapter.pathway(thesis, alloc)
    decision = zeus.decide(thesis, crit, exp, alloc, gov, ind, path, candidate_id=cid)
    return decision, thesis, alloc, rating


def _governed_order(order: Order, state: dict):
    """Apply REAL governance to every autonomous action before it fires."""
    if order.side == "BUY":
        gov = CG.assess_proposed_position(list(state["satellite"]), order.ticker, "MED")
        return (not gov.is_blocked, gov.block_reasons or gov.warnings)
    return (True, ["sell/trim de-risks — concentration governance satisfied"])


def _order_from_decision(decision, thesis, alloc, state) -> Order | None:
    t = decision.decision
    held = state["satellite"].get(thesis["ticker"])
    price = held["last_price"] if held else None
    if t == "BUY" and alloc.target_allocation > 0 and price:
        return Order(thesis["ticker"], "BUY", price=price,
                     dollars=alloc.target_allocation * PP.total_value(state), reason="zeus BUY")
    if t == "REDUCE" and held:
        return Order(thesis["ticker"], "SELL", price=held["last_price"],
                     shares=round(held["shares"] * 0.5, 6), reason="zeus REDUCE")
    if t == "EXIT" and held:
        return Order(thesis["ticker"], "SELL", price=held["last_price"],
                     shares=held["shares"], reason="zeus EXIT")
    return None   # HOLD / no-op / nothing held


def _update_prices(state: dict) -> None:
    try:
        import yfinance as yf
        for t, pos in state["satellite"].items():
            h = yf.Ticker(t).history(period="5d")
            if len(h):
                pos["last_price"] = round(float(h["Close"].dropna().iloc[-1]), 4)
    except Exception:
        pass   # best-effort; keep stored prices if offline


def run(*, fetch_prices: bool = True, broker_mode: str = "paper", record: bool = True) -> dict:
    broker = make_broker(broker_mode)
    assert isinstance(broker, PaperBroker) and broker.mode == PAPER_MODE, "loop is paper-only"
    state = PP.load()
    if fetch_prices:
        _update_prices(state)

    # 1. candidate pipeline → governed decisions → execute the actionable ones (paper)
    actions = []
    for rating in oracle_adapter.list_candidates():
        decision, thesis, alloc, rat = _govern_candidate(rating["ticker"])
        if record:
            storage.append_decision(decision.to_dict(), ticker=thesis["ticker"],
                                    decision=decision.decision, data_as_of=rat["as_of_date"])
        rec = {"ticker": thesis["ticker"], "decision": decision.decision, "executed": False}
        order = _order_from_decision(decision, thesis, alloc, state)
        if order:
            ok, why = _governed_order(order, state)
            if ok:
                fill = broker.execute(order); PP.apply_fill(state, fill.__dict__)
                rec.update(executed=True, fill=fill.to_dict())
            else:
                rec.update(blocked_by_governance=why)
        actions.append(rec)

    # 2. mandate rebalance — trim past the band, bank the excess into the core
    m = mandate.check(state)
    trims, banked = [], 0.0
    for order in m["orders"]:
        ok, _ = _governed_order(order, state)
        if ok:
            fill = broker.execute(order); PP.apply_fill(state, fill.__dict__)
            banked += fill.net_dollars
            trims.append(fill.to_dict())
    if banked > 0:
        state["core_value"] = round(state["core_value"] + banked, 2)
        state["cash"] = round(state["cash"] - banked, 2)

    PP.save(state)

    # 3. feedback — the scorecard is the kill-check that gates any future live step
    sc = forward_scorecard.build(fetch=fetch_prices)
    ok_chain, _ = storage.verify(storage.PAPER_FILLS) if storage.PAPER_FILLS.exists() else (True, [])
    return {
        "mode": PAPER_MODE,
        "candidate_actions": actions,
        "mandate": {"satellite_fraction_before": m["satellite_fraction"], "action": m["action"],
                    "excess_value": m["excess_value"], "n_trims": len(trims), "trims": trims,
                    "banked_into_core": round(banked, 2)},
        "portfolio_after": {"satellite_fraction": round(PP.satellite_fraction(state), 4),
                            "core_value": round(state["core_value"], 2),
                            "satellite_value": round(PP.satellite_value(state), 2)},
        "scorecard": {"n_resolved": sc["n_resolved"], "research_grade": sc["research_grade"],
                      "note": "kill-check: gates any future live step; research-grade until N sufficient"},
        "paper_fills_chain_ok": ok_chain,
    }
