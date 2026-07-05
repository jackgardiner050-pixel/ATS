# Analysis Plan — Hypothesis 001: Cross-sectional Momentum (FROZEN)

Pre-registered plan. Frozen at registration; the registry stores its sha256 as
`analysis_plan_sha`. Editing this file after registration breaks the entry-content chain.

- **Hypothesis:** 12–1 month price momentum predicts forward excess return in large-cap US
  equities: the top-quintile-minus-bottom-quintile (Q1−Q5) monthly net spread is positive
  with a Newey-West HAC t-statistic ≥ 2.0.
- **Universe:** large-cap US equities (config/universe.yaml), point-in-time.
- **Signal:** trailing 12-month return skipping the most recent month; sort into quintiles.
- **Rebalance:** monthly, equal-weight within quintile.
- **Metric:** Q1−Q5 monthly net-of-cost spread; significance by Newey-West HAC t (lag = 6).
- **Decision rule (pre-registered):** PASS iff net spread > 0 AND t ≥ 2.0 over the full
  backtest window; otherwise FAIL. Inconclusive is not a pass.
- **Costs:** round-trip transaction costs applied per rebalance.
