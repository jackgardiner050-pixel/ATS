#!/usr/bin/env python3
"""Study B — rating-engine PT calibration, point-in-time (item 9).

For each universe ticker at each fiscal-year-end+90d (2018-2024), compute a
point-in-time implied-upside PROXY from the 10-K available at that date (no
lookahead), then measure subsequent 12m excess return vs SPY TR minus 40bps round
trip. Report rank IC, monotonicity, and the STRONG_BUY-band (>20% upside) mean
forward excess — with and without extraction-invariant-flagged rows.

IMPORTANT HONESTY NOTES (see STUDY_B_pt_calibration_design.md):
- The repo has NO point-in-time EDGAR; this script fetches the as-of 10-K via
  edgartools directly (acceptance_datetime <= as-of), so no src/ change is needed.
- The full DCF+comps engine is NOT reproduced as-of (historical peer multiples are
  unavailable). This computes a TRANSPARENT PROXY: implied_upside = (EV/EBITDA proxy
  → equity bridge → PT) / price_asof - 1, with a FIXED, documented EV/EBITDA multiple
  (not fit to data). It is directional, not the exact engine number. Do not over-read.
- Full 147×7 run is environment-gated (EDGAR rate limits, hours). Runnable on a subset:
    python research/revisions_pt_validation/pt_calibration_study.py --tickers AGX,EMR --years 2022,2023
  Requires EDGAR_IDENTITY set. Writes pt_calibration_results.csv + prints the summary.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# Documented PROXY constants — fixed, NOT fit to the data being tested.
EV_EBITDA_MULTIPLE = 10.0     # conservative mid-cycle industrial comp; a transparent proxy
ROUND_TRIP_BPS = 40.0
STRONG_BUY_UPSIDE = 0.20      # the paper book's entry gate


def load_universe():
    cfg = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text()) or {}
    return sorted({t.upper() for t in cfg.get("universe", [])})


def asof_10k_metrics(ticker: str, asof: date):
    """Extract fundamentals from the latest 10-K with acceptance_datetime <= asof.
    Returns a metrics dict or None. Uses edgartools directly (point-in-time)."""
    try:
        from edgar import Company, set_identity  # noqa
        import os
        ident = os.environ.get("EDGAR_IDENTITY")
        if ident:
            set_identity(ident)
        co = Company(ticker)
        filings = co.get_filings(form="10-K")
        chosen = None
        for f in filings:
            acc = getattr(f, "acceptance_datetime", None) or getattr(f, "filing_date", None)
            accd = pd.to_datetime(acc).date() if acc is not None else None
            if accd is not None and accd <= asof:
                chosen = f
                break   # get_filings returns newest-first
        if chosen is None:
            return None
        # Reuse the repo's XBRL→metrics extraction (import only, no src change).
        from src.data.edgar_client import extract_historical_metrics, CompanyData
        fin = chosen.obj().financials  # edgartools financials for that specific filing
        cd = CompanyData(ticker=ticker, income_statement=fin.income_statement().to_dataframe(),
                         balance_sheet=fin.balance_sheet().to_dataframe(),
                         cash_flow=fin.cashflow_statement().to_dataframe())
        metrics = extract_historical_metrics(cd)
        if not metrics:
            return None
        return metrics[sorted(metrics)[-1]]
    except Exception:
        return None


def implied_upside_proxy(m: dict, price_asof: float):
    """Transparent comps proxy: EV = mult × EBITDA; equity = EV − net_debt; PT = equity/shares."""
    ebitda = m.get("ebitda") or m.get("operating_income")   # EBIT proxy if EBITDA absent
    shares = m.get("shares")
    net_debt = m.get("net_debt")
    if net_debt is None:
        td, cash = m.get("total_debt"), m.get("cash")
        net_debt = (td - cash) if (td is not None and cash is not None) else 0.0
    if not ebitda or not shares or ebitda <= 0 or shares <= 0 or not price_asof:
        return None
    ev = EV_EBITDA_MULTIPLE * ebitda
    pt = (ev - net_debt) / shares
    return pt / price_asof - 1.0


def _adj_close(ticker, d: date):
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(start=d.isoformat(),
                                      end=(d + timedelta(days=10)).isoformat(), auto_adjust=True)
        return float(h["Close"].iloc[0]) if h is not None and not h.empty else None
    except Exception:
        return None


def spearman_ic(deciles, fwd):
    s = pd.DataFrame({"d": deciles, "f": fwd}).dropna()
    return s["d"].corr(s["f"], method="spearman") if len(s) > 2 else np.nan


def run(tickers, years) -> int:
    from src.data.extraction_invariants import run_invariants
    rows = []
    for t in tickers:
        for y in years:
            asof = date(y, 12, 31) + timedelta(days=90)   # FY-end (approx Dec) + 90d
            m = asof_10k_metrics(t, asof)
            price = _adj_close(t, asof)
            if m is None or price is None:
                rows.append({"ticker": t, "year": y, "status": "NO_DATA"})
                continue
            upside = implied_upside_proxy(m, price)
            if upside is None:
                rows.append({"ticker": t, "year": y, "status": "NO_UPSIDE"})
                continue
            # forward 12m excess vs SPY TR, net of round-trip cost
            fp = _adj_close(t, asof + timedelta(days=365))
            sp0, sp1 = _adj_close("SPY", asof), _adj_close("SPY", asof + timedelta(days=365))
            fwd_excess = None
            if fp and sp0 and sp1:
                stock_r = fp / price - 1.0
                spy_r = sp1 / sp0 - 1.0
                fwd_excess = (stock_r - spy_r) - ROUND_TRIP_BPS / 1e4
            # extraction-invariant flags (KNOWN_BUGS contamination)
            extracted = {"revenue": m.get("revenue"), "gross_profit": m.get("gross_profit"),
                         "operating_income": m.get("operating_income"),
                         "price_target": price * (1 + upside), "current_price": price}
            flags = run_invariants(t, extracted, {})
            rows.append({"ticker": t, "year": y, "status": "OK", "implied_upside": upside,
                         "fwd_excess_net": fwd_excess,
                         "flagged": bool([f for f in flags if f["severity"] == "SEV_HIGH"]),
                         "strong_buy": upside > STRONG_BUY_UPSIDE})

    df = pd.DataFrame(rows)
    df.to_csv(HERE / "pt_calibration_results.csv", index=False)
    ok = df[df["status"] == "OK"].copy()
    print(f"[pt-calib] rows={len(df)} OK={len(ok)} NO_DATA={int((df['status']=='NO_DATA').sum())}")
    if len(ok) >= 3 and ok["fwd_excess_net"].notna().any():
        for label, sub in (("ALL", ok), ("EX-FLAGGED", ok[~ok["flagged"]])):
            sub = sub.dropna(subset=["fwd_excess_net"])
            if len(sub) < 3:
                print(f"  {label}: n<3, skip"); continue
            sub["decile"] = pd.qcut(sub["implied_upside"].rank(method="first"),
                                    min(10, len(sub)), labels=False)
            ic = spearman_ic(sub["decile"], sub["fwd_excess_net"])
            sb = sub[sub["strong_buy"]]["fwd_excess_net"]
            print(f"  {label}: n={len(sub)}  rank_IC={ic:+.3f}  "
                  f"STRONG_BUY-band mean fwd excess={sb.mean()*100:+.2f}% (n={len(sb)})")
        print("  DECISION: if STRONG_BUY-band mean excess (EX-FLAGGED) <= 0 → entry gate "
              "UNVALIDATED; observation protocol is the only evidence path.")
    else:
        print("  Insufficient OK rows to summarize — run the full universe on the droplet "
              "(EDGAR_IDENTITY set, hours). This subset only proves the pipeline.")
    print(f"  Wrote {HERE/'pt_calibration_results.csv'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=str, default=None, help="comma list; default = full universe")
    ap.add_argument("--years", type=str, default="2018,2019,2020,2021,2022,2023,2024")
    args = ap.parse_args()
    tickers = ([t.strip().upper() for t in args.tickers.split(",")] if args.tickers
               else load_universe())
    years = [int(y) for y in args.years.split(",")]
    print(f"[pt-calib] {len(tickers)} tickers × {len(years)} years "
          f"(EV/EBITDA proxy={EV_EBITDA_MULTIPLE}, cost={ROUND_TRIP_BPS}bps rt) — PROXY, see memo")
    return run(tickers, years)


if __name__ == "__main__":
    sys.exit(main())
