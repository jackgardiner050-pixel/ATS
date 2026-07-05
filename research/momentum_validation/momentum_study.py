#!/usr/bin/env python3
"""Item 8 — Momentum signal validation (self-contained, deterministic).

Validates the 12-1 price-momentum signal used by src/signals/momentum.py, which
currently lets Q1 alignment bump entry confidence (LOW→MED→HIGH).

SIGNAL (replicates momentum.py exactly): at each month-end t, momentum =
close[t-1] / close[t-12] − 1 (T-12 to T-1 month-end closes; the most recent month
is skipped). Quintiles within the universe; Q1 = top.

STUDY: monthly-rebalanced equal-weight Q1 vs Q5 vs universe-EW vs SPY total return,
2015-01..2025-12, yfinance auto_adjust closes. Cost: 20 bps per side on turnover.

REUSE (per infra map): batched auto_adjust download follows swing-bot
run_backtest.py:190 (_load_price_cache); month-end resample follows momentum.py:44;
per-side bps cost follows src/portfolio/nav_ledger.py:93. BUILT FRESH: the monthly
rebalance walk-forward and the Newey-West HAC t-stat (absent repo-wide).

SURVIVORSHIP (honest): config/universe.yaml is a *recently hand-curated* 147-name
list of survivors (a fixed BUG-001 delisting, SUM, plus other removed names — see
KNOWN_BUGS.md). Using today's members back to 2015 injects two biases, opposite in
sign for the SPREAD:
  (1) excluding failed/delisted firms (which would have had poor momentum → Q5)
      raises Q5 returns → NARROWS the Q1−Q5 spread (conservative for momentum);
  (2) selecting recent winners into the universe inflates Q1 → WIDENS the spread.
Net direction is discussed in the memo; absolute return levels are biased UP either
way. This study cannot remove the bias (no point-in-time membership); it quantifies
direction and treats the result accordingly.

Run:  python research/momentum_validation/momentum_study.py
Out:  results_monthly.csv, results_summary.csv (this directory)
NOTE: the brief said "60 tickers"; the actual universe is 147. We use 147 and flag it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

np.random.seed(1234)   # fixed seed (no stochastic step, but pinned for reproducibility)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
UNIVERSE = ROOT / "config" / "universe.yaml"

START, END = "2014-11-01", "2025-12-31"   # 12m lookback before the 2015-01 first formation
FORM_START = "2015-01-31"
COST_BPS = 20.0
CACHE = HERE / "_price_cache.parquet"


def load_universe() -> list[str]:
    cfg = yaml.safe_load(UNIVERSE.read_text()) or {}
    return sorted({t.upper() for t in cfg.get("universe", [])})


def fetch_monthly_closes(tickers: list[str]) -> pd.DataFrame:
    """Month-end auto_adjust closes, batched (swing-bot pattern). Cached to parquet."""
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        raw = yf.download(batch, start=START, end=END, auto_adjust=True,
                          progress=False, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        for t in batch:
            if t in close.columns:
                frames[t] = close[t]
        time.sleep(0.5)
    px = pd.DataFrame(frames)
    monthly = px.resample("ME").last()
    monthly.to_parquet(CACHE)
    return monthly


def newey_west_tstat(x: np.ndarray, lags: int | None = None) -> tuple[float, float, int]:
    """HAC (Newey-West) t-stat of the mean of x. Returns (mean, tstat, lags)."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), 0
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))   # standard automatic rule
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        var += 2.0 * w * (e[l:] @ e[:-l]) / n
    se = np.sqrt(var / n)
    return mu, (mu / se if se > 0 else float("nan")), lags


def ann_stats(monthly_ret: pd.Series) -> dict:
    r = monthly_ret.dropna()
    if len(r) == 0:
        return {"ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan, "max_dd": np.nan}
    ann_return = (1 + r).prod() ** (12.0 / len(r)) - 1
    ann_vol = r.std(ddof=1) * np.sqrt(12)
    sharpe = (r.mean() * 12) / ann_vol if ann_vol > 0 else np.nan
    equity = (1 + r).cumprod()
    max_dd = (equity / equity.cummax() - 1).min()
    return {"ann_return": ann_return, "ann_vol": ann_vol, "sharpe": sharpe, "max_dd": max_dd}


def run() -> int:
    tickers = load_universe()
    print(f"[momentum] universe = {len(tickers)} tickers (brief said 60 — actual is 147; using actual)")
    monthly = fetch_monthly_closes(tickers)
    monthly = monthly.dropna(how="all")
    months = monthly.index[monthly.index >= pd.Timestamp(FORM_START)]

    spy = None
    try:
        import yfinance as yf
        spy_px = yf.download("SPY", start=START, end=END, auto_adjust=True, progress=False)["Close"]
        spy = spy_px.resample("ME").last()
        if isinstance(spy, pd.DataFrame):
            spy = spy.iloc[:, 0]
    except Exception as e:
        print(f"[momentum] WARNING SPY fetch failed: {e}")

    rows = []
    prev_q1, prev_q5, prev_ew = set(), set(), set()
    for t in months:
        idx = monthly.index.get_loc(t)
        if idx < 12 or idx + 1 >= len(monthly.index):
            continue   # need 12m lookback and a forward month to realize the return
        t_prev = monthly.index[idx - 1]     # T-1
        t_12 = monthly.index[idx - 12]      # T-12
        t_next = monthly.index[idx + 1]

        mom = (monthly.loc[t_prev] / monthly.loc[t_12] - 1.0).dropna()
        if len(mom) < 10:
            continue
        ranked = mom.sort_values(ascending=False)
        n = len(ranked)
        q_size = max(1, n // 5)
        q1 = set(ranked.index[:q_size])
        q5 = set(ranked.index[-q_size:])
        ew = set(ranked.index)

        fwd = (monthly.loc[t_next] / monthly.loc[t] - 1.0)   # realized next-month return

        def port_ret(names, prev):
            r = fwd.reindex(list(names)).dropna()
            if len(r) == 0:
                return np.nan, 0.0
            gross = r.mean()
            turnover = len(names ^ prev) / max(len(names | prev), 1)   # symmetric-diff / union
            cost = 2 * turnover * COST_BPS / 1e4    # both sides of the changed fraction
            return gross - cost, turnover

        q1_r, q1_to = port_ret(q1, prev_q1)
        q5_r, q5_to = port_ret(q5, prev_q5)
        ew_r, ew_to = port_ret(ew, prev_ew)
        prev_q1, prev_q5, prev_ew = q1, q5, ew

        spy_r = np.nan
        if spy is not None and t in spy.index and t_next in spy.index:
            spy_r = float(spy.loc[t_next] / spy.loc[t] - 1.0)

        rows.append({"date": t.date().isoformat(), "n": n,
                     "Q1": q1_r, "Q5": q5_r, "EW": ew_r, "SPY": spy_r,
                     "Q1_minus_Q5": q1_r - q5_r, "Q1_minus_SPY": q1_r - spy_r,
                     "Q1_turnover": q1_to})

    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results_monthly.csv", index=False)

    # Summary
    summary = []
    for col in ["Q1", "Q5", "EW", "SPY"]:
        s = ann_stats(df[col])
        summary.append({"portfolio": col, **s})
    spread = df["Q1_minus_Q5"].to_numpy()
    mu, tstat, lags = newey_west_tstat(spread)
    q1_beat_spy = float((df["Q1_minus_SPY"] > 0).mean())

    sm = pd.DataFrame(summary)
    sm.to_csv(HERE / "results_summary.csv", index=False)

    print("\n=== Annualized stats ===")
    print(sm.to_string(index=False))
    print(f"\nQ1−Q5 monthly spread: mean={mu*100:+.3f}%/mo  "
          f"ann≈{mu*12*100:+.2f}%  Newey-West t={tstat:.2f} (lags={lags}, n={len(spread)})")
    print(f"Fraction of months Q1 beat SPY: {q1_beat_spy:.1%}")
    verdict = "(a) keep confidence bump" if (abs(tstat) >= 2 and mu > 0) else \
              "(b) neutralize momentum to observation-only  [or (c) if data thin]"
    print(f"DECISION (t<2 on net spread ⇒ NOT (a)): {verdict}")
    print(f"\nWrote {HERE/'results_monthly.csv'} and {HERE/'results_summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
