"""Realized slippage — per fill, decision_price (screener close) → card_price (at send) →
fill_price (executed), reported in bps against the modeled paper_cost_bps.

Sign convention: ADVERSE slippage is positive. A BUY filled above the decision price, or a
SELL filled below it, is positive (cost); the opposite is negative (price improvement).
"""
from __future__ import annotations


def slippage_bps(decision_price, fill_price, side: str):
    """Adverse slippage in bps of fill vs decision price. None if no decision price."""
    if not decision_price or fill_price is None:
        return None
    raw = (float(fill_price) - float(decision_price)) / float(decision_price)
    signed = raw if side == "BUY" else -raw            # BUY-up / SELL-down = adverse
    return round(signed * 1e4, 2)


def slippage_row(fill: dict, modeled_bps: float) -> dict:
    dp, cp, fp = fill.get("decision_price"), fill.get("card_price"), fill.get("price")
    bps = slippage_bps(dp, fp, fill.get("side"))
    return {
        "card_id": fill.get("card_id"), "ticker": fill.get("ticker"), "side": fill.get("side"),
        "decision_price": dp, "card_price": cp, "fill_price": fp,
        "slippage_bps": bps, "modeled_bps": modeled_bps,
        "excess_vs_modeled_bps": (round(bps - modeled_bps, 2) if bps is not None else None),
    }


def slippage_table(fills: list[dict], modeled_bps: float) -> list[dict]:
    return [slippage_row(f, modeled_bps) for f in fills]


def slippage_summary(fills: list[dict], modeled_bps: float) -> dict:
    rows = [r for r in slippage_table(fills, modeled_bps) if r["slippage_bps"] is not None]
    if not rows:
        return {"n": 0, "mean_bps": None, "mean_excess_bps": None, "modeled_bps": modeled_bps}
    n = len(rows)
    return {
        "n": n,
        "mean_bps": round(sum(r["slippage_bps"] for r in rows) / n, 2),
        "mean_excess_bps": round(sum(r["excess_vs_modeled_bps"] for r in rows) / n, 2),
        "modeled_bps": modeled_bps,
    }
