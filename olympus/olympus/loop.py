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


def _govern_candidate(ticker: str, satellite_tickers: list[str], *, client=None, tracker=None):
    """Govern ONE candidate from a bare ticker (firewall: no discovery signal enters).

    Oracle uses its existing rating if it has one; otherwise it runs its FULL causal reasoning
    (rate_causal — LLM, never the screener score). Tyche/governance run on the paper book.
    """
    rating = oracle_adapter.get_rating(ticker)
    if rating is not None:
        thesis = oracle_adapter.thesis_view(rating)
        cid = oracle_adapter.to_candidate(rating).candidate_id
        as_of = rating["as_of_date"]
    else:
        thesis = oracle_adapter.rate_causal(ticker, client=client, tracker=tracker)  # FULL Oracle (LLM)
        as_of = thesis.get("as_of_date") or thesis["_raw"]["as_of_date"]
        cid = f"artemis_{as_of.replace('-', '')}_{ticker}"
    crit = athena_nemesis_adapter.critique(thesis, candidate_id=cid)
    exp = hecate_adapter.assess(ticker, candidate_id=cid)
    alloc = tyche.size(thesis, crit, candidate_id=cid, satellite_tickers=satellite_tickers)
    ind = themis.evidence_independence(thesis, crit)
    gov = themis.governance_check(thesis, exp, alloc)
    path = hermes_adapter.pathway(thesis, alloc)
    decision = zeus.decide(thesis, crit, exp, alloc, gov, ind, path, candidate_id=cid)
    return decision, thesis, alloc, as_of


def _governed_order(order: Order, state: dict):
    """Apply REAL governance to every autonomous action before it fires."""
    if order.side == "BUY":
        gov = CG.assess_proposed_position(list(state["satellite"]), order.ticker, "MED")
        return (not gov.is_blocked, gov.block_reasons or gov.warnings)
    return (True, ["sell/trim de-risks — concentration governance satisfied"])


def _price(ticker: str, state: dict) -> float | None:
    held = state["satellite"].get(ticker)
    if held:
        return held["last_price"]
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d")
        return round(float(h["Close"].dropna().iloc[-1]), 4) if len(h) else None
    except Exception:
        return None


def _order_from_decision(decision, thesis, alloc, state) -> Order | None:
    t = decision.decision
    held = state["satellite"].get(thesis["ticker"])
    if t == "BUY" and alloc.target_allocation > 0:
        price = _price(thesis["ticker"], state)        # fetch for newly discovered names
        if price:
            return Order(thesis["ticker"], "BUY", price=price,
                         dollars=alloc.target_allocation * PP.total_value(state), reason="zeus BUY")
        return None
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


def _discover_tickers(discover: bool, fetch_prices: bool) -> list[tuple[str, str]]:
    """Return [(ticker, source)] — FIREWALL: only the bare ticker + source tag leave discovery."""
    if not discover:
        return [(r["ticker"], "oracle:forward_test") for r in oracle_adapter.list_candidates()]
    from olympus.discovery import artemis           # imported HERE; decision members never import it
    cands = artemis.discover() if fetch_prices else artemis.discover(price_fn=None)
    return [(c.ticker, c.source) for c in cands]     # NAKED: ticker + source only, no signal


def run(*, fetch_prices: bool = True, broker_mode: str = "paper", record: bool = True,
        discover: bool = True, standalone: bool = True, oracle_client=None) -> dict:
    if standalone:
        config.set_standalone(True)                  # disregard real funds; build our own paper book
    try:
        return _run(fetch_prices=fetch_prices, broker_mode=broker_mode, record=record,
                    discover=discover, standalone=standalone, oracle_client=oracle_client)
    finally:
        if standalone:
            config.set_standalone(False)             # reset — no global leak


def _run(*, fetch_prices, broker_mode, record, discover, standalone, oracle_client=None) -> dict:
    from olympus.adapters import oracle_llm as LLM
    broker = make_broker(broker_mode)
    assert isinstance(broker, PaperBroker) and broker.mode == PAPER_MODE, "loop is paper-only"
    state = PP.load()
    if fetch_prices:
        _update_prices(state)

    discovered = _discover_tickers(discover, fetch_prices)

    # FULL Oracle needs the LLM only for candidates without an existing rating. FAIL LOUD if those
    # exist and no key is present — never fall back to a data-only fake.
    tracker = LLM.CostTracker()
    client = oracle_client
    need_llm = any(oracle_adapter.get_rating(t) is None for t, _ in discovered)
    if need_llm and client is None:
        try:
            client = LLM.make_client()
        except LLM.OracleReasoningUnavailable as e:
            return {"mode": PAPER_MODE, "standalone_core_disregarded": standalone,
                    "discovery": {"source": "artemis" if discover else "oracle_book",
                                  "n_candidates": len(discovered),
                                  "candidates": [{"ticker": t, "source": s} for t, s in discovered]},
                    "oracle_reasoning": "UNAVAILABLE", "reason": str(e),
                    "candidate_actions": [], "decisions_made": 0, "positions_opened": 0,
                    "llm_cost": tracker.summary(),
                    "note": "Full causal Oracle requires ANTHROPIC_API_KEY. Discovery ran; reasoning did "
                            "not. No data-only fallback (that would fake theses)."}

    # 1. discover → govern each NAKED candidate. SELL-side acts now; BUYs are queued for a
    #    conviction-ranked deploy-toward-target step (so we don't over-deploy past 30%).
    from olympus.core.constants import ALLOCATION_BANDS
    actions, buy_queue = [], []
    for ticker, source in discovered:
        sat_tickers = list(state["satellite"])       # Hecate/Tyche govern the PAPER BOOK's concentration
        decision, thesis, alloc, as_of = _govern_candidate(ticker, sat_tickers, client=client, tracker=tracker)
        if record:
            storage.append_decision(decision.to_dict(), ticker=ticker,
                                    decision=decision.decision, data_as_of=as_of)
        rec = {"ticker": ticker, "source": source, "decision": decision.decision,
               "conviction": thesis.get("conviction_pct"), "executed": False}
        if decision.decision == "BUY" and alloc.target_allocation > 0:
            price = _price(ticker, state)
            if price:
                lo, hi = ALLOCATION_BANDS.get(alloc.band, (0.0, alloc.target_allocation))
                buy_queue.append({"ticker": ticker, "conviction": int(thesis.get("conviction_pct", 0)),
                                  "price": price, "band_lo": lo, "band_hi": hi, "rec": rec})
            else:
                rec["note"] = "no price — not deployed"
        elif decision.decision in ("REDUCE", "EXIT"):
            order = _order_from_decision(decision, thesis, alloc, state)
            if order:
                ok, why = _governed_order(order, state)
                if ok:
                    fill = broker.execute(order); PP.apply_fill(state, fill.__dict__)
                    rec.update(executed=True, fill=fill.to_dict())
                else:
                    rec.update(blocked_by_governance=why)
        actions.append(rec)

    # 1b. DEPLOY TOWARD TARGET — when below 30%, open conviction-ranked BUYs sized within bands,
    #     deploying toward (never forcing to) the target. Weak/few candidates → honest under-deploy.
    deploy = mandate.deploy_plan(state, [{k: v for k, v in c.items() if k != "rec"} for c in buy_queue])
    for order in deploy["orders"]:
        ok, why = _governed_order(order, state)
        if ok:
            fill = broker.execute(order); PP.apply_fill(state, fill.__dict__)
            for c in buy_queue:
                if c["ticker"] == order.ticker:
                    c["rec"].update(executed=True, fill=fill.to_dict()); break

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
        "standalone_core_disregarded": standalone,
        "oracle_reasoning": "FULL_CAUSAL_LLM",
        "discovery": {"source": "artemis" if discover else "oracle_book", "n_candidates": len(discovered),
                      "candidates": [{"ticker": t, "source": s} for t, s in discovered]},
        "decisions_made": len(actions),
        "positions_opened": sum(1 for a in actions if a.get("executed") and
                                (a.get("fill", {}) or {}).get("side") == "BUY"),
        "deploy_toward_target": {k: v for k, v in deploy.items() if k != "orders"},
        "llm_cost": tracker.summary(),
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
