"""Oracle adapter — wraps the EXISTING ~/labs/oracle in place (does not fork it).

Reads candidates straight from Oracle's real hash-chained forward-test ledger
(`oracle_forward_test.jsonl`). The thin slice runs against the ORCL entry already logged there,
so this exercises the genuine Oracle→Olympus seam against real data, not a fixture.
"""
from __future__ import annotations

from typing import Optional

from olympus.core import config  # noqa: F401  (wires ~/labs onto sys.path)
from olympus.core.constants import EVIDENCE_LABELS
from olympus.models.records import Candidate

from oracle import forward_test as FT   # the real Oracle module


def list_candidates() -> list[dict]:
    """Every name currently in Oracle's forward-test book (latest rating each)."""
    return [e["detail"]["rating"] for e in FT.open_ratings() if e.get("detail", {}).get("rating")]


def get_rating(ticker: str) -> Optional[dict]:
    for r in list_candidates():
        if r["ticker"].upper() == ticker.upper():
            return r
    return None


def _evidence_grade(rating: dict) -> str:
    """Derive an evidence grade from the real Oracle fields (priced-in + right-but-early)."""
    rbe = rating.get("right_but_early_risk", "MED")
    stance = (rating.get("priced_in") or {}).get("stance", "MIXED")
    if rbe == "HIGH" or stance == "MIXED":
        return "weak"
    if stance == "NON_CONSENSUS" and rbe == "LOW":
        return "strong"
    return "moderate"


def to_candidate(rating: dict) -> Candidate:
    return Candidate(
        candidate_id=f"oracle_{rating['as_of_date'].replace('-', '')}_{rating['ticker']}",
        ticker=rating["ticker"], name=rating["ticker"], asset_type="single_name",
        theme=(rating.get("overlap_with_core") or {}).get("text", "")[:60] or "unclassified",
        source="oracle:forward_test", discovery_date=rating["as_of_date"], status="actionable",
    )


def _public_context(ticker: str) -> str:
    """Public context for Oracle: fundamentals/valuation (fail loud on data error) + free news.
    NO screener / momentum / discovery signal is included (firewall §B)."""
    from oracle import priced_in as PI
    pi, val, surv, info = PI.pull(ticker, [])          # raises on a hard data failure — fail loud
    keys = ["shortName", "sector", "industry", "currentPrice", "marketCap", "trailingPE", "forwardPE",
            "priceToSalesTrailing12Months", "enterpriseToEbitda", "freeCashflow", "totalDebt",
            "debtToEquity", "grossMargins", "profitMargins", "revenueGrowth",
            "numberOfAnalystOpinions", "recommendationKey", "targetMeanPrice", "shortPercentOfFloat"]
    fund = "\n".join(f"  {k}: {info.get(k)}" for k in keys)
    news = ""
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
        heads = [(i.get("content", {}).get("title") or i.get("title")) for i in items[:6]]
        news = "\n".join(f"  - {h}" for h in heads if h) or "  (no recent free news available)"
    except Exception:
        news = "  (news feed unavailable)"
    return (f"Ticker: {ticker}\nFundamentals/valuation:\n{fund}\n"
            f"Priced-in gauge: {pi.assessment}\nRecent free news headlines:\n{news}")


def _to_judgement(ticker: str, j: dict):
    from oracle.rate import Judgement
    from oracle.schema import Pillar
    cat, inv, ov = j.get("catalyst") or {}, j.get("invalidation") or {}, j.get("overlap") or {}
    pillars = [Pillar(p.get("pillar", "pillar"), p.get("expectation", "")) for p in (j.get("pillars") or [])][:5]
    while len(pillars) < 3:                              # schema requires 3–5 pillars
        pillars.append(Pillar("(supporting consideration)", "(noted by Oracle)"))
    disc = j.get("disconfirming_evidence") or ["(Oracle stated none explicitly)"]
    return Judgement(
        ticker=ticker, raw_bias=str(j.get("bias", "HOLD")).upper(), raw_conviction=int(j.get("conviction", 50)),
        horizon=j.get("horizon", "6–12 months"), causal_thesis=j.get("causal_thesis", ""),
        catalyst_desc=cat.get("desc", ""), catalyst_when=cat.get("when", ""),
        catalyst_near_term=bool(cat.get("near_term", False)),
        right_but_early_risk=str(j.get("right_but_early_risk", "MED")).upper(),
        invalidation_line=inv.get("line", ""), invalidation_by_when=inv.get("by_when", ""),
        overlap_is_more_ai=bool(ov.get("is_more_ai", False)), overlap_diversifying=bool(ov.get("diversifying", True)),
        overlap_text=ov.get("text", ""), pillars=pillars, disconfirming_evidence=disc,
        target=j.get("target", ""), stop_exit=j.get("stop_exit", ""), peers=[])


def rate_causal(ticker: str, *, client=None, tracker=None) -> dict:
    """FULL causal Oracle on a naked ticker (Phase 6, RESEARCH-GRADE).

    Oracle reads PUBLIC context, runs its causal_sweep + thesis rubrics via an LLM, forms a real
    thesis (bias/conviction/invalidation, evidence-labelled, priced-in checked), and the rubric
    down-weights consensus + gates shorts. The rating is logged to Oracle's existing forward-test
    ledger BEFORE the outcome (chain preserved). FAILS LOUD with no API key — never fakes.
    """
    from olympus.adapters import oracle_llm as LLM
    from oracle import rate as OR, templates as T
    client = client or LLM.make_client()                # raises OracleReasoningUnavailable if no key
    ctx = _public_context(ticker)                        # fail loud on data error; no screener signal
    j = LLM.causal_thesis(ticker, ctx, client=client, tracker=tracker,
                          causal_sweep=T.load(T.CAUSAL_SWEEP), thesis_rubric=T.load(T.THESIS))
    rating = OR.build_rating(_to_judgement(ticker, j))   # applies the rubric (consensus down-weight, SELL gate)
    FT.log_rating(rating)                                 # log before outcome — preserve the chain
    return thesis_view(rating.to_dict())


def _growth_evidence_grade(durability: str, trend: str, momentum: str) -> str:
    """Growth evidence grade — durable+accelerating is STRONG; peaking/hype/decel/rolling-over is WEAK
    (so Chronos-style froth and broken momentum collapse the band, NOT consensus)."""
    durability, trend, momentum = (durability or "").lower(), (trend or "").lower(), (momentum or "").lower()
    if durability in ("peaking", "hype") or trend == "decelerating" or momentum == "rolling_over":
        return "weak"
    if durability == "durable" and trend == "accelerating" and momentum != "rolling_over":
        return "strong"
    if durability == "durable":
        return "moderate"
    return "weak"


def rate_growth(ticker: str, *, role: str = "leader", theme: str = "", enabler: str = "",
                stage: str = "mid", client=None, tracker=None) -> dict:
    """GROWTH-mode causal Oracle on a naked ticker (v2, RESEARCH-GRADE).

    Drops the v1 non-consensus gate: a consensus LEADER with durable growth can earn a BUY. The
    priced-in veto is replaced by a durability check (real & durable vs hype/peaking). Builds the
    thesis view DIRECTLY from the LLM judgement (it does NOT run the consensus-penalising
    build_rating) and does NOT write Oracle's forward-test ledger — Oracle's track stays byte-
    identical. FAILS LOUD with no API key — never fakes.
    """
    from datetime import date as _date
    from olympus.adapters import oracle_llm as LLM
    client = client or LLM.make_client()                 # raises OracleReasoningUnavailable if no key
    ctx = _public_context(ticker)                         # fail loud on data error; no screener signal
    j = LLM.growth_thesis(ticker, ctx, role=role, theme=theme, enabler=enabler, stage=stage,
                          client=client, tracker=tracker)
    durability = str(j.get("growth_durability", "")).lower()
    trend = str(j.get("growth_trend", "")).lower()
    momentum = str(j.get("momentum_state", "")).lower()
    grade = _growth_evidence_grade(durability, trend, momentum)
    bias = str(j.get("bias", "HOLD")).upper()
    if bias not in ("BUY", "HOLD", "SELL"):
        bias = "HOLD"
    inv = j.get("invalidation") or {}
    today = _date.today().isoformat()
    return {
        "ticker": ticker, "bias": bias, "conviction_pct": int(j.get("conviction", 50)),
        "horizon": j.get("horizon", "6-12 months"),
        "thesis_summary": j.get("causal_thesis", "") or f"Growth thesis for {ticker} ({role}, {theme}).",
        "evidence_grade": grade,
        # GROWTH benchmark stance — NOT the v1 priced-in veto; carries the durability read instead.
        "benchmark_alternative": {"priced_in_stance": "GROWTH", "growth_durability": durability or "unknown",
                                  "assessment": f"growth {durability or 'unknown'}/{trend or 'unknown'}, "
                                                f"momentum {momentum or 'unknown'}"},
        "invalidation": inv.get("line", "") or "growth decelerates or momentum rolls over",
        "review_by": inv.get("by_when", "") or "next quarter",
        "overlap_is_more_ai": False, "diversifying": True,
        # growth-specific extras (for the journal / scorecard / report)
        "role": role, "theme": theme, "enabler": enabler, "stage": stage,
        "growth_durability": durability or "unknown", "growth_trend": trend or "unknown",
        "momentum_state": momentum or "unknown", "quality": str(j.get("quality", "")).lower(),
        "bottleneck_angle": j.get("bottleneck_angle", ""),
        "claim_labels": {"causal_thesis": "Hypothesis", "growth_durability": "Hypothesis",
                         "conviction_pct": "Opinion", "quality": "Evidence"},
        "evidence_labels_vocab": EVIDENCE_LABELS,
        "as_of_date": today,
        "_raw": {**j, "ticker": ticker, "as_of_date": today, "growth_mode": True,
                 "role": role, "theme": theme},
    }


def rate_fresh(ticker: str) -> dict:
    """Oracle reasons FROM SCRATCH on a naked discovered ticker — from PUBLIC data only.

    No pre-existing ledger entry, and crucially NO discovery signal (the momentum screener's
    score never reaches here). Bias is derived from free valuation/fundamentals. This is a
    DEGRADED, data-only path (no human/LLM causal thesis) — explicitly RESEARCH-GRADE — so the
    honest default is a low-conviction HOLD unless the public data clearly supports otherwise.
    """
    from datetime import date as _date
    from oracle import priced_in as PI
    pi, val, surv, info = PI.pull(ticker, [])          # free data; no peers
    fcf, fpe = info.get("freeCashflow"), info.get("forwardPE")
    fragile = isinstance(fcf, (int, float)) and fcf < 0
    rich = isinstance(fpe, (int, float)) and fpe > 30
    cheap = isinstance(fpe, (int, float)) and 0 < fpe < 18
    if cheap and not fragile:
        bias, conv, grade = "BUY", 56, "data-only"
    else:
        bias, conv, grade = "HOLD", (50 if (fragile and rich) else 52), "weak"
    return {
        "ticker": ticker, "bias": bias, "conviction_pct": conv, "horizon": "6–12 months",
        "thesis_summary": (f"Auto data-only rating for discovered candidate {ticker} (RESEARCH-GRADE; "
                           f"no causal thesis). Bias from PUBLIC valuation/fundamentals only — "
                           f"fwdPE={fpe}, FCF{'<0' if fragile else '≥0'}. The discovery source's signal is NOT used."),
        "evidence_grade": grade,
        "benchmark_alternative": {"priced_in_stance": pi.stance, "assessment": pi.assessment},
        "invalidation": "fundamentals deteriorate (FCF turns negative / leverage rises) or valuation re-rates",
        "review_by": "next quarter", "overlap_is_more_ai": False, "diversifying": True,
        "claim_labels": {"valuation": "Evidence", "fundamentals": "Evidence", "conviction_pct": "Opinion"},
        "as_of_date": _date.today().isoformat(),
        "_raw": {"ticker": ticker, "as_of_date": _date.today().isoformat(), "fresh": True},
    }


def thesis_view(rating: dict) -> dict:
    """A normalised thesis view for downstream members, with every claim evidence-labelled (§4.1)."""
    pi, ov = rating.get("priced_in") or {}, rating.get("overlap_with_core") or {}
    return {
        "ticker": rating["ticker"],
        "bias": rating["bias"],
        "conviction_pct": rating["conviction_pct"],
        "horizon": rating.get("horizon", ""),
        "thesis_summary": rating.get("causal_thesis", ""),
        "evidence_grade": _evidence_grade(rating),
        "benchmark_alternative": {"priced_in_stance": pi.get("stance"),
                                  "assessment": pi.get("assessment")},
        "invalidation": (rating.get("invalidation") or {}).get("line", ""),
        "review_by": (rating.get("invalidation") or {}).get("by_when", ""),
        "overlap_is_more_ai": ov.get("is_more_ai"),
        "diversifying": ov.get("diversifying"),
        # §4.1 labelling: causal thesis = Hypothesis; priced-in gauge = Evidence; the rest as given.
        "claim_labels": {"causal_thesis": "Hypothesis", "priced_in": "Evidence",
                         "conviction_pct": "Opinion", "valuation": "Evidence"},
        "evidence_labels_vocab": EVIDENCE_LABELS,
        "_raw": rating,
    }
