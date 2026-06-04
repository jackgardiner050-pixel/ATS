"""Forward scorecard (§10 / §12.3) — wired to Oracle's EXISTING forward-test harness.

Does NOT reinvent the harness: it imports `oracle.forward_test` and reuses its pre-registered
VERDICT_POLICY (verdict @30 resolved, interim @15), its grading benchmarks (global index ACWI,
naive obvious-AI name NVDA), and the per-rating anchors that harness already stamps. It reads
BOTH the real Oracle forward-test ledger and the Olympus decision ledger, and reports:
total decisions, BUY/REDUCE/EXIT counts, hit rate, return, benchmark-relative (ACWI) and
ETF-alternative (NVDA) relative, calibration by confidence band, and major winners
(skill/luck/beta). It stays RESEARCH-GRADE until enough decisions resolve.
"""
from __future__ import annotations

import re
from datetime import date

from olympus.core import config, storage
from olympus.core.constants import ADVISORY_FOOTER

from oracle import forward_test as FT   # the real harness (no reinvention)


def _months(horizon: str) -> int:
    nums = [int(n) for n in re.findall(r"\d+", horizon or "")]
    return max(nums) if nums else 12            # "fully elapsed" = the upper bound of the horizon


def _elapsed_months(d0: str, d1: date) -> float:
    y0, m0, _ = (int(x) for x in d0.split("-"))
    return (d1.year - y0) * 12 + (d1.month - m0) + d1.day / 30.0


def _current(ticker: str):
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d")
        return round(float(h["Close"].dropna().iloc[-1]), 4) if len(h) else None
    except Exception:
        return None


def build(*, fetch: bool = True) -> dict:
    ratings = [e for e in FT.entries() if e.get("kind") != "GENESIS" and e.get("detail", {}).get("rating")]
    decisions = [e for e in storage.decisions() if e.get("kind") != "GENESIS"]
    outcomes = [e["detail"]["outcome"] for e in storage.outcomes()
                if e.get("detail", {}).get("outcome")]
    today = date.today()

    # decision-direction counts (from the governed Olympus decisions)
    counts = {"BUY": 0, "HOLD": 0, "REDUCE": 0, "EXIT": 0}
    for d in decisions:
        dec = (d.get("detail", {}).get("zeus_decision", {}) or {}).get("decision")
        if dec in counts:
            counts[dec] += 1

    # interim benchmark/ETF marks from Oracle's stored anchors (real wiring)
    # WALLED-OFF screener track read as a benchmark ARM only (ledger data, not the module).
    screener = [e["detail"]["pick"] for e in storage.screener_picks()
                if e.get("detail", {}).get("pick")]

    interim = []
    cur = {}
    if fetch:
        tickers = {"ACWI", "NVDA"} | {r["detail"]["rating"]["ticker"] for r in ratings}
        tickers |= {p["ticker"] for p in screener}
        for t in tickers:
            cur[t] = _current(t)
    for r in ratings:
        rat = r["detail"]["rating"]
        anch = r["detail"].get("grading_anchors_at_entry", {}) or {}
        elapsed = _elapsed_months(rat["as_of_date"], today)
        resolved = elapsed >= _months(rat.get("horizon", ""))
        def rel(tkr, entry):
            c = cur.get(tkr)
            return round((c / entry - 1) * 100, 2) if (c and entry) else None
        interim.append({
            "ticker": rat["ticker"], "bias": rat["bias"], "conviction": rat["conviction_pct"],
            "as_of": rat["as_of_date"], "horizon": rat.get("horizon"),
            "resolved": resolved, "elapsed_months": round(elapsed, 1),
            "acwi_since_entry_pct": rel("ACWI", anch.get("ACWI")),
            "nvda_since_entry_pct": rel("NVDA", anch.get("NVDA")),
        })

    # resolved metrics come ONLY from the outcomes ledger (graded, recorded before claimed)
    resolved_out = [o for o in outcomes if o.get("skill_luck_beta_classification") != "unresolved"]
    n_res = len(resolved_out)
    wins = [o for o in resolved_out if (o.get("relative_return") or 0) > 0]
    hit_rate = round(100 * len(wins) / n_res, 1) if n_res else None
    avg_ret = round(sum(o.get("asset_return") or 0 for o in resolved_out) / n_res, 2) if n_res else None
    avg_rel = round(sum(o.get("relative_return") or 0 for o in resolved_out) / n_res, 2) if n_res else None
    avg_etf = round(sum((o.get("asset_return") or 0) - (o.get("etf_alternative_return") or 0)
                        for o in resolved_out) / n_res, 2) if n_res else None
    winners = [o for o in resolved_out if o.get("skill_luck_beta_classification") in ("skill", "luck", "beta", "factor")
               and (o.get("asset_return") or 0) > 20]

    vp = FT.VERDICT_POLICY
    return {
        "policy": vp, "n_decisions": len(decisions), "n_oracle_ratings": len(ratings),
        "decision_counts": counts, "n_resolved": n_res,
        "interim_unresolved": [i for i in interim if not i["resolved"]],
        "metrics": {"hit_rate_pct": hit_rate, "avg_asset_return_pct": avg_ret,
                    "avg_benchmark_relative_pct_ACWI": avg_rel, "avg_etf_relative_pct_NVDA": avg_etf},
        "calibration_by_band": _calibration(resolved_out),
        "major_winners": winners,
        "naive_screener_arm": _screener_arm(screener, cur, fetch),
        "research_grade": n_res < vp["min_resolved_calls_for_verdict"],
    }


def _screener_arm(screener: list, cur: dict, fetch: bool) -> dict:
    """Benchmark arm (c): does the naive screener beat passive (ACWI), net of cost? And it is the
    third yardstick Olympus's own decisions are measured against once they resolve."""
    rows, rels = [], []
    for p in screener:
        c = cur.get(p["ticker"]) if fetch else None
        entry, acwi0 = p.get("price"), p.get("acwi_anchor")
        acwi_now = cur.get("ACWI") if fetch else None
        net = ((c / entry - 1) * 100 - p.get("net_cost_haircut_pct", 0)) if (c and entry) else None
        acwi_r = ((acwi_now / acwi0 - 1) * 100) if (acwi_now and acwi0) else None
        rel = round(net - acwi_r, 2) if (net is not None and acwi_r is not None) else None
        if rel is not None:
            rels.append(rel)
        rows.append({"ticker": p["ticker"], "entry_date": p.get("entry_date"),
                     "net_return_pct": round(net, 2) if net is not None else None,
                     "acwi_return_pct": round(acwi_r, 2) if acwi_r is not None else None,
                     "screener_vs_acwi_pct": rel})
    avg_rel = round(sum(rels) / len(rels), 2) if rels else None
    return {"n_picks": len(screener), "picks": rows,
            "avg_screener_vs_ACWI_pct_net": avg_rel,
            "screener_beats_passive": (avg_rel is not None and avg_rel > 0),
            "olympus_vs_screener": "needs resolved Olympus decisions (research-grade until then)"}


def _calibration(resolved_out) -> dict:
    bands = {"50-60": [], "60-70": [], "70-80": [], "80+": []}
    for o in resolved_out:
        c = o.get("conviction", 0)
        key = "80+" if c >= 80 else "70-80" if c >= 70 else "60-70" if c >= 60 else "50-60"
        bands[key].append(1 if (o.get("relative_return") or 0) > 0 else 0)
    return {k: (round(100 * sum(v) / len(v), 0) if v else None) for k, v in bands.items()}


def render(sc: dict) -> str:
    vp = sc["policy"]
    m = sc["metrics"]
    banner = (f"**RESEARCH-GRADE — {sc['n_resolved']}/{vp['min_resolved_calls_for_verdict']} resolved "
              f"decisions. No verdict before {vp['min_resolved_calls_for_verdict']} "
              f"(interim read at {vp['interim_read_at']}). '{vp['expect']}'**"
              if sc["research_grade"] else "**Verdict-eligible: enough resolved decisions.**")
    L = [
        "# Olympus Forward Scorecard",
        f"*wired to Oracle's forward-test harness · graded vs ACWI (index) + NVDA (naive AI) + calibration*",
        "", banner, "",
        f"- Governed decisions: **{sc['n_decisions']}** · Oracle ratings: {sc['n_oracle_ratings']}",
        f"- Decision mix: {sc['decision_counts']}",
        f"- Resolved: **{sc['n_resolved']}**",
        "",
        "## Resolved metrics (research-grade until N sufficient)",
        f"- Hit rate: {m['hit_rate_pct']}%" if m['hit_rate_pct'] is not None else "- Hit rate: — (no resolved decisions)",
        f"- Avg asset return: {m['avg_asset_return_pct']}%" if m['avg_asset_return_pct'] is not None else "- Avg asset return: —",
        f"- Avg vs ACWI (benchmark): {m['avg_benchmark_relative_pct_ACWI']}%" if m['avg_benchmark_relative_pct_ACWI'] is not None else "- Avg vs ACWI: —",
        f"- Avg vs NVDA (ETF/naive): {m['avg_etf_relative_pct_NVDA']}%" if m['avg_etf_relative_pct_NVDA'] is not None else "- Avg vs NVDA: —",
        f"- Calibration by confidence band: {sc['calibration_by_band']}",
        f"- Major winners (skill/luck/beta): {len(sc['major_winners'])}",
        "",
        "## Benchmark arm (c) — naive screener (walled off from decisions)",
        f"- Screener picks: {sc['naive_screener_arm']['n_picks']}",
        f"- Avg screener vs ACWI (net of cost): {sc['naive_screener_arm']['avg_screener_vs_ACWI_pct_net']}% "
        f"→ beats passive: {sc['naive_screener_arm']['screener_beats_passive']}",
        f"- Olympus vs screener: {sc['naive_screener_arm']['olympus_vs_screener']}",
        "",
        "## Interim (unresolved) — benchmark drift since entry (not a verdict)",
        *([f"- {i['ticker']} ({i['bias']}, conv {i['conviction']}, {i['elapsed_months']}mo of {i['horizon']}): "
          f"ACWI {i['acwi_since_entry_pct']}% · NVDA {i['nvda_since_entry_pct']}%"
          for i in sc["interim_unresolved"]] or ["- none"]),
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
