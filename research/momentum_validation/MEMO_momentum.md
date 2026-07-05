# Momentum Signal Validation — Findings (item 8)

**Date:** 2026-07-05 · **Script:** `momentum_study.py` (seed fixed) · **Data:** yfinance
auto_adjust monthly closes, 2015-01..2025-12 · **Cost:** 20 bps/side on turnover.

## Decision: **(b) neutralize momentum to observation-only.**
The net-of-cost Q1−Q5 spread has Newey-West **t = 0.09** (≪ 2). Per the pre-committed
frame, t < 2 on the net spread means the evidence does **not** support letting Q1
alignment bump entry confidence (the current LOW→MED→HIGH behavior). Downgrade
momentum to observation-only.

## Results (annualized, net of cost)

| Portfolio | Ann. return | Ann. vol | Sharpe | Max DD |
|-----------|------------:|---------:|-------:|-------:|
| Q1 (top momentum) | 18.3% | 17.3% | 1.06 | −17.5% |
| Q5 (bottom)       | 17.2% | 20.6% | 0.88 | −25.2% |
| Universe EW       | 18.0% | 15.9% | **1.13** | −19.1% |
| SPY TR            | 14.5% | 15.0% | 0.98 | −23.9% |

- **Q1 − Q5 spread:** +0.032%/mo → **≈ +0.38%/yr**, Newey-West **t = 0.09** (lags 4, n = 121).
- **Q1 beat SPY** in **58.7%** of months.
- Universe-EW has the **best** risk-adjusted return — Q1 does not separate from the
  universe, and barely from Q5. Momentum provides essentially **no quintile sorting**
  in these 147 names.

## What this can and cannot establish
It **can** say: within this universe and window, net-of-cost momentum quintiles are
statistically indistinguishable (t = 0.09), and Q1 carries no Sharpe advantage over
simply holding the universe equal-weight. It **cannot** prove momentum is dead in
general — only that it does not earn its keep as a confidence input *here*.

## Survivorship — honest accounting
`config/universe.yaml` is a **recently hand-curated 147-name survivor list** (BUG-001
removed the delisted SUM; other removed names noted in the file). Using today's members
back to 2015 injects bias:
- **Absolute levels are biased UP** — every portfolio (incl. EW at 18% vs SPY 14.5%)
  benefits from selecting names that survived and were chosen in 2026.
- **On the Q1−Q5 spread the sign is ambiguous:** excluding failed firms (extreme Q5
  losers) raises Q5 → **deflates** the spread; selecting persistent recent winners
  raises Q1 → **inflates** it. In a survivor set the missing-failures effect is the
  larger one, so the *true* spread is, if anything, modestly **higher** than measured.
- **Robustness:** t = 0.09 is so far below 2 that no plausible bias correction rescues
  significance. If anything a survivor-biased universe should *flatter* momentum
  (winners persist), yet the spread is ~0 — which strengthens conclusion (b).

## Caveats / notes
- **Universe size:** the brief said "60 tickers"; the actual `universe.yaml` is **147**.
  This study used 147 and flags the discrepancy. (The "60 names" is a stale BUG-001 note.)
- **Point-in-time membership** is unavailable, so the survivorship bias cannot be removed,
  only bounded in direction (above).
- Turnover cost applied as `2 × one-way-turnover × 20 bps` per rebalance (both traded
  sides), reusing the per-side model from `src/portfolio/nav_ledger.py`.
- No `src/` changes. Reused: swing-bot batched auto_adjust pull pattern, momentum.py
  month-end resample. Built fresh: monthly-rebalance walk-forward, Newey-West HAC.

## Recommendation
Set momentum to **observation-only** (log the quintile, do not let it move confidence).
Keep logging so the question can be revisited on more (and ideally point-in-time) data.
Files: `results_monthly.csv` (121 months), `results_summary.csv`.
