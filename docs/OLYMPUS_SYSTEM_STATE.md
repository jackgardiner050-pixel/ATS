# Olympus — System State (System of Record)

**Snapshot date:** 2026-07-06 · **Baseline:** `main` @ `4118fde` · **Method:** re-derived from the live repo (code, config, data, tests), not from prior summaries.

> **This is a dated snapshot and will drift.** The repo moves fast (this whole framework layer landed in a single day, 2026-07-05). Treat every number here as "as of 2026-07-06 on `main` @ `4118fde`." **Recommended refresh cadence: regenerate after every merge to `main` that touches a subsystem heading below, and otherwise at least monthly.** Where this doc and the code ever disagree, the code wins — regenerate.

---

## What this system is, in one paragraph (as of today)

Olympus is a **paper-only, human-gated equity research-and-simulation system**: a fundamentals rating engine (DCF + comparables → price target → expected-return band → `STRONG_BUY…STRONG_SELL` + a confidence tier) screens a **147-ticker large-cap universe** on an adaptive cadence, and a simulated paper book opens/closes positions under a **hash-locked, pre-registered ruleset** whose behaviour is frozen and CI-guarded. Around that core sit three governance frameworks built to stop the operator's documented failure mode (over-iterating on under-powered results): a **protocol lock** over the ruleset files, a **hypothesis registry** with multiple-testing correction, and a **sleeve contract layer** that generalises the single cohort into named, hypothesis-gated strategy sleeves (only `oracle_v1` — the existing book — exists so far). **Phaethon** is a separate, isolated LLM idea-generation experiment (two paper arms) with its own governance and a boundary-only learning mechanism. There is **no live-trading code** — a constitutional guard test fails the build if any broker library is imported. Much of the "pantheon" (Zeus, Hermes, Themis, etc.) is **dashboard labelling, not code**; only Oracle and Phaethon have backing implementations in this repo.

---

## 1. Architecture map (what actually exists in code)

### 1.1 The rating + paper-book core (this is the real engine)
| Component | File(s) | What it actually does |
|---|---|---|
| Valuation/rating engine | `src/engine/calculator.py` | `compute_dcf_price`, `compute_comps_price`, `compute_price_target`, `classify_rating` (expected-return → `STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL`), `assess_confidence`/`_v2`. |
| Financial model | `src/agents/model.py`, `src/agents/valuation.py` | Projects financials, builds the model, writes valuation sheets. |
| Data/extraction | `src/data/edgar_client.py`, `extraction_invariants.py`, `peer_multiples.py` | Point-in-time EDGAR fetch, post-extraction sanity checks, peer comparables. |
| Signals | `src/signals/momentum.py`, `revisions.py`, `escalation.py` | Momentum quintiles (observation-only — neutralized), EPS-revision direction, confidence-escalation/rescreen logic. |
| Universe admission | `src/universe/admission.py` | Market-cap admission gate (`check_market_cap_admission`, `fetch_market_cap`). Plus `universe_classifier/governor`, `economic_behavior_engine`, `candidate_diversifier_engine`, `universe_balance_audit` (taxonomy/balance analytics). |
| Paper book | `src/paper_trading.py` (**LOCKED**) | `should_enter`/`should_exit`, `evaluate_exit_v2`, `open_position`/`close_position` (cost model + total-return fields), `process_screener_results`, cohort tagging, forced-sunset. |
| NAV / attribution | `src/portfolio/nav_ledger.py` (+ `exposure_engine`, `factor_engine`, `portfolio_stress`, `survivability_engine`) | NAV snapshots, unit math, per-cohort performance; portfolio-level exposure/factor/stress analytics. |
| Cadence | `src/cadence.py` | Adaptive re-screen scheduling by rating/confidence/earnings proximity. |
| Governance ("council") | `src/governance/` — `constitution.py`, `concentration_governor.py`, `dcf_skeptic.py`, `exposure.py`, `regime.py`, `calibration.py`, `signal_tracker.py`, `adversarial.py`, `attribution_log.py`, `dashboard.py` | Hard-rule enforcement, concentration checks, stress-adjusted valuation, regime classifier, calibration stats, LLM adversarial review, decision logging, terminal dashboard. |
| Orchestration | `src/orchestrator.py`; drivers `scripts/run_universe.py` → `scripts/paper_run.py` | Screen the universe → write `runs/_screen/<latest>/summary.json` → apply entry/exit to the paper book. |

### 1.2 The framework layer (all landed 2026-07-05)
- **Sleeve contract layer** — `config/sleeves/_schema.yaml` (manifest schema), `config/sleeves/oracle_v1.yaml` (the only sleeve — retrofit of the existing book), `src/sleeves/manifest.py` (hard-validating loader), `src/sleeves/base.py` (`Sleeve` ABC + `OrderIntentDraft`), `src/sleeves/cohort.py` (generalized cohort validator, `cohort_1 → oracle_v1_c1` alias).
- **Hypothesis registry** — `src/research/registry.py` (append-only, content-hash-chained ledger), `src/research/corrections.py` (Bonferroni + deflated Sharpe), `research/registry.yaml` (entries 001–003), `scripts/registry.py` (CLI). See §4.
- **Phaethon** (distinct parallel system) — `src/phaethon/`: `scorecard.py`, `governance.py`, `ledger.py`, `publish.py` (the publish path → `docs/data/phaethon_live.json` / `phaethon_b_live.json`); `journal.py`, `review_trigger.py`, `lessons_ledger.py`, `prediction_resolution.py`, `learning_kill_switch.py`, `schema.py` (the boundary-only learning mechanism — built, **no data yet**). Scripts `phaethon_review_report.py`, `phaethon_adopt_lesson.py`.

### 1.3 Pantheon names — code vs. label (verified by grep)
Only **two** pantheon names have backing code in `src/`/`config/`:
- **Oracle** — the running paper book (`src/paper_trading.py` + `config/sleeves/oracle_v1.yaml`). ✅ code.
- **Phaethon** — `src/phaethon/` (11 modules). ✅ code.

The rest are **display labels** on the dashboard (`docs/index.html`, `scripts/_olympus.py`) with **no `src/` code in this repo**: Zeus (council/kill-switch), Hermes (execution — engine lives in an external `labs/` tree not in this repo), Themis (governance — the label for the sleeve/lock discipline), Mnemosyne (attribution — the function exists as `src/governance/attribution_log.py` but is not named Mnemosyne), Demeter (valuation — `src/agents/valuation.py`, not named Demeter), Apollo/SCAI, Hades, Kairos, Hephaestus/Chronos/Artemis (a single "discovery brain" prose label; listed as *future* members), Iris/ESE. **Phobos** appears **only** in `pantheon_naming_map.md` — no code, no dashboard presence. See §7 for the `labs/`-absent divergence.

---

## 2. Governance / lock inventory (single reference table)

| Guard | Mechanism / file | Protects | Re-registration / bypass procedure |
|---|---|---|---|
| **Protocol lock** | `config/protocol_lock.yaml` (`locked`, `registered: 2026-07-05`, `protocol_sha`, `ruleset_sha`) + `scripts/verify_protocol_lock.py`. **Status today: PASS.** | 7 ruleset files: `src/paper_trading.py`, `src/engine/calculator.py`, `src/signals/momentum.py`, `src/signals/revisions.py`, `config/constitution.yaml`, `config/settings.yaml`, `config/universe.yaml`; plus `protocol_sha` covers `docs/OBSERVATION_PROTOCOL.md`. | `python scripts/verify_protocol_lock.py --register` (deliberate), then log the reason in `docs/PROTOCOL_CHANGELOG.md` (**9 entries** to date). A `lock_sha` mismatch is defined to halt the screen. |
| **Constitution booleans** | `config/constitution.yaml` + `tests/test_constitutional_guards.py::test_constitution_hard_booleans_all_true` | `NO_LEVERAGE`, `NO_REAL_ORDERS`, `NO_LIVE_PNL_LEARNING`, `human_gated` (+ `MAX_SINGLE_POSITION: 0.10`, `MIN_OBSERVATIONS_FOR_CALIBRATION: 20`). | Change the yaml → CI fails unless the guard is updated deliberately. |
| **No broker libraries** | `test_no_broker_library_imports`, `test_no_broker_library_in_requirements`, `test_swingbot_place_real_order_raises` | Whole repo (agent + swing-bot dirs) — no `ibkr`/`alpaca`/etc. import may exist. | None — this is a hard bright line. |
| **Research/trading ringfence** | `test_swingbot_and_agent_are_ringfenced`, `test_no_feedback_imports.py` | Agent code and swing-bot code cannot import each other. | None. |
| **Phaethon isolation** | `test_phaethon_does_not_import_engine_or_signals`, `test_phaethon_no_live_pnl_read_in_prompt_paths` | `src/phaethon/` cannot import the rating engine/signals or read a live-P&L/fills artifact from a prompt path. | None (NO_LIVE_PNL_LEARNING firewall). |
| **Phaethon learning firewall** | `test_learning_modules_unreachable_from_phaethon_facing_code`, `test_learning_modules_write_only_human_side` | The learning modules are unreachable from any Phaethon-facing/context-builder code; they write only human-side paths. | None. |
| **Deploy droplet guard** | `test_deploy_sh_has_both_trading_guards` + `scripts/deploy.sh` | Deploy refuses unless host/hostname contain "trading". | Edit `deploy.sh` guards deliberately. |
| **Locked-config flag** | `test_locked_configs_report_locked_true` | Locked config files self-report `locked: true`. | Deliberate. |
| **Sleeve admission (Themis)** | `src/sleeves/manifest.py` + `tests/test_registry_discipline.py` | A sleeve manifest missing `registry_ref` or `kill_criteria` fails to load; a sleeve at stage ≥ S2 must reference a **PASSED** registry entry. | N/A — additive framework, no lock. |
| **Registry content chain** | `src/research/registry.py::verify_registry_chain` + `tests/test_research_registry.py` | Immutable hypothesis fields — editing e.g. a `hypothesis` breaks the chain. | Append-only; status advances forward-only via `advance_status`. |

**Cohort-scoped ruleset behaviour inside the locked `src/paper_trading.py`:** `exit_rules_v2` is **ACTIVE** (`config/settings.yaml: exit_rules_v2: true`) and confined to `cohort_1` only (the guard `pos.cohort != "cohort_1"` excludes legacy); the Legacy Cohort is exempt (RATING_DOWNGRADE-only) until its **forced sunset on `LEGACY_SUNSET_DATE = 2026-08-23`** (`FORCED_SUNSET`, flag-independent). Frozen v2 params: `pt_fraction=1.0, max_hold_days=270, stale_days=28`.

---

## 3. Cohort & evidence-state ledger (actual numbers from the data files)

| Cohort / arm | Source | Actual state today |
|---|---|---|
| **Legacy Cohort** | `data/paper_positions.yaml` | **12 positions**, all `cohort: legacy_pre_fix`, all opened **2026-05-25** (pre-fix engine). No gates/kill criteria — runs only its §1.2 **forced sunset on 2026-08-23**. |
| **Cohort-1 / `oracle_v1`** | `data/paper_positions.yaml`, `config/protocol_lock.yaml`, `config/sleeves/oracle_v1.yaml` | **0 positions, 0 closed trades** (`data/paper_trades.jsonl` is absent). Protocol lock `registered: 2026-07-05`. Sleeve `oracle_v1`: **stage S1** (downgraded from S2 on 2026-07-05 — see §4/§7), `registry_ref: "003"`, benchmark SPY_TR, 4 kill_criteria (verbatim from §5). **The window's clock is registered but the book is still empty** — see §6(c). Pre-declared window: 52 weeks; success only at window end (§5). |
| **Phaethon Arm A (disciplined)** | `docs/data/phaethon_live.json` | **18 positions, 62.0% cash, gross 38.0% — CONFORMING.** Marked `restated 2026-07-05, cash-accounting bug fixed`. |
| **Phaethon Arm B (aggressive)** | `docs/data/phaethon_b_live.json` | **11 positions, 5.1% cash, gross 94.8% — NONCONFORMING.** Open flags (3): `CEG 13.5%`, `GOOGL 13.8%`, `AMZN 10.6%` each `> MAX_SINGLE_POSITION 10%`. Leverage bug fixed (was 138%); the **operator question — live candidate vs falsification control — remains open** (`docs/PHAETHON_ARM_B_LEDGER_MEMO.md`). |
| **Other sleeves** | `config/sleeves/` | Only `oracle_v1` exists. The sleeve framework supports more; none registered. |

> **Cannot verify from the repo alone:** droplet-side state, cron status, and any live tmux run (e.g. the `ptcal2` calibration job) are not derivable from the repo and are **not** asserted here.

---

## 4. Registry status (real `scripts/registry.py stats` output on `main`)

`scripts/registry.py stats` on `main` @ `4118fde` prints:
```
m (hypotheses ever)  : 3
Bonferroni alpha     : 0.016666666666666666
pass rate (resolved) : 0.00% (0/2)
```
| id | status | hypothesis (abbrev.) | result_ref |
|---|---|---|---|
| **001** | FAILED | 12-1 cross-sectional momentum, Q1−Q5 net spread, NW t≥2 | `research/momentum_validation/MEMO_momentum.md` |
| **002** | FAILED | Post-earnings-announcement drift (PEAD/Kairos) | `swing-bot/backtest/PEAD_RESULTS.md` |
| **003** | TESTING | Oracle/Cohort-1: STRONG_BUY-gated entries beat SPY TR net of costs (§5 gate) | `docs/OBSERVATION_PROTOCOL.md` (no result — window mid-flight) |

**Correction bar today:** `m = 3`, Bonferroni `alpha = 0.05/3 ≈ 0.0167`; pass rate `0/2` resolved (003 is unresolved/TESTING). Registry entries are append-only with a content-hash chain; both retroactive entries are FAILED, so the denominator "includes history."

> **⚠️ Merge-state caveat (see §6/§7):** the branch `registry-machinery-fixes` (committed, **unmerged**) changes this machinery — the correction denominator would count **TESTING-or-beyond only** (`m` unchanged today at 3, since all three are TESTING+), the stats CLI would show a second "total entries registered" line, `interpretation_contract` becomes a required field (001–003 backfilled via an appended `SCHEMA_MIGRATION`), and a `queue` command is added. **None of that is on `main` yet.** The `main` output above is the canonical current state.

---

## 5. Data flow — one trade/decision, end to end (actual code path)

1. **Universe admission** — `config/universe.yaml` (147 tickers) filtered by `src/universe/admission.py::check_market_cap_admission` (micro-cap floor / cap ceiling from `config/settings.yaml` screener block).
2. **Rating/signal generation** — `scripts/run_universe.py` runs the screener: `src/engine/calculator.py` computes DCF + comps → `compute_price_target` → expected return → `classify_rating` (`STRONG_BUY…`) + `assess_confidence_v2`; signals (`src/signals/`) and the governance council (`src/governance/` — `dcf_skeptic`, `concentration_governor`, `constitution`, `adversarial`) inform/adjust. Output → **`runs/_screen/<latest>/summary.json`**.
3. **Entry decision** — `scripts/paper_run.py` reads the latest `summary.json` and calls `src/paper_trading.py::process_screener_results`. `should_enter` = rating `STRONG_BUY` AND confidence ∈ {MED, HIGH}. New positions → `open_position(cohort=NEW_POSITION_COHORT="cohort_1")`.
4. **Position record** — written to `data/paper_positions.yaml`, schema- and cohort-validated (`_validate_cohort` accepts only `legacy_pre_fix`/`cohort_1`).
5. **Exit evaluation** — with `exit_rules_v2: true`: for `cohort_1` positions, `evaluate_exit_v2` applies precedence `RATING_DOWNGRADE > PT_HIT > TIME_STOP > STALE`; legacy positions are excluded (still `should_exit` = rating downgrade) until the `2026-08-23` `FORCED_SUNSET` pass force-closes them.
6. **Close** — `close_position` writes an immutable record to `data/paper_trades.jsonl` with gross/net and **dividend-adjusted total-return** fields and alpha vs SPY (cost haircut = `paper_cost_bps: 20`, per side).
7. **NAV / attribution** — `src/portfolio/nav_ledger.py` (`compute_units` with `paper_nav_start=100000`, `n_target_positions=20`; `build_snapshot`, `compute_performance` per cohort); `paper_run.py` writes an additive attribution snapshot.

**Divergence noted in the flow:** `n_target_positions = 20` (config) is the sizing denominator, but no live cohort holds 20 (Legacy = 12; Cohort-1 = 0). Phaethon has an **entirely separate** publish path (`src/phaethon/publish.py` → `docs/data/phaethon_*.json`) — it does **not** flow through `paper_trading.py`.

---

## 6. Known gaps & deferred items

### (a) Deliberately deferred (with pointer)
- **Live trading:** none exists — paper-only by constitutional design (`NO_REAL_ORDERS`, broker-import guard). Any "November live-trading backlog" is **not built**; no broker/IBKR/Alpaca code is present.
- **Phaethon Arm B disposition:** cash bug fixed; whether B remains a live candidate or becomes a falsification control is explicitly deferred to the operator (`docs/PHAETHON_ARM_B_LEDGER_MEMO.md`).
- **Registry machinery fixes (F7a/F7b/F5/F7d):** committed on `registry-machinery-fixes`, **not merged** — deferred to a merge decision.
- **Second sleeve:** the framework supports many; only the `oracle_v1` retrofit exists.

### (b) Genuinely unknown / undecided
- **Droplet/cron/tmux state** (e.g. the `ptcal2` calibration run, the Phaethon publisher cron) — not derivable from the repo; status unknown here.
- Whether Cohort-1 "inception" is the lock-registration date (2026-07-05) or the first-position date — the protocol says "first screen under the locked ruleset," but no cohort_1 position exists yet (see 6c).

### (c) Gaps I found that nobody appears to have flagged — surfaced prominently
1. **Cohort-1 is armed but empty.** The protocol lock is `registered: 2026-07-05` and `exit_rules_v2` is ACTIVE "for Cohort-1," yet `data/paper_positions.yaml` has **0 `cohort_1` positions** and `data/paper_trades.jsonl` is **absent (0 trades)**. The 52-week evidence clock is effectively running against an empty book; the whole exit-rules-v2 activation currently governs zero positions.
2. **The Phaethon learning mechanism has never run on data.** `data/phaethon/` and `runs/phaethon/` are **empty** — no journal, no lessons ledger, no review artifact, no `LEARNING_SUSPENDED` sentinel. The entire boundary-learning machinery (kill switch, prediction resolution, change budget) is built and unit-tested but has **zero real-world exercise**.
3. **`main`'s registry lacks the discipline fixes it was just given.** `interpretation_contract` is NOT required on `main`, and the correction denominator still counts all entries (not TESTING+). The improvements exist only on an unmerged branch — so the canonical system runs the pre-review machinery.
4. **BUG-003 is OPEN** (`KNOWN_BUGS.md`): LMT/MA price target floored to $0, confidence=BROKEN.
5. **Pre-existing test failures:** the suite is **851 passed / 6 failed** — the 6 failures are all `tests/test_dashboard_live.py` (position-id assertions vs a newer `docs/index.html` structure). Long-standing; not from recent work.
6. **Untracked "system" docs:** several status/design docs a reader would treat as canonical are **not in git** (untracked working files) — see §7.

---

## 7. Document / reality divergences (actively hunted — this class of error has recurred here)

| # | Divergence | Doc claim (source) | Repo reality (source) |
|---|---|---|---|
| 1 | **Universe size** | 61 tickers (`SYSTEM_AUDIT_2026-05-25.md:323`); "Universe is now 60 names" (`KNOWN_BUGS.md:42`) | **147 tickers** (`config/universe.yaml`; matches `docs/environment_snapshot.md:16` "147 tickers, 25 archetypes"). The 60/61 docs are stale. |
| 2 | **Whole prior-review docs predate the architecture** | `olympus_system_review.md` (2026-05-29), `SYSTEM_AUDIT_2026-05-25.md`, `OLYMPUS_STATUS_BRIEFING_2026-06-16.md`, `NEXT_STEPS.md` (2026-06-05) describe the system | They mention **0** sleeves/registry/exit_rules_v2 (`grep`): the entire framework layer (sleeves, hypothesis registry, exit_rules_v2, Phaethon governance, cohort tagging, protocol lock re-registrations) landed **2026-07-05**, after all of them. Do not use them as ground truth. |
| 3 | **`labs/` engines referenced but absent** | Dashboard/naming map present Hermes (execution), Apollo/SCAI, Iris/ESE as system members | The `labs/` tree that holds their code **is not in this repo**. In-repo they are **display labels only** (`docs/index.html`, `scripts/_olympus.py`). |
| 4 | **`Phobos` implies a built member** | `pantheon_naming_map.md` lists Phobos (volatility) as a member | **Zero** code/dashboard/config hits anywhere. Naming-map-only. |
| 5 | **Stale branch refs read as "unmerged"** | `git branch` shows `exit-v2-cohort-guard`, `legacy-forced-sunset` as unmerged | Their **content IS in `main`** (cohort-scope guard + forced sunset both present in `src/paper_trading.py`) — the refs are pre-rebase stragglers. Only `registry-machinery-fixes` is genuinely unmerged. |
| 6 | **Untracked docs treated as canonical** | `NEXT_STEPS.md`, `OLYMPUS_STATUS_BRIEFING_2026-06-16.md`, `Olympus_Build_Prompt_v1.2.md`, `INFRA_INVENTORY.md`, `NAME_MAP.md`, `WORKING_STYLE.md`, `caerus_design_note.md`, `council_architecture_note.md` | All are **untracked** (`git status` `??`) — on disk but not in the repo of record. |
| 7 | **Book size** | `n_target_positions: 20` (`config/portfolio.yaml`) is the sizing target | No live cohort holds 20 (Legacy 12, Cohort-1 0, Phaethon A 18 / B 11). Target ≠ actual — not a bug, but do not read "20" as a live count. |
| 8 | **`oracle_v1` stage history** | An earlier state had `oracle_v1` at S2 | Now **S1** — deliberately downgraded 2026-07-05 (inline comment in `config/sleeves/oracle_v1.yaml`) because its hypothesis (entry 003) is TESTING, not PASSED; a prior reviewer's "S2" is superseded. |
| 9 | **A documented output file does not exist** (the classic recurring class) | `README.md:59` and `src/paper_trading.py:11,29` present `data/paper_trades.jsonl` as the paper-run output / "immutable append-only log of closed trades" (`TRADES_PATH`) | The file **does not exist** — 0 closed trades, never written. Runtime-created, but documented as an existing artifact. |
| 10 | **`exit_rules_v2` comment contradicts its own value + the code** | `config/settings.yaml:36–40` comment: "**DEFAULT OFF — must stay false until the PLACEHOLDER thresholds … are calibrated**" | Value on line 40 is **`exit_rules_v2: true`**; `src/paper_trading.py:77–80` params are "calibrated…frozen"; `tests/test_cohort1_exit_rules_active.py` asserts it **must be True**. The comment is stale (not updated when the flag flipped). |
| 11 | **`environment_snapshot.md` overstates dependencies** | `docs/environment_snapshot.md:26–29` pins `matplotlib`, `numpy`, `python-dateutil` as runtime deps | `requirements.txt:48–52` explicitly **drops** them as "not imported by any module"; `grep` confirms no direct import anywhere in `src/`/`scripts/`. |
| 12 | **Dangling config key** | `config/settings.yaml:54` → `corpus_file: "corpus.jsonl"` | No corpus module and no `corpus.jsonl` exist (README lists corpus as "planned / not built"). |
| 13 | **`STATUS.txt` internally inconsistent + stale** | `STATUS.txt:2–3` "**6 tickers screened.** Distribution … SB=17 B=3 H=12 S=8 SS=20" | Distribution sums to **60**, impossible from a 6-ticker screen; dated 2026-05-25, never refreshed, predates the 147-name universe. |
| 14 | **Briefing cites a deploy tool not in the repo** | `OLYMPUS_STATUS_BRIEFING_2026-06-16.md` repeatedly cites `safe_deploy.sh` as *the* deploy discipline; "suite green (**87/0**)" | No `safe_deploy*` exists in the repo (only `scripts/deploy.sh`); suite today is **56 files / 851 passed, 6 failed**. Likely droplet-only, presented without that caveat. |
| 15 | **`INFRA_INVENTORY.md` lists absent script paths** | e.g. `scripts/price_updater.sh`, `kill_flags.sh`, `quarterly_rebalance.sh`, `run_hermes_{daily,weekly}.sh`, `universe_check.py` | None exist under this repo's `scripts/`; swing-bot scripts it lists at `scripts/…` actually live under `swing-bot/scripts/`. (Droplet inventory; also an untracked doc — see #6.) |

**Confirmed clean (checked, not divergent):** `config/universe.yaml` header "147" matches the count; README rating bands match `config/settings.yaml`; `docs/LIVE_RUNBOOK.md` path references all exist; `pantheon_naming_map.md`'s only in-repo build claim (Phaethon governance in `src/phaethon/`) is accurate; the 003/oracle_v1 reconciliation is internally consistent. Notably, `research/momentum_validation/MEMO_momentum.md` **already flags** the "60 names → actually 147" staleness (#1) — the repo half-knows.

> A dedicated two-reader divergence sweep was run as part of this snapshot; the items above are the confirmed, load-bearing ones. Lesser docstring drift may remain — the repo, not any doc, is authoritative.

---

*Generated 2026-07-06 from `main` @ `4118fde`. Regenerate after the next subsystem-touching merge (or monthly). To refresh the hard numbers: `python scripts/registry.py stats`; `python scripts/verify_protocol_lock.py`; count `data/paper_positions.yaml` by cohort; read `docs/data/phaethon_*.json` status; `git branch` merge-state.*
