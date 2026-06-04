#!/usr/bin/env python3
"""Publish the Olympus v2 growth-arm (A/B/C) live performance feed for the dashboard.

Reads each arm's PAPER ledger (arm_{A,B,C}_portfolio.json — pulled from the droplet where the
growth loop runs), marks the held positions at live prices, and computes each arm's active-book
return since inception vs QQQ (primary) and SPY (secondary). Writes docs/data/growth_arms_live.json.

PAPER/ADVISORY ONLY. Ratios/% only — NO dollar amounts, no real-account data. Fail-soft: a missing
price or ledger leaves that field null rather than aborting. RESEARCH-GRADE: a freshly-opened book
has ~no elapsed return and 0/30 resolved — this is instrumentation, never a track record.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ARM_DIR = _ROOT / "olympus" / "olympus" / "data"
_OUT = _ROOT / "docs" / "data" / "growth_arms_live.json"
_SCORECARD_TARGET = 30

_LABELS = {"A": "obvious theme leaders only",
           "B": "leaders + second-order bottlenecks",
           "C": "second-order bottleneck names only"}


def _spot(ticker: str):
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="5d")
        return round(float(h["Close"].dropna().iloc[-1]), 4) if len(h) else None
    except Exception:
        return None


def _close_on(ticker: str, day: str):
    """Close on/just-before an inception date — the benchmark anchor when the ledger lacks one."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(start=day, period="7d")
        return round(float(h["Close"].dropna().iloc[0]), 4) if len(h) else None
    except Exception:
        return None


def _days(d0: str) -> int:
    try:
        return max(0, (date.today() - date.fromisoformat(d0)).days)
    except Exception:
        return 0


def _arm_metrics(arm_id: str, qqq_now, spy_now) -> dict:
    p = _ARM_DIR / f"arm_{arm_id}_portfolio.json"
    if not p.exists():
        return {"arm": arm_id, "label": _LABELS[arm_id], "available": False,
                "note": "no paper ledger yet — arm not run"}
    book = json.loads(p.read_text())
    sat = book.get("satellite", {})
    tickers = sorted(sat)
    inception = min((pos.get("entry_date") or "9999") for pos in sat.values()) if sat else None
    qqq_anchor = next((pos.get("qqq_anchor") for pos in sat.values() if pos.get("qqq_anchor")), None)
    spy_anchor = next((pos.get("spy_anchor") for pos in sat.values() if pos.get("spy_anchor")), None)
    if spy_anchor is None and inception:
        spy_anchor = _close_on("SPY", inception)             # ledger predates spy_anchor → fetch it

    # cost-weighted active-book (satellite) return, marked live
    cost = sum(pos["shares"] * pos["cost_basis"] for pos in sat.values()) if sat else 0.0
    val = 0.0
    pos_rows, priced = [], 0
    for t, pos in sat.items():
        live = _spot(t) or pos.get("last_price")
        if live:
            priced += 1
        val += pos["shares"] * (live or pos["cost_basis"])
        r = round((live / pos["cost_basis"] - 1) * 100, 2) if (live and pos.get("cost_basis")) else None
        pos_rows.append({"ticker": t, "return_pct": r})
    active_ret = round((val / cost - 1) * 100, 2) if cost > 0 else None

    def bench_ret(now, anchor):
        return round((now / anchor - 1) * 100, 2) if (now and anchor) else None
    qqq_r = bench_ret(qqq_now, qqq_anchor)
    spy_r = bench_ret(spy_now, spy_anchor)
    return {
        "arm": arm_id, "label": _LABELS[arm_id], "available": True,
        "n_positions": len(sat), "tickers": tickers, "inception": inception, "days_held": _days(inception or ""),
        "active_return_pct": active_ret,
        "qqq_return_pct": qqq_r, "spy_return_pct": spy_r,
        "vs_qqq_pp": round(active_ret - qqq_r, 2) if (active_ret is not None and qqq_r is not None) else None,
        "vs_spy_pp": round(active_ret - spy_r, 2) if (active_ret is not None and spy_r is not None) else None,
        "n_priced": priced, "positions": pos_rows,
        "n_resolved": 0, "scorecard_target": _SCORECARD_TARGET,
    }


def main() -> int:
    qqq_now, spy_now = _spot("QQQ"), _spot("SPY")
    out = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_primary": "QQQ", "benchmark_secondary": "SPY",
        "qqq_spot": qqq_now, "spy_spot": spy_now,
        "scorecard_target": _SCORECARD_TARGET,
        "mode": "paper/simulated",
        "honest_note": ("research-grade · scorecard 0/%d resolved · not statistically meaningful. The three "
                        "arms are AI-infrastructure-concentrated and highly correlated — not independent "
                        "strategies. QQQ is the real test; beating the S&P with an AI-infra book in an AI "
                        "bull is expected, not edge." % _SCORECARD_TARGET),
        "arms": {a: _arm_metrics(a, qqq_now, spy_now) for a in ("A", "B", "C")},
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, indent=2))
    print(f"[growth-arms] wrote {_OUT} · QQQ={qqq_now} SPY={spy_now}", file=sys.stderr)
    for a, m in out["arms"].items():
        if m.get("available"):
            print(f"  arm {a}: active {m['active_return_pct']}% vs QQQ {m['vs_qqq_pp']}pp "
                  f"vs SPY {m['vs_spy_pp']}pp · {m['n_positions']} pos · {m['days_held']}d", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
