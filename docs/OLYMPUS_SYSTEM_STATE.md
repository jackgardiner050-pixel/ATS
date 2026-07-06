# Olympus — System State (System of Record)

**Snapshot date:** 2026-07-06 · **Baseline:** `main` @ `73be0ab` · **Method:** re-derived from the live repo (code, config, data, tests), not from the prior snapshot's claims.

> **This is a dated snapshot and will drift.** This is a **regeneration** of the earlier `4118fde` snapshot, taken after merging the registry-discipline machinery (F7a/F7b/F5/F7d), this document, and the pt-calibration findings memo — all now on `main`. Every number here is "as of 2026-07-06 on `main` @ `73be0ab`." **Refresh cadence: regenerate after every merge to `main` that touches a subsystem heading below, and otherwise at least monthly.** Where this doc and the code ever disagree, the code wins — regenerate.

---

## What this system is, in one paragraph (as of today)

Olympus is a **paper-only, human-gated equity research-and-simulation system**: a fundamentals rating engine (DCF + comparables → price target → expected-return band → `STRONG_BUY…STRONG_SELL` + a confidence tier) screens a **147-ticker large-cap universe** on an adaptive cadence, and a simulated paper book opens/closes positions under a **hash-locked, pre-registered ruleset** whose behaviour is frozen and CI-guarded. Around that core sit three governance frameworks built to stop the operator's documented failure mode (over-iterating on under-powered results): a **protocol lock** over the ruleset files; a **hypothesis registry** with multiple-testing correction whose denominator now counts only tests actually initiated (TESTING+), requires a plain-language `interpretation_contract` on every entry, and declares a deliberate Bonferroni-AND-deflated-Sharpe double-gate; and a **sleeve contract layer** that generalises the single cohort into named, hypothesis-gated strategy sleeves (only `oracle_v1` — the existing book — exists so far). **Phaethon** is a separate, isolated LLM idea-generation experiment (two paper arms) with its own governance and a boundary-only learning mechanism. There is **no live-trading code** — a constitutional guard test fails the build if any broker library is imported. Much of the "pantheon" (Zeus, Hermes, Themis, etc.) is **dashboard labelling, not code**; only Oracle and Phaethon have backing implementations in this repo.

---

## 1. Architecture map (what actually exists in code)

### 1.1 The rating + paper-book core (the real engine)
| Component | File(s) | What it actually does |
|---|---|---|
| Valuation/rating engine | `src/engine/calculator.py` | `compute_dcf_price`, `compute_comps_price`, `compute_price_target`, `classify_rating` (expected-return → `STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL`), `assess_confidence`/`_v2`. |
| Financial model | `src/agents/model.py`, `src/agents/valuation.py` | Projects financials, builds the model, writes valuation sheets. |
| Data/extraction | `src/data/edgar_client.py`, `extraction_invariants.py`, `peer_multiples.py` | Point-in-time EDGAR fetch, post-extraction sanity checks, peer comparables. |
| Signals | `src/signals/momentum.py`, `revisions.py`, `escalation.py` | Momentum quintiles (observation-only — neutralized), EPS-revision direction, confidence-escalation/rescreen logic. |
| Universe | `src/universe/` | `admission.py` (market-cap gate) + `universe_classifier/governor`, `economic_behavior_engine`, `candidate_diversifier_engine`, `universe_balance_audit` (taxonomy/balance analytics). |
| Paper book | `src/paper_trading.py` (**LOCKED**) | `should_enter`/`should_exit`, `evaluate_exit_v2`, `open_position`/`close_position` (cost model + total-return fields), `process_screener_results`, cohort tagging, forced-sunset. |
| NAV / portfolio | `src/portfolio/` | `nav_ledger.py` (snapshots, unit math, per-cohort performance) + `exposure_engine`, `factor_engine`, `portfolio_stress`, `survivability_engine`. |
| Cadence | `src/cadence.py` | Adaptive re-screen scheduling by rating/confidence/earnings proximity. |
| Governance ("council") | `src/governance/` | `constitution.py`, `concentration_governor.py`, `dcf_skeptic.py`, `exposure.py`, `regime.py`, `calibration.py`, `signal_tracker.py`, `adversarial.py` (LLM review), `attribution_log.py`, `dashboard.py`. |
| Orchestration | `src/orchestrator.py`; `scripts/run_universe.py` → `scripts/paper_run.py` | Screen the universe → `runs/_screen/<latest>/summary.json` → apply entry/exit to the paper book. |

### 1.2 The framework layer
- **Sleeve contract layer** — `config/sleeves/_schema.yaml`, `config/sleeves/oracle_v1.yaml` (the only sleeve, stage **S1**), `src/sleeves/manifest.py` (hard loader), `base.py` (`Sleeve` ABC + `OrderIntentDraft`), `cohort.py` (generalized cohort validator, `cohort_1 → oracle_v1_c1` alias).
- **Hypothesis registry** — `src/research/registry.py` (append-only content-hash chain + the F7a/F5/F7d machinery: `correction_m`, `add_migration`, `queue`, `interpretation_contract` enforcement), `src/research/corrections.py` (Bonferroni + deflated Sharpe), `research/registry.yaml` (entries 001–003 + a `migrations` block), `research/README.md` (F7b double-gate declaration), `scripts/registry.py` (CLI: `new`/`status`/`stats`/`queue`). See §4.
- **Phaethon** (distinct parallel system) — `src/phaethon/` (11 modules): the publish path (`scorecard`, `governance`, `ledger`, `publish` → `docs/data/phaethon_*.json`) and the boundary-only learning mechanism (`journal`, `review_trigger`, `lessons_ledger`, `prediction_resolution`, `learning_kill_switch`, `schema`) — built, **no data yet**.

### 1.3 Pantheon names — code vs. label (verified by grep)
Only **Oracle** (the paper book: `src/paper_trading.py` + `config/sleeves/oracle_v1.yaml`) and **Phaethon** (`src/phaethon/`) have backing code. All others are **display labels** on the dashboard (`docs/index.html`, `scripts/_olympus.py`) with **no `src/` code here** — Zeus, Hermes, Themis, Mnemosyne (function exists as `src/governance/attribution_log.py`, not named that), Demeter (valuation code exists, not named that), Apollo/SCAI, Hades, Kairos, Hephaestus/Chronos/Artemis, Iris/ESE — several of whose real engines live in a `labs/` tree **not present in this repo** (§7). **Phobos** appears only in `pantheon_naming_map.md`.

---

## 2. Governance / lock inventory (single reference table)

| Guard | Mechanism / file | Protects | Re-registration / bypass |
|---|---|---|---|
| **Protocol lock** | `config/protocol_lock.yaml` (`locked`, `registered: 2026-07-05`, `protocol_sha`, `ruleset_sha`) + `scripts/verify_protocol_lock.py`. **Status: PASS.** | 7 ruleset files: `src/paper_trading.py`, `src/engine/calculator.py`, `src/signals/{momentum,revisions}.py`, `config/{constitution,settings,universe}.yaml`; `protocol_sha` also covers `docs/OBSERVATION_PROTOCOL.md`. | `verify_protocol_lock.py --register` (deliberate) + log the reason in `docs/PROTOCOL_CHANGELOG.md` (**9 entries**). A `lock_sha` mismatch halts the screen. |
| **Constitution booleans** | `config/constitution.yaml` + `test_constitution_hard_booleans_all_true` | `NO_LEVERAGE`, `NO_REAL_ORDERS`, `NO_LIVE_PNL_LEARNING`, `human_gated` (+ `MAX_SINGLE_POSITION: 0.10`, `MIN_OBSERVATIONS_FOR_CALIBRATION: 20`). | Edit yaml → CI fails unless the guard is updated deliberately. |
| **No broker libraries** | `test_no_broker_library_imports`, `…_in_requirements`, `test_swingbot_place_real_order_raises` | Whole repo — no broker import may exist. | None (hard bright line). |
| **Research/trading ringfence** | `test_swingbot_and_agent_are_ringfenced`, `test_no_feedback_imports.py` | Agent and swing-bot code cannot import each other. | None. |
| **Phaethon isolation** | `test_phaethon_does_not_import_engine_or_signals`, `…_no_live_pnl_read_in_prompt_paths` | `src/phaethon/` can't reach the engine/signals or read a live-P&L artifact. | None (NO_LIVE_PNL_LEARNING). |
| **Phaethon learning firewall** | `test_learning_modules_unreachable_from_phaethon_facing_code`, `…_write_only_human_side` | Learning modules unreachable from any Phaethon-facing code; write only human-side paths. | None. |
| **Deploy droplet guard** | `test_deploy_sh_has_both_trading_guards` + `scripts/deploy.sh` | Deploy refuses unless host/hostname contain "trading". | Edit deliberately. |
| **Sleeve admission (Themis)** | `src/sleeves/manifest.py` + `tests/test_registry_discipline.py` | Manifest missing `registry_ref`/`kill_criteria` fails to load; stage ≥ S2 must reference a **PASSED** registry entry. | N/A. |
| **Registry content chain** | `src/research/registry.py::verify_registry_chain` + `verify_migration_chain` | Immutable hypothesis fields (editing one breaks the chain); the `SCHEMA_MIGRATION` backfill is itself an append-only hash chain. | Append-only; status advances forward-only. |
| **Registry admission (F5)** | `add_entry` + `tests/test_registry_machinery.py` | Every new entry must carry `interpretation_contract {licenses, does_not_license}` or fails to load. | None. |

**Cohort-scoped ruleset behaviour inside locked `src/paper_trading.py`:** `exit_rules_v2` is **ACTIVE** (`config/settings.yaml: exit_rules_v2: true`), confined to `cohort_1` only; the Legacy Cohort is exempt (RATING_DOWNGRADE-only) until its **forced sunset on `LEGACY_SUNSET_DATE = 2026-08-23`**. Frozen v2 params: `pt_fraction=1.0, max_hold_days=270, stale_days=28`.

---

## 3. Cohort & evidence-state ledger (actual numbers from the data files)

| Cohort / arm | Source | Actual state today |
|---|---|---|
| **Legacy Cohort** | `data/paper_positions.yaml` | **12 positions**, all `legacy_pre_fix`, opened **2026-05-25**. No gates — runs only its **forced sunset on 2026-08-23**. |
| **Cohort-1 / `oracle_v1`** | positions/trades, `protocol_lock.yaml`, `config/sleeves/oracle_v1.yaml` | **0 positions, 0 closed trades** (`data/paper_trades.jsonl` absent). Lock `registered: 2026-07-05`. Sleeve stage **S1** (downgraded from S2 on 2026-07-05), `registry_ref: "003"`, benchmark SPY_TR, 4 kill_criteria (verbatim from §5). Still empty — see §6(c). |
| **Phaethon Arm A (disciplined)** | `docs/data/phaethon_live.json` | **18 positions, 62.0% cash, gross 38.0% — CONFORMING.** `restated 2026-07-05`. |
| **Phaethon Arm B (aggressive)** | `docs/data/phaethon_b_live.json` | **11 positions, 5.1% cash, gross 94.8% — NONCONFORMING** (3 flags: CEG 13.5%, GOOGL 13.8%, AMZN 10.6% > 10%). Leverage bug fixed; live-candidate-vs-falsification-control question **open** (`docs/PHAETHON_ARM_B_LEDGER_MEMO.md`). |
| **Registry hypotheses** | `research/registry.yaml` | 001 FAILED, 002 FAILED, 003 TESTING — all now carry an `interpretation_contract` (§4). |

> **Not verifiable from the repo alone:** droplet-side state, cron status, live tmux sessions. Not asserted here. (The pt-calibration proxy run *has* completed — its result is committed in `research/revisions_pt_validation/FINDINGS_pt_calibration.md`; see §4.)

---

## 4. Registry status (real `scripts/registry.py stats` output on `main`)

`scripts/registry.py stats` on `main` @ `73be0ab` prints:
```
m (correction denominator, TESTING+)     : 3
total entries registered (informational) : 3
Bonferroni alpha                         : 0.016666666666666666
pass rate (resolved)                     : 0.00% (0/2)
```
| id | status | hypothesis (abbrev.) | result_ref |
|---|---|---|---|
| **001** | FAILED | 12-1 cross-sectional momentum, Q1−Q5 net spread, NW t≥2 | `research/momentum_validation/MEMO_momentum.md` |
| **002** | FAILED | Post-earnings-announcement drift (PEAD/Kairos) | `swing-bot/backtest/PEAD_RESULTS.md` |
| **003** | TESTING | Oracle/Cohort-1: STRONG_BUY-gated entries beat SPY TR net of costs (§5 gate) | `docs/OBSERVATION_PROTOCOL.md` (no result — window mid-flight) |

**Machinery now live on `main` (F7a/F7b/F5/F7d — no longer pending):**
- **F7a — denominator = TESTING+ only.** `m` counts only entries at TESTING/FAILED/PASSED/RETIRED; REGISTERED (Stage-0) is free. Today `m = 3` (all three are TESTING+), Bonferroni `alpha = 0.05/3 ≈ 0.0167`.
- **F7b — declared double-gate.** `research/README.md` states candidates must clear **both** Bonferroni significance **and** the deflated Sharpe — a deliberate high-false-negative-rate choice.
- **F5 — `interpretation_contract` required.** Every entry declares `{licenses, does_not_license}`; new entries hard-fail without it. Entries 001–003 were backfilled via an appended, hash-chained **`SCHEMA_MIGRATION`** event (overlaid at read time) — their records and content-hashes are unchanged (append-only preserved; both chains verify).
- **F7d — `queue`.** `registry.py queue` ranks REGISTERED entries by `survival_prior × strategic_fit`; informational only. (No REGISTERED entries exist today, so the queue is empty.)

**Proxy PT-calibration study (result committed):** `research/revisions_pt_validation/FINDINGS_pt_calibration.md` reports a full run (711 OK ticker-years): rank IC **+0.136 (all) / +0.097 (ex-flagged)** — significant but **below the §5 Spearman ≥ 0.30 bar**; STRONG_BUY-band median **≈ 0 (−0.3%)** on the clean subset (the +9.4% mean is skew-driven). Conclusion: weak/fragile/proxy-level positive, **entry gate remains unvalidated at the required standard**. **This is a fixed-multiple proxy and does NOT resolve entry 003** — Cohort-1's live window remains the primary evidence path.

---

## 5. Data flow — one trade/decision, end to end (actual code path)

1. **Universe admission** — `config/universe.yaml` (147 tickers) filtered by `src/universe/admission.py::check_market_cap_admission`.
2. **Rating/signal** — `scripts/run_universe.py`: `src/engine/calculator.py` computes DCF + comps → `compute_price_target` → expected return → `classify_rating` + `assess_confidence_v2`; signals + governance council inform. Output → **`runs/_screen/<latest>/summary.json`**.
3. **Entry** — `scripts/paper_run.py` → `process_screener_results`. `should_enter` = `STRONG_BUY` AND confidence ∈ {MED, HIGH}. New positions → `open_position(cohort="cohort_1")`.
4. **Position record** — `data/paper_positions.yaml`, schema- + cohort-validated (`_validate_cohort` accepts only `legacy_pre_fix`/`cohort_1`).
5. **Exit** — with `exit_rules_v2: true`: for `cohort_1`, `evaluate_exit_v2` (precedence `RATING_DOWNGRADE > PT_HIT > TIME_STOP > STALE`); legacy excluded until the `2026-08-23` `FORCED_SUNSET` pass.
6. **Close** — `close_position` → `data/paper_trades.jsonl` (immutable) with gross/net + dividend-adjusted total-return fields and alpha vs SPY (cost `paper_cost_bps: 20`/side).
7. **NAV / attribution** — `src/portfolio/nav_ledger.py` (`compute_units` with `paper_nav_start=100000`, `n_target_positions=20`; `compute_performance` per cohort); `paper_run.py` writes an attribution snapshot.

**Divergence in the flow:** `n_target_positions = 20` is the sizing denominator, but no live cohort holds 20 (Legacy 12, Cohort-1 0). Phaethon has an **entirely separate** publish path (`src/phaethon/publish.py` → `docs/data/phaethon_*.json`) — it does **not** flow through `paper_trading.py`.

---

## 6. Known gaps & deferred items

### (a) Deliberately deferred (with pointer)
- **Live trading:** none — paper-only by constitutional design (`NO_REAL_ORDERS`, broker-import guard). No broker/IBKR/Alpaca code exists.
- **Phaethon Arm B disposition:** live candidate vs falsification control — deferred to the operator (`docs/PHAETHON_ARM_B_LEDGER_MEMO.md`).
- **Real-engine PT study:** `FINDINGS_pt_calibration.md §6` notes (does not prescribe) a possible Stage-1 study using the actual engine's price targets rather than the EV/EBITDA proxy — an open operator decision, deliberately not registered.
- **Second sleeve:** the framework supports many; only the `oracle_v1` retrofit exists.

### (b) Genuinely unknown / undecided
- **Droplet/cron/tmux state** (the Phaethon publisher cron, droplet health) — not derivable from the repo. *(The pt-calibration `ptcal2` run has completed — result in the FINDINGS memo — so it is no longer unknown.)*
- Whether Cohort-1 "inception" is the lock-registration date (2026-07-05) or the first-position date — no `cohort_1` position exists yet (6c).

### (c) Gaps I found that nobody appears to have flagged — surfaced prominently
1. **Cohort-1 is armed but empty.** Lock `registered: 2026-07-05`, `exit_rules_v2` ACTIVE "for Cohort-1", yet **0 `cohort_1` positions, 0 closed trades**. The only screens on disk (`runs/_screen/`) are from **2026-05-26** — *before* the lock registration — so **no screen has run under the locked ruleset**. The 52-week evidence clock is registered against an empty book; exit-rules-v2 currently governs zero positions. **(Unchanged since the last snapshot.)**
2. **The Phaethon learning mechanism has never run on data.** `data/phaethon/` and `runs/phaethon/` are **empty** — no journal, lessons ledger, review artifact, or `LEARNING_SUSPENDED`. Fully built and unit-tested, **zero real-world exercise**.
3. **BUG-003 is OPEN** (`KNOWN_BUGS.md`): LMT/MA price target floored to $0, confidence=BROKEN.
4. **Pre-existing test failures:** the suite is **861 passed / 6 failed** (58 files). The 6 failures are all `tests/test_dashboard_live.py` (position-id assertions vs a newer `docs/index.html`). Long-standing; not from recent work.
5. **Untracked "system" docs:** several status/design docs a reader would treat as canonical are **not in git** (untracked) — see §7.

> *Resolved since the last snapshot:* the earlier gap "`main`'s registry lacks the discipline fixes" — F7a/F7b/F5/F7d are now merged and live (§4).

---

## 7. Document / reality divergences (actively hunted — this class of error recurs here)

Source files for divergences #1–#14 were confirmed **unchanged** by the three merges since `4118fde`, so each still holds verbatim.

| # | Divergence | Doc claim (source) | Repo reality (source) |
|---|---|---|---|
| 1 | **Universe size** | 61 (`SYSTEM_AUDIT_2026-05-25.md:323`); "now 60 names" (`KNOWN_BUGS.md:42`) | **147** (`config/universe.yaml`; matches `docs/environment_snapshot.md:16`). |
| 2 | **Prior-review docs predate the architecture** | `olympus_system_review.md` (2026-05-29), `SYSTEM_AUDIT_2026-05-25.md`, `OLYMPUS_STATUS_BRIEFING_2026-06-16.md`, `NEXT_STEPS.md` (2026-06-05) | They mention **0** sleeves/registry/exit_rules_v2 — the whole framework layer landed 2026-07-05, after all of them. |
| 3 | **`labs/` engines referenced but absent** | Dashboard/naming map present Hermes/Apollo/Iris as members | Their code tree `labs/` is **not in this repo**; in-repo they are labels only. |
| 4 | **`Phobos` implies a built member** | `pantheon_naming_map.md` | **Zero** code/dashboard/config hits. Naming-map-only. |
| 5 | **`data/paper_trades.jsonl` documented but absent** | `README.md:59`, `src/paper_trading.py:11,29` call it the immutable trades log/output | File **does not exist** — 0 closed trades, never written. |
| 6 | **`exit_rules_v2` comment vs value/code** | `config/settings.yaml:36–40` comment: "DEFAULT OFF — must stay false" | Value is **`true`**; params are "calibrated…frozen"; `test_cohort1_exit_rules_active.py` asserts it must be True. Comment is stale. |
| 7 | **`environment_snapshot.md` overstates deps** | pins `matplotlib`/`numpy`/`python-dateutil` (lines 26–29) | `requirements.txt:48–52` drops them as "not imported"; grep confirms no import. |
| 8 | **Dangling config key** | `config/settings.yaml:54` `corpus_file: "corpus.jsonl"` | No corpus module/file exists (README: corpus "planned/not built"). |
| 9 | **`STATUS.txt` inconsistent + stale** | ":2–3 6 tickers screened … SB=17 B=3 H=12 S=8 SS=20" | Distribution sums to **60**, impossible from 6 tickers; dated 2026-05-25, never refreshed, predates the 147 universe. |
| 10 | **Briefing cites an absent tool** | `OLYMPUS_STATUS_BRIEFING` cites `safe_deploy.sh`; "suite green (87/0)" | No `safe_deploy*` in repo (only `scripts/deploy.sh`); suite is **58 files / 861 passed, 6 failed**. |
| 11 | **`INFRA_INVENTORY.md` lists absent scripts** | `scripts/price_updater.sh`, `run_hermes_*.sh`, `universe_check.py`, … | None exist under this repo's `scripts/` (droplet-side; also untracked — see #12). |
| 12 | **Untracked docs treated as canonical** | `NEXT_STEPS.md`, `OLYMPUS_STATUS_BRIEFING_2026-06-16.md`, `INFRA_INVENTORY.md`, `NAME_MAP.md`, `Olympus_Build_Prompt_v1.2.md`, … | All **untracked** (`git status` `??`) — on disk, not in the repo of record. |
| 13 | **Book size** | `n_target_positions: 20` (`config/portfolio.yaml`) | No live cohort holds 20 (Legacy 12, Cohort-1 0, Phaethon A 18 / B 11). Target ≠ actual. |
| 14 | **`oracle_v1` stage history** | An earlier state had it at S2 | Now **S1** (deliberate 2026-07-05 downgrade — hypothesis 003 is TESTING, not PASSED). |
| 15 | **Stale/leftover branches** | (git housekeeping) | After pruning merged branches, 4 locals remain — `activate-exit-rules-v2`, `constitutional-exception-log` (content in `main`; `-d` refuses vs their remote refs) and `exit-v2-cohort-guard`, `legacy-forced-sunset` (stale pre-rebase refs; content in `main`). None represent unmerged work. |

**Superseded:** the previous `OLYMPUS_SYSTEM_STATE.md` (the `4118fde` version, now in git history) flagged `registry-machinery-fixes` as *unmerged/pending* — **that caveat is void**; the machinery is live (§4). This regeneration replaces it.

**Confirmed clean:** `config/universe.yaml` "147" matches the count; README rating bands match `config/settings.yaml`; `docs/LIVE_RUNBOOK.md` paths exist; `pantheon_naming_map.md`'s only in-repo build claim (Phaethon governance) is accurate; the 003/oracle_v1 reconciliation and the registry chains are internally consistent. `MEMO_momentum.md` already flags the "60→147" staleness (#1).

---

*Generated 2026-07-06 from `main` @ `73be0ab` (regeneration of the `4118fde` snapshot). Regenerate after the next subsystem-touching merge (or monthly). Refresh commands: `python scripts/registry.py stats`; `python scripts/verify_protocol_lock.py`; count `data/paper_positions.yaml` by cohort; read `docs/data/phaethon_*.json`; `ls runs/_screen/`; `git branch` state.*
