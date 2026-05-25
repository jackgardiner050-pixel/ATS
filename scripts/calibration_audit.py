"""Phase 1 calibration audit.

For each of 5 audit targets:
  - Read latest agent recommendation.json + model outputs
  - Pull current market data via yfinance
  - Compute peer medians from raw market data
  - Print side-by-side comparison sheet

Run from agent/ project root:
    python3 scripts/calibration_audit.py

Output: prints markdown table to stdout, saves to runs/_audit/calibration_audit_{ts}.md
"""
from __future__ import annotations
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# Audit targets and their peer groups (from peer_groups.yaml)
TARGETS = {
    "AGX":  ["PWR", "MTZ", "PRIM", "EME", "FIX", "STRL", "IESC", "DY"],
    "ROK":  ["ETN", "AME", "HUBB", "EMR"],
    "AMAT": ["LRCX", "KLAC", "TER", "ENTG"],
    "LLY":  ["MRK", "PFE", "ABBV", "BMY", "JNJ"],
    "HON":  ["GE", "EMR", "ITW", "PH", "DOV"],
}

ROOT = Path(__file__).parent.parent  # agent/
RUNS_DIR = ROOT / "runs"


def latest_recommendation(ticker: str) -> dict | None:
    """Find the most recent recommendation.json for a ticker."""
    tdir = RUNS_DIR / ticker.upper()
    if not tdir.exists():
        return None
    runs = sorted([d for d in tdir.iterdir() if d.is_dir()], reverse=True)
    for run in runs:
        rec = run / "recommendation.json"
        if rec.exists():
            with open(rec) as f:
                return json.load(f)
    return None


def market_metrics(ticker: str) -> dict:
    """Pull current market data via yfinance."""
    try:
        info = yf.Ticker(ticker).info or {}
        mc = info.get("marketCap") or 0
        debt = info.get("totalDebt") or 0
        cash = info.get("totalCash") or 0
        ebitda = info.get("ebitda") or 0
        ev = mc + debt - cash if mc else None
        ev_ebitda = (ev / ebitda) if ebitda and ebitda > 0 and ev else None
        fwd_pe = info.get("forwardPE")
        trail_pe = info.get("trailingPE")
        pe = fwd_pe if (fwd_pe and 0 < fwd_pe < 200) else (trail_pe if (trail_pe and 0 < trail_pe < 200) else None)
        return {
            "ticker": ticker,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "shares_M": (info.get("sharesOutstanding") or 0) / 1e6,
            "ev_ebitda": ev_ebitda,
            "fwd_pe": fwd_pe,
            "trail_pe": trail_pe,
            "pe_used": pe,
            "analyst_pt_mean": info.get("targetMeanPrice"),
            "analyst_pt_high": info.get("targetHighPrice"),
            "analyst_pt_low": info.get("targetLowPrice"),
            "n_analysts": info.get("numberOfAnalystOpinions"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def fmt(v, prec=1, prefix="", suffix=""):
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    if isinstance(v, (int, float)):
        return f"{prefix}{v:.{prec}f}{suffix}"
    return str(v)


def pct_diff(a, b):
    if a is None or b is None or b == 0:
        return "—"
    return f"{(a - b) / b * 100:+.0f}%"


def audit_one(target: str, peers: list[str]) -> str:
    """Build comparison sheet for one target."""
    out = []
    out.append(f"\n## {target}\n")

    rec = latest_recommendation(target)
    if rec is None:
        out.append(f"⚠️  No recommendation.json found for {target} in {RUNS_DIR}/{target}/")
        return "\n".join(out)

    fixed = rec.get("fixed_numbers", {})
    model_out = rec.get("model_outputs", {})
    assumptions = rec.get("assumptions", {})
    peer_mult_agent = fixed.get("peer_multiples", {}) or {}

    # Agent's view
    agent_price = rec.get("current_price")
    agent_pt = rec.get("price_target_12m")
    agent_rating = rec.get("rating")
    agent_conf = rec.get("confidence", "?")
    agent_med_ev_ebitda = peer_mult_agent.get("median_ev_ebitda")
    agent_p75_ev_ebitda = peer_mult_agent.get("p75_ev_ebitda")
    agent_med_pe = peer_mult_agent.get("median_pe")
    agent_dcf_gordon = fixed.get("dcf_price_gordon") or fixed.get("dcf_gordon_price")
    agent_dcf_exit = fixed.get("dcf_price_exit") or fixed.get("dcf_exit_price")
    agent_comps = fixed.get("comps_price_median_ev_ebitda") or fixed.get("comps_median_price")
    # wacc / terminal_growth / exit_multiple now live in assumptions block
    agent_wacc = assumptions.get("wacc") or fixed.get("wacc")
    agent_terminal_growth = assumptions.get("terminal_growth") or fixed.get("terminal_growth")
    agent_exit_multiple = assumptions.get("exit_multiple_used") or fixed.get("exit_multiple")
    agent_fy1_ebitda = model_out.get("fy1_ebitda")

    # Market data
    tgt_mkt = market_metrics(target)
    peer_data = [market_metrics(p) for p in peers]

    # Compute market peer medians
    p_ev = [p["ev_ebitda"] for p in peer_data if p.get("ev_ebitda") and 0 < p["ev_ebitda"] < 100]
    p_pe = [p["pe_used"] for p in peer_data if p.get("pe_used")]
    mkt_med_ev_ebitda = statistics.median(p_ev) if p_ev else None
    mkt_p75_ev_ebitda = statistics.quantiles(p_ev, n=4)[2] if len(p_ev) >= 4 else None
    mkt_med_pe = statistics.median(p_pe) if p_pe else None

    out.append(f"**Agent rating: {agent_rating} | Confidence: {agent_conf} | Agent PT: ${fmt(agent_pt, 0)} vs current ${fmt(agent_price, 2)} ({fmt(rec.get('expected_return', 0)*100, 1, suffix='%') if rec.get('expected_return') else '—'})**\n")

    out.append("| Metric | Agent | Market (yfinance) | Delta | Verdict |")
    out.append("|---|---|---|---|---|")
    out.append(f"| Current price | ${fmt(agent_price, 2)} | ${fmt(tgt_mkt.get('price'), 2)} | {pct_diff(agent_price, tgt_mkt.get('price'))} | {'OK' if agent_price and tgt_mkt.get('price') and abs(agent_price - tgt_mkt['price']) < 1 else 'CHECK'} |")
    out.append(f"| Shares (M) | — | {fmt(tgt_mkt.get('shares_M'), 1)} | | |")
    out.append(f"| Peer median EV/EBITDA | {fmt(agent_med_ev_ebitda, 1, suffix='x')} | {fmt(mkt_med_ev_ebitda, 1, suffix='x')} | {pct_diff(agent_med_ev_ebitda, mkt_med_ev_ebitda)} | |")
    out.append(f"| Peer 75th EV/EBITDA | {fmt(agent_p75_ev_ebitda, 1, suffix='x')} | {fmt(mkt_p75_ev_ebitda, 1, suffix='x')} | {pct_diff(agent_p75_ev_ebitda, mkt_p75_ev_ebitda)} | |")
    out.append(f"| Peer median P/E | {fmt(agent_med_pe, 1, suffix='x')} | {fmt(mkt_med_pe, 1, suffix='x')} | {pct_diff(agent_med_pe, mkt_med_pe)} | |")
    out.append(f"| WACC used | {fmt((agent_wacc or 0)*100, 1, suffix='%')} | (n/a) | | |")
    out.append(f"| Terminal growth | {fmt((agent_terminal_growth or 0)*100, 1, suffix='%')} | (n/a) | | |")
    out.append(f"| Exit multiple | {fmt(agent_exit_multiple, 1, suffix='x')} | (n/a) | | |")
    out.append(f"| FY1 EBITDA ($M) | {fmt(agent_fy1_ebitda, 0)} | — | | |")
    out.append(f"| DCF Gordon PT | ${fmt(agent_dcf_gordon, 0)} | — | | |")
    out.append(f"| DCF Exit PT | ${fmt(agent_dcf_exit, 0)} | — | | |")
    out.append(f"| Comps PT | ${fmt(agent_comps, 0)} | — | | |")
    out.append(f"| **Blended PT** | **${fmt(agent_pt, 0)}** | — | | |")
    out.append(f"| Sell-side mean PT | — | ${fmt(tgt_mkt.get('analyst_pt_mean'), 0)} (n={tgt_mkt.get('n_analysts') or '?'}) | {pct_diff(agent_pt, tgt_mkt.get('analyst_pt_mean'))} | |")
    out.append(f"| Sell-side range | — | ${fmt(tgt_mkt.get('analyst_pt_low'), 0)} – ${fmt(tgt_mkt.get('analyst_pt_high'), 0)} | | |")

    # Per-peer breakdown
    out.append(f"\n**Peer detail (market data, n={len(peer_data)}):**\n")
    out.append("| Peer | EV/EBITDA | Fwd P/E | Trail P/E |")
    out.append("|---|---|---|---|")
    for p in peer_data:
        if p.get("error"):
            out.append(f"| {p['ticker']} | ERROR | | |")
        else:
            out.append(f"| {p['ticker']} | {fmt(p.get('ev_ebitda'), 1, suffix='x')} | {fmt(p.get('fwd_pe'), 1, suffix='x')} | {fmt(p.get('trail_pe'), 1, suffix='x')} |")

    return "\n".join(out)


def main():
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    print(f"# Calibration Audit — {ts}\n")
    print(f"Run from {ROOT}\n")

    sections = []
    for tgt, peers in TARGETS.items():
        print(f"Processing {tgt}...", file=sys.stderr)
        sections.append(audit_one(tgt, peers))

    full = "\n".join(sections)
    print(full)

    # Save
    audit_dir = RUNS_DIR / "_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    out_path = audit_dir / f"calibration_audit_{ts}.md"
    with open(out_path, "w") as f:
        f.write(f"# Calibration Audit — {ts}\n\nRun from {ROOT}\n\n{full}")
    print(f"\n\nSaved to: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
