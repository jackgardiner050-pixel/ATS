"""Growth scorecard (v2) — score each arm's paper book vs the growth ETF (QQQ) and vs each other.

The primary yardstick is QQQ, not the broad index: the question is "does this arm's stock-picking
beat just buying the growth basket?". Each position is marked vs QQQ SINCE ENTRY (using the QQQ
anchor stamped at the fill). RESEARCH-GRADE — a freshly opened book has ~no elapsed return; this is
interim instrumentation, never a verdict.
"""
from __future__ import annotations

from olympus.core import arm_portfolio as AP


def _ret(now, entry):
    return round((now / entry - 1) * 100, 2) if (now and entry and entry > 0) else None


def score_arm(arm_id: str, book: dict, qqq_now: float | None) -> dict:
    rows, rels = [], []
    for t, pos in book["satellite"].items():
        asset_r = _ret(pos["last_price"], pos.get("cost_basis"))
        qqq_r = _ret(qqq_now, pos.get("qqq_anchor"))
        rel = round(asset_r - qqq_r, 2) if (asset_r is not None and qqq_r is not None) else None
        if rel is not None:
            rels.append(rel)
        rows.append({"ticker": t, "entry_date": pos.get("entry_date"),
                     "asset_return_pct": asset_r, "qqq_return_pct": qqq_r, "vs_qqq_pct": rel})
    avg_rel = round(sum(rels) / len(rels), 2) if rels else None
    sat = AP.satellite_value(book)
    return {
        "arm": arm_id, "benchmark": "QQQ", "n_positions": len(book["satellite"]),
        "positions": rows, "avg_vs_qqq_pct": avg_rel,
        "beats_qqq": (avg_rel is not None and avg_rel > 0),
        "satellite_value": round(sat, 2), "satellite_fraction": round(AP.satellite_fraction(book), 4),
        "research_grade": True,
        "note": "interim — freshly opened paper book, marked vs QQQ since entry; not a verdict.",
    }


def compare(arm_results: dict) -> dict:
    """Arms vs each other — which edge-focus deployed, and (once elapsed) which beats QQQ."""
    table = []
    for arm_id, r in arm_results.items():
        sc = r.get("scorecard_vs_qqq", {})
        table.append({"arm": arm_id, "label": r.get("label"),
                      "n_buys": len(r.get("buys", [])),
                      "satellite_fraction": sc.get("satellite_fraction"),
                      "avg_vs_qqq_pct": sc.get("avg_vs_qqq_pct")})
    deployed = [t for t in table if (t["n_buys"] or 0) > 0]
    return {"per_arm": table, "n_arms_deployed": len(deployed),
            "question": "which edge-focus (A leaders / B both / C bottlenecks) beats QQQ?",
            "research_grade": True,
            "verdict": "research-grade — books just opened; arms vs QQQ resolve over the holding window."}
