"""Phaethon scorecard / holdings render — FROZEN migration of the droplet publisher's
embedded Python (build() in /root/phaethon-panel-publish.sh).

Pure functions, no I/O. The math is a verbatim migration — do NOT "improve" it:
  total value      tv = cash + Σ shares·last_price   (or 1 if that is 0)
  per-holding      weight_pct = shares·last_price / tv · 100
  cash_pct         cash / tv · 100
The ONLY additions vs the original render are governance-layer, not strategy:
  * a `cohort` tag on each holding (phaethon_a | phaethon_b)
  * a `status` field injected by the governance layer (see governance.run_governance)
"""
from __future__ import annotations

from datetime import date

from src.phaethon import ARM_COHORT


def total_value(book: dict) -> float:
    """tv = cash + Σ shares·last_price, or 1 when that is exactly 0 (frozen)."""
    return book["cash"] + sum(
        h["shares"] * h["last_price"] for h in book["holdings"].values()
    ) or 1


def holdings_view(book: dict, arm: str, tv: float | None = None) -> list[dict]:
    """Per-holding public view (ticker, bought_at, last, weight_pct) + cohort tag."""
    tv = total_value(book) if tv is None else tv
    cohort = ARM_COHORT[arm]
    return [
        {
            "ticker": t,
            "cohort": cohort,   # governance addition (holding-level cohort tag)
            "bought_at": round(h.get("cost_basis") or h.get("entry_price") or 0, 2),
            "last": round(h["last_price"], 2),
            "weight_pct": round(h["shares"] * h["last_price"] / tv * 100, 1),
        }
        for t, h in book["holdings"].items()
    ]


def render_arm(scorecard: dict, book: dict, arm: str, as_of: str | None = None,
               data_status: str | None = None, stale_days: int = 0, stale_days_effective: int = 0) -> dict:
    """Build the per-arm dashboard JSON. Frozen render of the original build() output,
    with cohort tags added on holdings. `status` is added later by the governance layer.

    arm is 'A' (disciplined) or 'B' (aggressive).
    stale_days: raw trading-day count (for truthful data-age display in banner).
    stale_days_effective: raw minus expected_lag_days (used for FRESH/STALE decision)."""
    tv = total_value(book)
    agg = (arm == "B")
    hold = holdings_view(book, arm, tv)
    return {
        "arm": "aggressive-B" if agg else "disciplined",
        "label": "Aggressive (B)" if agg else "Disciplined (A)",
        "mandate": "+10%/qtr, concentrated" if agg else "research-grade discipline",
        "cohort": ARM_COHORT[arm],
        "n_positions": scorecard.get("n_positions"),
        "holdings": hold,
        "cash_pct": round(book["cash"] / tv * 100, 1),
        "active_return_pct": scorecard.get("active_return_pct"),
        "vs_qqq_pp": scorecard.get("vs_qqq_pp"),
        "trend": scorecard.get("trend"),
        "n_marks": scorecard.get("n_marks"),
        "halted": bool(scorecard.get("halted")) if agg else None,
        "drawdown_pct": scorecard.get("drawdown_pct"),
        "kill_switch": "-25% peak-to-trough" if agg else "n/a (disciplined arm)",
        "mode": "paper/simulated", "isolated": True, "forward_only": True,
        "research_grade": True, "benchmark": "QQQ",
        # Single clearly-labeled headline benchmark per book (see docs/PHAETHON_BENCHMARK_MEMO.md):
        # Phaethon's primary is QQQ (growth/tech mandate); Olympus's is SPY TR. Dual-display
        # is allowed but the headline figure is vs the primary. Labeling only — no history rewrite.
        "benchmark_primary": "QQQ",
        "benchmark_headline": "active return vs QQQ (primary)",
        "as_of": as_of or date.today().isoformat(),
        "data_status": data_status or "FRESH",
        "stale_days": stale_days,
        "stale_days_effective": stale_days_effective,
    }
