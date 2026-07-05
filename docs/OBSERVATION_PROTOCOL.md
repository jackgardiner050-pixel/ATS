# OBSERVATION PROTOCOL — Paper-Trading Validation

**Status:** DRAFT — pending approval & hash-lock · **Drafted:** 2026-07-05
**System:** long-only paper book, US large/mid cap, 60-name universe, weekly rescreen, DCF+comps rating engine.
**Style:** pre-registration. Once approved, this file and its frozen inputs are hash-locked (§0); any edit is a deliberate re-registration, never a tune-to-flatter.

---

## 0. Lock mechanism

At Cohort-1 inception, `config/protocol_lock.yaml` records — modeled on `gaia/rules.yaml` —
`locked: true`, `registered: <inception date>`, and a `lock_sha` over the concatenation of:
this document, `config/universe.yaml`, the entry/exit ruleset, the cadence table, and the
rating-engine version (`src/version.py` lineage + git commit SHA). A pre-run check verifies
`lock_sha` against those inputs; a mismatch **halts the screen**. Changing any locked input
without re-registration is a process violation (§5).

## 1. Legacy Cohort (12 positions opened 2026-05-25, pre-fix engine)

1.1 **Not evidence.** Legacy Cohort performance is **NOT** evidence of system validity. It was
opened under an engine with known, since-patched extraction bugs. It is **informational / gut-check
only** and MUST carry the label *"informational only — not evidence of system validity"* on every
report and dashboard where it appears.

1.2 **Sunset rule — (b) fixed date, forced close 2026-08-23 (open + 90 days).** Chosen over
run-to-natural-exit because (a) would couple legacy positions to the *fixed* engine's downgrade
logic — contaminating the clean Cohort-1 record — and leaves an open-ended tail that keeps capital
tied up and forces dual reporting indefinitely. A fixed date gives bounded, dated closure, frees
capital before Cohort-1 matures, and keeps the paper book's capital/reporting simple. The forced
close is a mechanical action, tagged `forced_sunset`, and is **not** counted as an entry/exit signal.
On close, the cohort is reported once as a closed footnote and never resurfaced as a live series.

1.3 **Data tag (enforced, not convention).** Every Legacy position/trade record MUST carry
`cohort: legacy_pre_fix`. Enforcement is automated: the load-time schema validators
(`validate_position` / `validate_trade`) require a `cohort` field ∈ {`legacy_pre_fix`, `cohort_1`};
a missing/invalid tag is logged WARN + excluded, and the **report build aborts** if any record lacks
a valid cohort tag. Tagging is a gate, not a naming habit.

## 2. Cohort-1 definition

2.1 **Inception** = the date of the first screen run executed under the locked ruleset (i.e. after
§0 hash-lock). No position opened before inception is Cohort-1.

2.2 **Frozen at inception:** universe membership, entry/exit rules, cadence table, and rating-engine
math are fixed by the `lock_sha`. Every Cohort-1 record carries `cohort: cohort_1`.

## 3. Observation window — **52 weeks** (1 year)

Recommended at the top of the 26–52 range to maximize n, span a full earnings/seasonal cycle, and
grow the calibration sample. **Power reality:** for a ~20-stock equal-weight book vs SPY TR with
annualized tracking error (TE) of 4–8%, the standard error of the estimated annualized excess return
is `SE = TE / √τ` (τ = years). The minimum excess return distinguishable from zero at ~95%
(≈ 2·SE) is:

| Window | τ | SE @ TE=4/6/8% | ~2·SE (min detectable excess) |
|--------|-----|----------------|-------------------------------|
| 26 wk  | 0.50 | 5.7 / 8.5 / 11.3% | **11 / 17 / 23% ann.** |
| 52 wk  | 1.00 | 4.0 / 6.0 / 8.0%  | **8 / 12 / 16% ann.** |

Realistic skill alpha (~1–4%/yr) sits far below every cell. **26 weeks cannot establish statistical
significance on excess return; 52 weeks almost certainly cannot either** unless alpha is implausibly
large. Stated plainly, the window **CANNOT** prove alpha ≠ 0. What it **CAN** establish: (i) **process
integrity** — rules executed exactly as locked; (ii) **cost realism** — modeled vs realized
commission/slippage; (iii) a **calibration sample** — ~30–60 closed trades at 52 weeks (vs a thin
~15–30 at 26), enough for a meaningful PT decile plot and a hit-rate with usable confidence width.

## 4. Pre-declared metrics (Cohort-1 only)

1. **TWR vs SPY TR** — time-weighted return of the book minus SPY total return (dividends included),
   over the window. Time-weighting neutralizes cashflow timing.
2. **Information Ratio** — annualized mean weekly excess return ÷ annualized TE. Reported as a point
   estimate with its CI; never asserted as significant (§3).
3. **Max-drawdown ratio** — peak-to-trough drawdown of the book ÷ that of SPY over the same window.
4. **Hit-rate of closed trades** — fraction of closed trades with positive alpha vs SPY over the
   holding period (the record's `alpha` field), reported with n.
5. **PT calibration** — realized forward return vs engine-implied upside, bucketed into deciles of
   implied upside (decile plot); summarized by the Spearman rank correlation of decile vs realized.

## 5. Gates (numbers, not adjectives)

Burn-in: gates below apply after **week 8**. Decisions are pre-registered decision rules under
acknowledged uncertainty (§3), not significance claims.

**KILL — stop immediately, post-mortem, no new entries — if ANY:**
- Realized annualized excess (TWR vs SPY TR) **< −10%**, sustained 2 consecutive weekly marks.
- **Max-DD ratio > 1.5** (book draws down >1.5× SPY over the same window).
- **Hit-rate < 35%** after ≥20 closed trades.
- **Any process violation:** an untagged/mistagged record; an entry/exit not matching the locked
  ruleset; a `lock_sha` mismatch; a calibration-class engine change shipped mid-window (§6); a rating
  emitted from a silently-swallowed engine exception.

**CONTINUE (default / expected state):** none of KILL met, SUCCESS not yet met → run to full window.
Inconclusive is the anticipated outcome and is not a failure.

**SUCCESS — advance to next phase — only if ALL hold at window end (≥52 wk):**
- **IR ≥ 0.5** over the full window.
- **Max-DD ratio ≤ 1.2**.
- **PT calibration Spearman ≥ 0.30** (implied-upside ordering carries information).
- **Hit-rate ≥ 50%** over **≥30 closed trades**.
- **Zero process violations** across the entire window.

**Legacy Cohort has no gates and no kill criteria** — it only runs its §1.2 sunset.

## 6. Change policy (during the Cohort-1 window)

**Protocol-breaking (forbidden mid-window; forces a re-registered Cohort-2):** any change to
entry/exit rules, universe membership, the cadence table, or **rating-engine math** (DCF/comps
formulas, extraction label maps that alter output *values*, confidence/escalation thresholds).

**Allowed mid-window:** **crash-class bug fixes only** — a fix for a defect that would otherwise raise
an exception or crash the run; plus reporting-layer/dashboard changes, logging, and refactors *proven
output-identical* by a golden test. **Calibration-class fixes** (changes that move numbers without
crashing) are **queued for Cohort-2**, documented, and **not applied** to the live cohort. Fixing a
number mid-window silently re-writes the experiment — so we don't.

## 7. Reporting rule (hard formatting requirement — not a suggestion)

Every report and dashboard that surfaces performance **MUST** render Legacy Cohort and Cohort-1 as
**two visually distinct sections**. There is **NO** combined performance number and **NO** combined
chart series — ever. Legacy always carries its §1.1 label. A build that emits a blended figure or a
shared series is non-conforming and must fail the report check.

---

### LOCK BLOCK (populated at approval)
```
locked:      false        # → true on approval
registered:  <inception date>
lock_sha:    <sha256 over §0 inputs>
```
