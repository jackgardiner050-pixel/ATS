# Universe Counts — Reconciliation (283 → 147)

**Document date:** 2026-09-02

---

## The three universe numbers

1. **283 tickers** — checked in Step 0 (liveness check via yfinance)
2. **147 tickers** — locked screen universe in `config/universe.yaml` (used in Steps 0b/0c screen & extraction)
3. **60 tickers** — stale reference in older documentation (pre-2026-08 drafts)

## Why three numbers? How they relate.

### Step 0: Universe liveness check (283 tickers)

**Script:** `scripts/check_universe_liveness.py`

**Input sources:**
- `config/universe.yaml` — 147 tickers (the locked screen universe)
- `config/peer_groups.yaml` — 283 total tickers (147 universe members + 136 peer cohort tickers)

**Purpose:** Before running the screen, verify that all 283 tickers (universe + peers) return a non-empty 5-day price history from yfinance. This flags delisted, renamed, or otherwise-unreachable names before the screener hits them.

**Output:** (269 live, 14 flagged suspects as of 2026-08-30; see OLYMPUS_KNOWLEDGE_BASE_DROPLET.md §3)

### Steps 0b/0c: Screen & extraction (147 tickers)

**Scripts:** `scripts/run_screen.py`, `scripts/log_eps_trend.py`

**Universe source:** `config/universe.yaml` — exactly 147 tickers. This is the **locked** screen universe per §0 of OBSERVATION_PROTOCOL.md; changes force a re-registered Cohort-2.

**Purpose:** 
- Step 0b runs the screener only on the 147 universe tickers (faster, deterministic, no peer noise)
- Step 0c logs weekly eps-trend history into `data/eps_trend_history.jsonl` for the same 147

### The 60-ticker reference (deprecated)

The OBSERVATION_PROTOCOL header (drafted 2026-07-05) reads "60-name universe." This predates the expansion to 147. The **operative** universe is `config/universe.yaml` = 147 names, and the lock's `ruleset_sha` covers that file — so the screen runs on 147 regardless of the stale prose. The header line is cosmetic drift, to be corrected on the next deliberate re-registration.

**Note:** some very early screen runs may reference 60–61 tickers if they used a different locked universe. These are now outside the current Cohort-1 window and are documented separately (Legacy Cohort, pre-fix engine).

## Summary

| Stage | Ticker count | Source | Purpose |
|-------|--------------|--------|---------|
| **Step 0** (liveness check) | 283 | universe.yaml (147) + peer_groups.yaml (283 total) | Detect delisted/broken tickers before screening |
| **Steps 0b/0c** (screen & extract) | **147** | universe.yaml (locked) | Run screen on the locked universe only; log eps trends |
| **Cohort-1** (paper book) | 147 | OBSERVATION_PROTOCOL.md lock | Locked at inception; any member-change forces Cohort-2 |

## References

- `config/universe.yaml` — The locked 147-name universe (protocol input)
- `config/peer_groups.yaml` — Union includes all 283 tickers checked in Step 0
- `scripts/check_universe_liveness.py` — Step 0 liveness check over all 283
- `scripts/run_screen.py` — Step 0b screen over 147 universe only
- `scripts/log_eps_trend.py` — Step 0c eps-trend logging for 147 universe
- `docs/OBSERVATION_PROTOCOL.md` — Cohort-1 protocol & universe lock. **Its header still reads "60-name universe" (stale).** That file is hash-locked (`protocol_sha` in `config/protocol_lock.yaml`); correcting the prose is a deliberate `--register` action with a `PROTOCOL_CHANGELOG.md` entry — deferred to the operator, NOT done in B-11. Until then, this document is the reconciled reference.
