# Study A — EPS-Revisions Signal: Design Memo (item 9)

**Signal (src/signals/revisions.py):** FY1 consensus EPS *now* vs *90 days ago*
(yfinance `eps_trend` row `+1y`, `current` vs `90daysAgo`), ±2% → POSITIVE / NEGATIVE
/ FLAT. Currently this can nudge entry confidence via the alignment logic.

## Core problem: the data has no history
`eps_trend` returns **only current snapshots** — `current` and `90daysAgo` are both
live values as of the call; there is no stored time series. Confirmed against the repo
(revisions.py:51-59) and the codebase infra map. **A true historical backtest is
therefore impossible from yfinance** — you cannot reconstruct what the FY1 consensus
was on an arbitrary past date, nor what the 90-days-prior anchor was.

### Reuse check (required by brief)
Checked swing-bot's PEAD backtest for a reusable **point-in-time** methodology. It is
**not reusable for revisions**: PEAD keys events on SEC 8-K `filingDate` (recent-block
only, no `acceptanceDateTime`), and it studies *price reaction to earnings*, a different
signal on a different data source. It has no consensus-EPS history and no as-of
reconstruction. Nothing reused from PEAD here; the two answer different questions.

### Free proxy point-in-time sources — availability
- **I/B/E/S / FactSet / Refinitiv** (the real consensus-revision history): paid.
- **yfinance:** current snapshot only (this signal's source).
- **Finnhub / FMP free tiers:** expose current estimates and limited recent history, but
  not a clean, dense, universe-wide FY1-consensus time series back several years, and
  their free rate limits make a 147-name multi-year pull impractical.
- **Verdict:** no defensible free point-in-time source exists. We do **not** proxy-
  backtest on an unreliable feed (that would manufacture a false result). Instead we do
  **forward observation** (below), starting now.

## Solution (1): start logging now — `scripts/log_eps_trend.py` (the one repo addition)
Appends one JSONL line per universe ticker per run to `data/eps_trend_history.jsonl`
(`{date, ticker, fy1_current, fy1_90d_ago, direction, fetched_at_utc}`), logging only —
no decisions, no `src/` change. Run **weekly** via cron. Every logged week grows the
forward sample. Classification mirrors revisions.py (±2%).

## Solution (2): forward-observation design & power
**Test:** does the POSITIVE cohort earn higher subsequent forward return than the
NEGATIVE cohort? Each week, tag each ticker POSITIVE/NEGATIVE/FLAT from the logged
snapshot; measure the **forward monthly excess return** (vs SPY TR) of the POSITIVE vs
NEGATIVE groups; pool cross-sections and test the mean difference with a Newey-West
t-stat (returns overlap → HAC required).

**How many weeks until testable?** Power sketch at the universe's n:
- Universe n = 147; typically ~⅓ carry a non-FLAT direction → group sizes ~n₁,n₂ ≈ 20–40.
- Monthly idiosyncratic stock vol σ ≈ 8–10%. SE of a single monthly cross-sectional
  difference-in-means ≈ σ·√(1/n₁ + 1/n₂) ≈ 9%·√(2/30) ≈ **2.3%/month**.
- The signal moves on a 90-day window and revision states are **persistent**, so weekly
  snapshots are highly autocorrelated — effective **independent** cross-sections accrue
  roughly **monthly to quarterly**, not weekly.
- To detect a *plausible* edge of ≈ **+1%/month** POSITIVE−NEGATIVE difference at t ≥ 2:
  need √(k)·(effect/SE) ≥ 2 → √k ≥ 2·(2.3/1.0) ≈ 4.6 → **k ≈ 21 independent monthly
  cross-sections**. With HAC/autocorrelation inflating variance ~1.5–2×, call it
  **~30 effective months**.
- **Bottom line:** expect a *first, weak* read after **~12–18 months** of weekly logging,
  and a **~2.5–3 year** horizon for a robust POSITIVE-vs-NEGATIVE forward-return test at
  this universe's n and a realistic ~1%/mo effect. A smaller true effect needs longer.

## Decision frame
Until ≥ ~18 months of forward data exist, the revisions signal's forward value is
**(c) insufficient data** — it should be treated as **observation-only** (log the
direction; do not let it move confidence), exactly like the momentum recommendation in
item 8. Re-evaluate once `eps_trend_history.jsonl` has the sample above.

**Deliverables:** this memo; `scripts/log_eps_trend.py` (runnable now, logging only). No
results CSV yet — by construction, the data does not exist until forward logging accrues.
