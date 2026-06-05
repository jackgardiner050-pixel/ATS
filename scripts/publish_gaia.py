#!/usr/bin/env python3
"""Gaia paper-test publisher — mark the 3 diversified cores + the current arm forward, daily.

PUBLIC output (docs/data/gaia_cores_live.json): the three generic cores vs a public all-world ETF
benchmark — returns since inception + blended fees + honest framing. NO current allocation, NO
fee-saving-vs-current (those reveal the private stack).

PRIVATE output (gaia/data/gaia_private.json — GITIGNORED): the current-allocation comparison arm +
the fee saving. Never published.

% / ratios only — no dollar amounts, no personal framing in the public file. Fail-soft: a missing
price leaves that sleeve unpriced rather than aborting. RESEARCH, NOT ADVICE.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "gaia"))
import gaia  # noqa: E402

_PUBLIC = _ROOT / "docs" / "data" / "gaia_cores_live.json"
_DATA = _ROOT / "gaia" / "data"
_ANCHORS = _DATA / "anchors.json"            # gitignored — inception prices
_PRIVATE = _DATA / "gaia_private.json"       # gitignored — current arm + saving


def _spot(ticker: str):
    """Live price for an LSE-listed ETF (tries the .L suffix). Fail-soft -> None."""
    try:
        import yfinance as yf
        for sym in (f"{ticker}.L", ticker):
            h = yf.Ticker(sym).history(period="5d")
            if len(h):
                return round(float(h["Close"].dropna().iloc[-1]), 6)
        return None
    except Exception:
        return None


def _anchors(tickers: list[str]) -> dict:
    """Inception prices, established once and reused (so returns are since-inception)."""
    _DATA.mkdir(parents=True, exist_ok=True)
    store = json.loads(_ANCHORS.read_text()) if _ANCHORS.exists() else {}
    changed = False
    for t in tickers:
        if t not in store or store[t].get("price") is None:
            px = _spot(t)
            if px is not None:
                store[t] = {"price": px, "date": store.get("_inception") or date.today().isoformat()}
                changed = True
    store.setdefault("_inception", date.today().isoformat())
    if changed:
        _ANCHORS.write_text(json.dumps(store, indent=2))
    return store


def _portfolio_return(weights: dict, prices: dict, anchors: dict):
    """Weighted return-since-inception (%). Returns (return_pct, n_priced)."""
    tot, n = 0.0, 0
    for t, w in weights.items():
        px, a = prices.get(t), (anchors.get(t) or {}).get("price")
        if px and a:
            tot += w * (px / a - 1) * 100
            n += 1
    return (round(tot, 3) if n else None), n


def main() -> int:
    fa = gaia.fee_analysis()
    cfg = gaia.load_cores()
    sleeves = cfg["sleeves"]
    bench = cfg["benchmark"]
    current = gaia.load_current()

    # gather every ticker (cores + benchmark + private current arm) and anchor + mark them
    tickers = {bench["ticker"]} | {s["ticker"] for s in sleeves.values()}
    if current:
        tickers |= {h["ticker"] for h in current["holdings"]}
    anchors = _anchors(sorted(tickers))
    inception = anchors.get("_inception")
    days = max(0, (date.today() - date.fromisoformat(inception)).days) if inception else 0
    prices = {t: _spot(t) for t in sorted(tickers)}

    bench_ret, _ = _portfolio_return({bench["ticker"]: 1.0}, prices, anchors)

    # ---- PUBLIC: cores vs benchmark (no current, no saving) ----
    pub_cores = []
    for c in fa["cores"]:
        ret, n = _portfolio_return(c["etfs"], prices, anchors)
        pub_cores.append({
            "id": c["id"], "risk": c["risk"], "label": c["label"],
            "blended_ocf_pct": c["blended_ocf_pct"], "weights": c["weights"], "etfs": c["etfs"],
            "return_pct": ret, "n_priced": n,
            "vs_benchmark_pp": round(ret - bench_ret, 3) if (ret is not None and bench_ret is not None) else None,
        })
    public = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inception": inception, "days": days, "mode": "paper/simulated",
        "benchmark": {"ticker": bench["ticker"], "name": bench["name"],
                      "ocf_pct": bench["ocf_pct"], "return_pct": bench_ret},
        "cores": pub_cores, "framing": fa["framing"],
        "note": ("research candidates, not advice · in an AI bull these diversified cores will likely "
                 "lag an AI-heavy tilt on raw return — value is lower cost + lower concentration, not "
                 "more return · read as cost + risk, not which-wins"),
    }
    _PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    _PUBLIC.write_text(json.dumps(public, indent=2))

    # ---- PRIVATE: current arm + fee saving (gitignored) ----
    if current:
        cur_ret, cur_n = _portfolio_return({h["ticker"]: h["weight"] for h in current["holdings"]}, prices, anchors)
        private = {
            "generated_at_utc": public["generated_at_utc"], "inception": inception, "days": days,
            "current_allocation": {
                "label": current.get("label", "current"), "is_example": bool(current.get("is_example")),
                "blended_ocf_pct": fa["current_blended_ocf_pct"], "return_pct": cur_ret, "n_priced": cur_n,
            },
            "per_core": [{"core": c["id"], "saving_vs_current_bps": c["saving_vs_current_bps"],
                          "compounding_uplift_pct_30y": c["compounding_uplift_pct_30y"]} for c in fa["cores"]],
            "note": "PRIVATE — current-allocation comparison arm + fee saving. NEVER publish.",
        }
        _PRIVATE.write_text(json.dumps(private, indent=2))

    # console summary (the saving line is local-only)
    print(f"[gaia] inception {inception} · day {days} · benchmark {bench['ticker']} {bench_ret}%", file=sys.stderr)
    for c in pub_cores:
        print(f"  {c['id']}: {c['return_pct']}% vs bench {c['vs_benchmark_pp']}pp · OCF {c['blended_ocf_pct']}% "
              f"· {c['n_priced']}/{len(c['etfs'])} priced", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
