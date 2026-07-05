# Analysis Plan — Hypothesis 002: Post-Earnings-Announcement Drift / Kairos (FROZEN)

Pre-registered plan. Frozen at registration; the registry stores its sha256 as
`analysis_plan_sha`. Editing this file after registration breaks the entry-content chain.

- **Hypothesis:** Large positive earnings surprises are followed by positive net-of-cost
  excess return over the subsequent drift window (PEAD), exploitable in the traded universe.
- **Universe:** US equities with scheduled earnings events (swing-bot event universe).
- **Signal:** standardized earnings surprise (SUE) above a pre-set threshold at the event.
- **Holding:** enter at the post-announcement open; hold a fixed drift window.
- **Metric:** mean net-of-cost excess return over the drift window vs the benchmark.
- **Decision rule (pre-registered):** PASS iff the mean net excess is positive and clears
  the significance bar; otherwise FAIL.
- **Costs:** commissions + slippage applied at entry and exit.
