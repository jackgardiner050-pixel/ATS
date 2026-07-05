# Analysis Plan — Hypothesis 003: Oracle / Cohort-1 causal-rating book (FROZEN)

Pre-registered plan; this is a transcription/pointer to the pre-declared gates in
`docs/OBSERVATION_PROTOCOL.md` §3–5 (itself hash-locked). Frozen at registration; the
registry stores this file's sha256 as `analysis_plan_sha`.

- **Hypothesis:** STRONG_BUY-gated entries (MED/HIGH confidence) beat SPY TR net of costs
  over the 52-week window, per the §5 SUCCESS gate.
- **Universe:** ~20-stock equal-weight book from the locked universe (config/universe.yaml),
  benchmarked vs SPY total return.
- **Window:** 52 weeks (1 year) — §3.
- **Metrics (§4):** TWR vs SPY TR; Information Ratio; hit-rate of closed trades (alpha vs
  SPY); PT-calibration Spearman.
- **SUCCESS threshold (§5, at window end):** IR ≥ 0.5; Max-DD ratio ≤ 1.2; PT calibration
  Spearman ≥ 0.30; hit-rate ≥ 50% over ≥30 closed trades; zero process violations.
- **Power caveat (§3):** the window CANNOT establish alpha ≠ 0; it establishes process
  integrity, cost realism, and a calibration sample. Status is TESTING — no result yet.
