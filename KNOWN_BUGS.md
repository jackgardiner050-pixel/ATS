# Known Bugs

Issues surfaced during the 2026-05-25 universe expansion run. All are calibration-class
bugs; none affect order placement (there is none) or hard rule compliance.

---

## BUG-001: SUM (Summit Materials) — delisted
**Status:** FIXED — removed from universe.yaml and peer_groups.yaml  
**Symptom:** `CompanyNotFoundError: Company not found: 'SUM'` at EDGAR fetch stage.  
**Root cause:** Summit Materials (SUM) was acquired by Quikrete Holdings in 2024 and delisted. The ticker no longer exists on any exchange.  
**Fix applied:** Removed SUM from `config/universe.yaml` and `config/peer_groups.yaml`. Universe is now 60 names.

---

## BUG-002: AVAV — astronomical price target (~$148M/share)
**Status:** FIXED — lowered unit-conversion threshold in `src/agents/model.py`  
**Symptom:** AVAV price target reported as ~$148,000,000/share vs ~$174 current price.  
**Root cause:** `build_model` converts projected values from dollars to $mm only when `fy1_revenue > 1e9`. AVAV's base revenue is ~$820M; after 18% FY+1 growth the projected revenue is ~$968M — just below $1B — so the conversion never fires. Balance-sheet cash/debt ARE always divided by 1e6, creating a unit mismatch: UFCF stream in dollars, diluted shares in millions → price per share inflated by 1e6.  
**Fix applied:** Changed threshold from `> 1e9` to `> 1e6` in `src/agents/model.py`. This covers all real companies in the universe (none have < $1M revenue).

---

## BUG-003: LMT, MA — price target floored to $0, confidence=BROKEN
**Status:** OPEN — pre-existing calibration issue; Path B addresses root cause  
**Symptom:** LMT and MA (and likely other large-cap, high-debt names) produce a negative blended price target before the BUG-003 floor in `src/engine/calculator.py` clamps it to zero.  
**Root cause:** The DCF + comps blend assumes peer multiples calibrated to the EPC/industrial sector. For financial-services (MA) and large-cap defense (LMT) with significant net debt, the equity bridge (`EV - net_debt / shares`) can produce negative equity even with reasonable multiples, because the peer EV/EBITDA multiple applied to FY+1 EBITDA underestimates the true enterprise value for asset-light or mega-cap names.  
**Workaround:** The `assess_confidence` function returns `BROKEN` for PT ≤ 0, suppressing the rating from being actionable. The floor in `build_fixed_numbers` prevents negative PTs surfacing in output.  
**Proper fix:** Per-sector multiple calibration (Path B). Until then, treat BROKEN outputs as "model not applicable to this name" — human review required before any action.

---

---

## BUG-004: HON-class projection bug — gross_profit=None for conglomerates
**Status:** FIXED — expanded LABEL_MAP_IS and added computed fallback in `src/data/edgar_client.py`  
**Symptom:** HON (and similar diversified industrials) projected FY1 EBITDA ~$5.1B vs actual TTM ~$8.5B — a ~67% underestimate. Rating and PT were materially wrong.  
**Root cause:** EDGAR XBRL extraction for `gross_profit` and `operating_income` returned `None` for HON. HON reports cost lines as "Cost of products sold" and "Cost of services sold" rather than the standard `us-gaap_GrossProfit` concept. With no gross profit history, `base_gm` fell back to 0.25 (25%) instead of HON's actual ~37%.  
**Fix applied:** (1) Expanded `cost_of_revenue` label map to include HON-specific labels ("Cost of products sold", "Cost of products and services sold", etc.) and additional XBRL concepts. (2) Added computed fallback in `extract_historical_metrics`: when `gross_profit` is None but `revenue` and `cost_of_revenue` are both extracted, derive `gross_profit = revenue - cost_of_revenue`. Similarly derives `operating_income = gross_profit - sga` when direct label absent.  
**Verified:** GE, ITW, EMR all extract correctly with EBITDA proxies within 10% of yfinance; HON now shows GM ~37% across 2023–2025 FY data.

---

## BUG-005: LLY-class cohort outlier — peer multiples not representative
**Status:** FIXED — cohort outlier detection added in `src/orchestrator.py`, `src/engine/calculator.py`, `src/agents/valuation.py`  
**Symptom:** LLY (and similarly high-premium names) received MED or HIGH confidence despite trading at EV/EBITDA far above its pharma peers. The comps-implied PT was wildly low because peer EV/EBITDA multiples (~13×) are not applicable to LLY's growth profile (~60×+).  
**Root cause:** No mechanism to detect when the target's own trading multiple is an outlier vs its assigned peer cohort.  
**Fix applied:** Orchestrator fetches target's EV/EBITDA via yfinance. If `target_ev_ebitda > 1.5 × peer_median_ev_ebitda`, `cohort_outlier=True` is set. `build_fixed_numbers` then appends `"target_ev_ebitda_2x_peer_median"` to `confidence_flags` and caps confidence at LOW. Rating is unchanged.

---

## BUG-006: Health insurer gross_profit inflation — UNH/HUM/CI/ELV/CVS-class
**Status:** FIXED — high-gross-margin guard added in `src/data/edgar_client.py`  
**Symptom:** UNH price target computed as ~$4583/share (1080% implied return) vs ~$290 actual. Similar inflation expected for HUM, CI, ELV, CVS.  
**Root cause:** Health insurers report "Medical costs" (~$314B for UNH) under `us-gaap_PolicyholderBenefitsAndClaimsIncurredNet`, not under standard COGS concepts. The `cost_of_revenue` label map only captured "Cost of products sold" (~$51B — pharmacy segment only). The HON-class computed fallback then computed `gross_profit = revenue - cost_of_revenue = $447B - $51B = $396B` (88.7% gross margin), producing a wildly overstated EBITDA and PT.  
**Fix applied:** Two-part: (1) Added `medical_costs` field to `LABEL_MAP_IS` with XBRL concepts `us-gaap_PolicyholderBenefitsAndClaimsIncurredNet`, `us-gaap_HealthCareCosts`, etc. (2) Added high-gross-margin guard in `extract_historical_metrics`: when `gross_profit / revenue > 0.70` AND `operating_income` and `sga` are both available, back-compute `gross_profit = operating_income + abs(sga)`. This ensures `EBIT = gross_profit - sga = operating_income` regardless of which revenue figure EDGAR returns.  
**Note:** Subtracting `medical_costs` directly from `gross_profit` was attempted first but caused negative EBITDA because `standard_concept="Revenue"` picks up "Premiums" ($352B) before "Total revenues" ($447B), and $352B - $314B (medical) - $51B (products) = -$13B. The back-compute guard avoids this ambiguity entirely.  
**Verified:** UNH fy1_ebitda=$25.9B (actual ~$23B), PT=$293 (SELL). No crashes on SYK, EW, COR.

---

## BUG-007: run_pipeline.py always bypasses live peer fetch
**Status:** FIXED — `scripts/run_pipeline.py` defaults changed to `None`  
**Symptom:** All tickers run via `python3 scripts/run_pipeline.py TICKER` showed `no_peers_resolved` in `confidence_flags` even when peers are defined in `peer_groups.yaml` and yfinance returns valid data. Exit multiple always defaulted to 12.0x instead of using the peer-derived value.  
**Root cause:** `run_pipeline.py` built a `peer_multiples` dict from argparse defaults (14.0, 20.0, 25.0) and passed it to `run_pipeline()`. In `orchestrator.py`, the peer-fetch block is guarded by `if peer_multiples is None:` — so when the dict was passed with defaults, the yfinance fetch was skipped and `n_peers_resolved` stayed at 0.  
**Fix applied:** Changed `--peer-ev-ebitda-median/p75/pe` defaults to `None`. `peer_multiples` is now set to `None` unless the user explicitly passes `--peer-ev-ebitda-median`. The orchestrator then auto-resolves peers via yfinance as intended.  
**Note:** `run_universe.py` was unaffected — it calls `run_pipeline()` without `peer_multiples`, so it always fetched live peer data.

---

*Bugs are documented here only when the root cause is non-obvious or the fix is deferred.
Bugs fixed in the same session as discovery do not require a permanent entry after resolution.*
