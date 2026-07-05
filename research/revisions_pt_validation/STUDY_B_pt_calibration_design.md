# Study B — Rating-Engine PT Calibration (point-in-time): Design & Execution Memo (item 9)

**Question:** does the DCF+comps engine's implied upside (`PT/price − 1`,
`src/engine/calculator.py` via `src/data/edgar_client.py`) predict forward excess
return — and specifically, does the **STRONG_BUY band (>20% upside)**, which is the
paper book's entry gate, have **positive mean 12-month forward excess return** after
costs? If not, the entry gate is unvalidated.

## Design (as specified)
For each of the 147 universe tickers, at each **fiscal-year-end + 90 days** from
**2018–2024** (the as-of date, ensuring the 10-K was filable/known):
1. Using **only filings available at the as-of date** (10-K with `acceptanceDateTime`
   ≤ as-of) and **trailing prices** (no lookahead), compute the engine's implied upside.
2. Record the subsequent **12-month excess return** vs SPY total return, minus **40 bps
   round-trip** cost.
3. Bucket implied upside into **deciles**; report **rank IC** (Spearman of decile vs
   forward excess), **monotonicity**, and the **STRONG_BUY-band** mean forward excess.
4. **Flag** every ticker-date where extraction invariants fire (gross margin > 90%,
   PT/price outside [0.2, 3.0] — from `src/data/extraction_invariants.py` / KNOWN_BUGS).
   Report results **with and without** flagged rows; the delta measures how much the
   KNOWN_BUGS extraction class contaminates the signal.

## Reuse check (required by brief)
- **Point-in-time EDGAR:** the repo has **none**. `edgar_client.fetch_company` is
  latest-only (no as-of / acceptance-timestamp filter); swing-bot's PEAD keys 8-Ks on
  `filingDate` from the `recent` block only. So a faithful point-in-time pull must be
  built in the research script using **edgartools directly** (filings filtered by
  `acceptance_datetime`), NOT by editing `src/` (forbidden). We **reuse**
  `edgar_client.extract_historical_metrics` (import, no change) for the XBRL→metrics
  mapping, and `extraction_invariants.run_invariants` for the flagging.
- **Cost model:** reuse the per-side bps formula (`nav_ledger.py`), 40 bps round trip.

## Execution constraints — stated honestly (this is why the full run is gated)
A faithful full run is **environment-gated (droplet, hours)**, for three concrete reasons:
1. **Point-in-time fundamentals** must be reconstructed per as-of date (fetch the *specific*
   10-K filed before that date, not the latest). edgartools supports this, but it is
   147 tickers × 7 years × filing-history pagination against EDGAR's ~10 req/s limit —
   long, and rate-limit-fragile.
2. **The full DCF+comps engine as-of is not trivially reproducible.** `calculator.py`
   needs FY1 EBITDA projections, **peer EV/EBITDA multiples**, and consensus — and
   **historical peer multiples are themselves unavailable** (same snapshot problem as
   Study A). A fully faithful "engine as-of" would require rebuilding the peer-multiple
   history. This script therefore computes a **transparent implied-upside proxy** (comps
   EV/EBITDA at a fixed, documented multiple applied to point-in-time EBITDA, equity
   bridge via point-in-time debt/cash/shares) and labels it as a proxy — it is directional,
   not the exact engine number. The design memo flags this so results are not over-read.
3. **The KNOWN_BUGS extraction class contaminates inputs** (BUG-002/004/006) — which is
   itself part of what step 4 measures, but it means raw runs need the invariant filter.

`pt_calibration_study.py` implements the methodology and is **runnable on a subset**
(`--tickers`, `--years`) as a proof of correctness. The full 147×7 run should be executed
on the droplet with EDGAR identity set and generous rate-limit pauses; budget several
hours and expect a non-trivial NO_DATA fraction (thin XBRL history pre-2018 for some names).

## Decision frame (pre-committed)
- If the **STRONG_BUY-band forward excess ≤ 0 after costs** (with the invariant-flagged
  rows removed), then **the entry gate is unvalidated** and the observation window
  (`docs/OBSERVATION_PROTOCOL.md`, Cohort-1) is the **only remaining evidence path** — the
  paper book must not treat STRONG_BUY as established alpha.
- Report rank IC and monotonicity alongside; a positive band mean with near-zero IC is
  weak support at best.

## Outputs
- This design memo; `pt_calibration_study.py` (runnable subset + full-run flags).
- On execution: `pt_calibration_results.csv` (one row per ticker-as-of-date: implied
  upside, decile, fwd 12m excess net, invariant flags) + a 2-page findings memo with the
  decision recommendation (to be written from the droplet run).

**Status:** designed + script delivered; **full run deferred to the droplet** (gated as
above). A small proof-of-concept subset can be run here to validate the pipeline.
