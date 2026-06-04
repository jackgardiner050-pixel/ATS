"""Olympus v2 growth loop — three parallel arms, one paper book each. PAPER/SIMULATED ONLY.

Same pipeline per arm, different discovery FILTER (A leaders · B leaders+bottlenecks · C bottlenecks):
  growth-discovery → role-filter → Chronos froth-skip → growth Oracle → Athena → Hecate → Tyche →
  Themis → Zeus → deploy-toward-target → harvest-into-core + tight exit → score vs QQQ.

Execution venue is the internal PaperBroker ONLY (yfinance prices + the REAL Hermes v3 friction model
applied to every paper fill). The T212 demo adapter is dormant — never constructed, never required.
The growth path does NOT write Oracle's forward-test ledger (that track stays byte-identical).
FAILS LOUD with no ANTHROPIC_API_KEY — it never fabricates a thesis.
"""
from __future__ import annotations

from olympus.core import config, storage, arm_portfolio as AP
from olympus.adapters.execution import PaperBroker, Order
from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter
from olympus.adapters import themis_mnemosyne_adapter as themis
from olympus.adapters import hermes_adapter
from olympus.members import tyche, zeus, mandate
from olympus.discovery import growth_discovery, observational_feed
from olympus.reports import growth_scorecard
from olympus import arms

from src.governance import concentration_governor as CG   # REAL blocking limits (every action)


def _spot(ticker: str) -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d")
        return round(float(h["Close"].dropna().iloc[-1]), 4) if len(h) else None
    except Exception:
        return None


def _price(ticker: str, state: dict) -> float | None:
    held = state["satellite"].get(ticker)
    return held["last_price"] if held else _spot(ticker)


def _update_prices(state: dict, fetch: bool) -> None:
    if not fetch:
        for pos in state["satellite"].values():
            pos["high"] = max(pos.get("high", 0.0), pos["last_price"])   # keep the high-watermark current
        return
    for t, pos in state["satellite"].items():
        px = _spot(t)
        if px:
            pos["last_price"] = px
        pos["high"] = max(pos.get("high", 0.0), pos["last_price"])


def _governed_order(order: Order, state: dict):
    if order.side == "BUY":
        gov = CG.assess_proposed_position(list(state["satellite"]), order.ticker, "MED")
        return (not gov.is_blocked, gov.block_reasons or gov.warnings)
    return (True, ["sell/trim de-risks — concentration governance satisfied"])


def _govern_growth(cand, book_tickers, *, client, tracker):
    """Govern ONE growth candidate (firewall: only ticker+role+theme context, no price signal)."""
    thesis = oracle_adapter.rate_growth(cand.ticker, role=cand.role, theme=cand.theme,
                                        enabler=cand.enabler, stage=cand.stage,
                                        client=client, tracker=tracker)
    cid = f"growth_{thesis['as_of_date'].replace('-', '')}_{cand.ticker}_{cand.role}"
    crit = athena_nemesis_adapter.critique(thesis, candidate_id=cid)
    exp = hecate_adapter.assess(cand.ticker, candidate_id=cid)          # concentration/overlap vs core
    alloc = tyche.size(thesis, crit, candidate_id=cid, satellite_tickers=book_tickers)
    ind = themis.evidence_independence(thesis, crit)
    gov = themis.governance_check(thesis, exp, alloc)
    path = hermes_adapter.pathway(thesis, alloc)
    decision = zeus.decide(thesis, crit, exp, alloc, gov, ind, path, candidate_id=cid)
    return decision, thesis, alloc, cid


def run_arm(arm_id: str, candidates, *, client, tracker, fetch_prices: bool = True,
            record: bool = True, notional: float = 10000.0, qqq_now: float | None = None,
            spy_now: float | None = None) -> dict:
    from olympus.adapters import oracle_llm as LLM
    from olympus.core.constants import ALLOCATION_BANDS

    broker = PaperBroker()                                   # SOLE venue — Hermes friction on every fill
    book = AP.load(arm_id, notional)
    _update_prices(book, fetch_prices)
    if qqq_now is None and fetch_prices:
        qqq_now = _spot(arms.BENCHMARK_ETF)
    if spy_now is None and fetch_prices:
        spy_now = _spot("SPY")                               # secondary benchmark anchor (S&P 500 proxy)

    cands = growth_discovery.for_arm(candidates, arms.allowed_roles(arm_id))

    # 1. govern each candidate → growth thesis → decision
    theses, buy_queue, actions = {}, [], []
    for cand in cands:
        try:
            decision, thesis, alloc, cid = _govern_growth(cand, list(book["satellite"]),
                                                          client=client, tracker=tracker)
        except LLM.OracleReasoningUnavailable as e:
            actions.append({"ticker": cand.ticker, "role": cand.role, "theme": cand.theme,
                            "decision": "SKIPPED", "reason": f"oracle reasoning failed: {str(e)[:70]}"})
            continue
        theses[cand.ticker] = thesis
        if record:
            storage.append_decision(decision.to_dict(), ticker=cand.ticker,
                                    decision=decision.decision, data_as_of=thesis["as_of_date"])
        rec = {"ticker": cand.ticker, "role": cand.role, "theme": cand.theme,
               "decision": decision.decision, "conviction": thesis.get("conviction_pct"),
               "durability": thesis.get("growth_durability"), "trend": thesis.get("growth_trend"),
               "evidence_grade": thesis.get("evidence_grade"), "executed": False}
        if decision.decision == "BUY" and alloc.target_allocation > 0:
            price = _price(cand.ticker, book)
            if price:
                lo, hi = ALLOCATION_BANDS.get(alloc.band, (0.0, alloc.target_allocation))
                buy_queue.append({"ticker": cand.ticker, "conviction": int(thesis.get("conviction_pct", 0)),
                                  "price": price, "band_lo": lo, "band_hi": hi, "rec": rec})
            else:
                rec["note"] = "no price — not deployed"
        actions.append(rec)

    # 2. DISCIPLINE first — tight exit / thesis-break, then harvest winners into the core (manage the
    #    existing book before adding). Proceeds bank into the safe core.
    banked = 0.0
    exit_res = mandate.exit_plan(book, theses)
    harvest_res = mandate.harvest_plan(book)
    for order in exit_res["orders"] + harvest_res["orders"]:
        fill = broker.execute(order)
        AP.apply_fill(book, fill.__dict__)
        banked += max(0.0, fill.net_dollars)

    # 3. deploy-toward-target into THIS arm's book (conviction-ranked, sized within bands)
    deploy = mandate.deploy_plan(book, [{k: v for k, v in c.items() if k != "rec"} for c in buy_queue])
    deployed_cost = 0.0
    for order in deploy["orders"]:
        ok, why = _governed_order(order, book)
        if not ok:
            for c in buy_queue:
                if c["ticker"] == order.ticker:
                    c["rec"]["blocked_by_governance"] = why
            continue
        fill = broker.execute(order)
        AP.apply_fill(book, fill.__dict__)
        deployed_cost += fill.cost_dollars
        pos = book["satellite"].get(order.ticker)
        if pos is not None:                                  # stamp QQQ + SPY anchors + high-watermark at entry
            pos.setdefault("qqq_anchor", qqq_now)
            pos.setdefault("spy_anchor", spy_now)
            pos.setdefault("entry_date", fill.date)
            pos["high"] = max(pos.get("high", 0.0), pos["last_price"])
        for c in buy_queue:
            if c["ticker"] == order.ticker:
                c["rec"].update(executed=True, fill=fill.to_dict())

    if banked > 0:
        book["core_value"] = round(book["core_value"] + banked, 2)
    AP.save(arm_id, book)

    sc = growth_scorecard.score_arm(arm_id, book, qqq_now)
    return {
        "arm": arm_id, "label": arms.label(arm_id), "allowed_roles": arms.allowed_roles(arm_id),
        "n_candidates": len(cands),
        "candidates": [{"ticker": c.ticker, "role": c.role, "theme": c.theme,
                        "obviousness": c.obviousness} for c in cands],
        "theses": [{"ticker": a["ticker"], "role": a["role"], "theme": a["theme"],
                    "decision": a["decision"], "conviction": a.get("conviction"),
                    "durability": a.get("durability"), "trend": a.get("trend")} for a in actions],
        "decisions": actions,
        "buys": [c["rec"]["ticker"] for c in buy_queue if c["rec"].get("executed")],
        "deploy": {k: v for k, v in deploy.items() if k != "orders"},
        "exit": exit_res, "harvest": harvest_res, "banked_into_core": round(banked, 2),
        "deployed_friction_cost": round(deployed_cost, 4),
        "book_after": {"satellite_fraction": round(AP.satellite_fraction(book), 4),
                       "core_value": round(book["core_value"], 2),
                       "satellite_value": round(AP.satellite_value(book), 2),
                       "positions": list(book["satellite"])},
        "scorecard_vs_qqq": sc,
    }


def run(*, fetch_prices: bool = True, record: bool = True, notional: float = 10000.0,
        client=None, enrich: bool = True) -> dict:
    """Run all three arms off one shared discovery pass + one shared LLM client/cost tracker."""
    from olympus.adapters import oracle_llm as LLM
    config.set_standalone(True)                              # paper books are self-contained (no real funds)
    try:
        observational_feed.refresh(record=record)            # log the thematic read for later grading
        candidates = growth_discovery.discover(enrich=enrich)
        awareness = growth_discovery.awareness()             # catalyst beneficiaries — AWARENESS only

        tracker = LLM.CostTracker()
        if client is None:
            try:
                client = LLM.make_client()                   # FAIL LOUD — no data-only fake
            except LLM.OracleReasoningUnavailable as e:
                return {"mode": "paper/simulated", "oracle_reasoning": "UNAVAILABLE", "reason": str(e),
                        "benchmark_etf": arms.BENCHMARK_ETF,
                        "discovery": {"n_value_chain": len(candidates),
                                      "awareness_beneficiaries": [c.ticker for c in awareness]},
                        "arms": {}, "llm_cost": tracker.summary(),
                        "note": "Growth Oracle requires ANTHROPIC_API_KEY. Discovery ran; reasoning did "
                                "not. No data-only fallback (that would fake theses)."}

        qqq_now = _spot(arms.BENCHMARK_ETF) if fetch_prices else None
        spy_now = _spot("SPY") if fetch_prices else None
        arm_results = {}
        for arm_id in arms.ARM_IDS:
            arm_results[arm_id] = run_arm(arm_id, candidates, client=client, tracker=tracker,
                                          fetch_prices=fetch_prices, record=record,
                                          notional=notional, qqq_now=qqq_now, spy_now=spy_now)

        return {
            "mode": "paper/simulated", "execution_venue": "internal_sim (PaperBroker + Hermes friction)",
            "oracle_reasoning": "FULL_CAUSAL_LLM_GROWTH", "benchmark_etf": arms.BENCHMARK_ETF,
            "qqq_spot": qqq_now, "standalone_core_disregarded": True,
            "discovery": {"n_value_chain": len(candidates),
                          "awareness_catalyst_beneficiaries": [
                              {"ticker": c.ticker, "catalyst": c.catalyst} for c in awareness]},
            "arms": arm_results,
            "arm_comparison": growth_scorecard.compare(arm_results),
            "llm_cost": tracker.summary(),
            "oracle_ledger": "untouched by the growth path (byte-identical)",
        }
    finally:
        config.set_standalone(False)
