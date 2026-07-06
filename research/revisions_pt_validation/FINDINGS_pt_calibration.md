# PT-Calibration Proxy Study — Findings

**Date:** 2026-07-06 · **Data:** `pt_calibration_results.csv` (full run: 1029 ticker-years, **711 OK**, 311 NO_UPSIDE, 7 NO_DATA) · **Nature:** exploratory proxy study, not a registered Stage-1 test.

> **The one sentence that matters most:** on the invariant-clean subset, the median STRONG_BUY-band forward excess is **approximately zero (−0.3%)** — the flattering **+9.4% mean is carried by a small number of large winners**, not by the typical name. Read the median, not the mean.

---

## 1. Headline: rank IC is positive and significant, but below the pre-declared bar

Spearman rank correlation between implied upside (proxy) and forward 12-month excess return (net of costs):

| Subset | rank IC | p | n |
|---|---|---|---|
| ALL | **+0.136** | 0.0003 | 711 |
| EX-FLAGGED (invariant-clean) | **+0.097** | 0.019 | 591 |

Both are positive and statistically significant. **Both are well below the §5 pre-declared success bar of Spearman ≥ 0.30.** Stated plainly: **the proxy PT-calibration does NOT clear the pre-registered gate.** The ordering carries *some* information, but not at the standard this system committed to in advance.

## 2. STRONG_BUY-band forward excess — median first, because the mean misleads

| Subset | **median** | mean | n |
|---|---|---|---|
| ALL | +5.3% | +22.7% | 78 |
| EX-FLAGGED (clean) | **−0.3%** | +9.4% | 45 |

**Lead finding:** on the invariant-clean subset the **typical (median) STRONG_BUY-band outcome is essentially zero (−0.3%)**. The headline mean (+9.4%, and +22.7% before cleaning) is **carried by a small number of large winners** in a right-skewed distribution — it is not the experience of the typical name that clears the gate. The invariant flags were doing real work: removing flagged rows cuts the mean from **+22.7% → +9.4%** and drops the median from +5.3% to ≈0. Any read of this band as a "+22.7% edge" is a mean-chasing artifact.

## 3. Decile monotonicity — noisy, not a clean ranking

Mean forward excess by implied-upside decile (ex-flagged) is **non-monotonic**: the deepest-negative-upside decile is anomalously positive, the middle deciles are mixed/negative, and the informative signal is **concentrated in D7–D8** (≈ +19% / +15%) rather than rising cleanly with upside; D9–D10 fade back toward the middle. A positive rank IC therefore coexists with an ordering that is **not a reliable ranking tool** — even where the correlation is positive, the decile structure does not support using the proxy score as a dependable sort.

## 4. Caveats (stated, not softened)

**(a) This is a fixed EV/EBITDA = 10 proxy, NOT the live rating engine's price targets.** Implied upside here is a stand-in comps multiple applied uniformly, not what `src/engine/calculator.py` actually produces (DCF + comps + confidence). **The finding characterizes the proxy, not Oracle/Cohort-1 directly.** The real engine may order names differently.

**(b) This result is separate from, and does not resolve, registry entry 003.** Entry 003 (the Oracle/Cohort-1 live observation window) remains **TESTING on its own forward evidence**. This backtest proxy neither passes nor fails it; the two are different experiments on different inputs.

## 5. Decision-frame conclusion (per the pre-committed frame)

The STRONG_BUY gate's forward excess is **not cleanly ≤ 0** — there is a small positive signal via the rank IC (+0.10 to +0.14, significant). But it is **also not robustly positive at the pre-declared bar**: rank IC is below 0.30, the STRONG_BUY-band median is ≈0 on the clean subset, the mean is skew-driven, and the decile ordering is noisy.

**Honest conclusion: a weak, fragile, proxy-level positive signal. The entry gate remains UNVALIDATED at the standard this system requires. Cohort-1's own live observation window remains the primary evidence path — not this study.**

## 6. Recommendation (a note, not a registry action)

This proxy result is **marginally interesting but not compelling** — enough of a positive rank IC to not dismiss, not enough to claim the gate works. The obvious next question is whether the **real rating engine's price targets** (not a fixed-multiple stand-in) would calibrate better or worse: a fixed EV/EBITDA=10 both mutes real dispersion and can manufacture spurious ordering, so the true engine could plausibly clear or miss the bar by a wider margin than this proxy suggests.

**Note (not a decision):** if the operator wants to pursue this, the defensible next step is a **Stage-1 study using the actual engine's price targets** — pre-registered in the hypothesis registry with its own analysis plan and success threshold — rather than iterating on the proxy. Whether that study is worth the cost is a separate future decision and is **not** proposed here as a registry entry.

---

*Reproduce the summary numbers: `summarize_results()` in `pt_calibration_study.py` over `pt_calibration_results.csv`. Rank-IC/median figures above are computed directly on `implied_upside` vs `fwd_excess_net`; the script's own decile-binned rank IC (+0.13 / +0.10) agrees within noise. Proxy parameters: EV/EBITDA = 10, round-trip cost 40 bps.*
