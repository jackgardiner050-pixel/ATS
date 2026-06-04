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
    interim = []
    cur = {}
    if fetch:
        for t in {"ACWI", "NVDA"} | {r["detail"]["rating"]["ticker"] for r in ratings}:
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
        "research_grade": n_res < vp["min_resolved_calls_for_verdict"],
    }


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
        "## Interim (unresolved) — benchmark drift since entry (not a verdict)",
        *([f"- {i['ticker']} ({i['bias']}, conv {i['conviction']}, {i['elapsed_months']}mo of {i['horizon']}): "
          f"ACWI {i['acwi_since_entry_pct']}% · NVDA {i['nvda_since_entry_pct']}%"
          for i in sc["interim_unresolved"]] or ["- none"]),
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
