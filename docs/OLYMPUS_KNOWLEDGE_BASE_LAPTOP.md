# Olympus / ATS — Consolidated Knowledge Base

## LOCATION: **LAPTOP** (Mac, `Mac.mynet`, macOS Darwin 25.4.0)

**Repo root:** `/Users/jackgardiner/agent` · **Remote:** `git@github.com:jackgardiner050-pixel/ATS.git`
**Branch:** `main` · **HEAD:** `c97c9ff` (2026-09-01 18:44 +0100, "live dashboard refresh — 2026-09-01 17:44 UTC")
**Compiled:** 2026-09-01 · **Method:** read-only walk of the working tree, git history, config, data files, and tests. No code, config, or data was modified. This file is the only write.

> This spec runs **twice** — once per location. This is the laptop run. The droplet run produces
> `docs/OLYMPUS_KNOWLEDGE_BASE_DROPLET.md`. The two are **not** merged here; reconciliation is a
> separate manual diff step (§9).

---

## ESCALATION-CLAUSE CHECK — result: **NO DIVERGENCE, proceed**

The escalation clause requires stopping if the two locations' HEADs suggest real divergence. Checked
read-only over SSH to the `ats-trading` droplet (named in `INFRA_INVENTORY.md:8`):

| Location | Repo path | Branch | HEAD |
|---|---|---|---|
| Laptop | `/Users/jackgardiner/agent` | `main` | `c97c9ff` (2026-09-01 18:44) |
| Droplet `ats-trading` | `/root/phaethon-panel-repo` | `main` | `7ef5fcd` (2026-08-31 22:45) |

`git merge-base --is-ancestor 7ef5fcd HEAD` → **true**. The droplet HEAD is a direct ancestor; the
droplet is **2 commits behind**, and both commits are automated `ATS Live Refresh <noreply@ats>`
dashboard-data commits (`89797f3`, `c97c9ff`) carrying no code or governance change. Same lineage,
no fork, no rewritten history. **Consolidation proceeds.**

Only one git working tree was found on the droplet (`/root/phaethon-panel-repo`); `/root/agent` and
`/opt/agent` do not exist there. Nothing further about the droplet was inspected in this run — that
is the droplet run's job (§9).

---

# LOCAL-ONLY MATERIAL FOUND AT THIS LOCATION

Everything in this section exists **on this laptop only** and is **not** part of shared repo
history. It is listed separately and is **not** folded into §1–§8 as if it were committed record;
where a local-only document is the sole source for a fact used later, it is cited as
`(LAPTOP-LOCAL)`.

## A. Tracked but modified (`git status --porcelain`, ` M`)

| File | Apparent content | Relevance |
|---|---|---|
| `docs/data/hermes_v3_live.json` | Live price/mark refresh output, rewritten 2026-09-01 19:45 | **Operational, location-specific.** Product of the Mac `com.ats.live-refresh` launchd job (below), not yet committed. Not decision history. |
| `docs/data/system_summary_live.json` | Cross-system summary panel data, same job/timestamp | Same — operational only. |

## B. Untracked (`??`) — the substantive local-only corpus

| File | Apparent content | Relevance to Olympus/ATS decision history |
|---|---|---|
| `olympus/` (directory) | **The Olympus MVP "council" build's data tier**: `data/ledgers/*.jsonl` (decisions 11, screener_picks 19, paper_fills 28, outcomes 2, overrides 2, postmortems 2), `data/reports/*.md` (journal, forward_scorecard, quarterly_review, override_audit, success_audit, monthly_rollup, exposure_report, `zeus_oracle_20260602_ORCL.md`), `data/arm_{A,B,C}_portfolio.json`, `data/paper_portfolio.json`, all dated **2026-06-04**. Code subdirs (`olympus/olympus/{core,members,discovery,adapters,benchmark,preregistration,models,reports}`, `olympus/tests`) are **gitignored and contain zero `.py` files on this machine** — only `__pycache__` and one `portfolio_policy.real.yaml`. | **HIGHLY RELEVANT — the only running-council prior art anywhere in this corpus.** The one worked decision (Zeus→ORCL HOLD, LOW confidence, human override to SKIP) is the sole empirical example of the member/council architecture executing. Per `INFRA_INVENTORY.md:47,112,121` the live loop `agent/olympus/scripts/run_olympus_loop.sh` runs on the droplet and **"exists nowhere else"** — so the *code* behind this data is invisible from here (§9). |
| `Olympus_Build_Prompt_v1.2.md` | 349-line "OLYMPUS MASTER SYSTEM SPECIFICATION v1.2 — Minimal, Governance-First, Consolidation-Aware Build Prompt". Defines the MVP member set (Oracle, Athena-Nemesis, Hecate, Tyche, Themis-Mnemosyne, Zeus, Hermes), the named-placeholder list, and §2 non-negotiable constraints, §6 Aeolus/Hades trap rule, §7 correlated-council rule, §8 benchmark/ETF-alternative rule, §9 core+satellite rule, §10 forward scorecard. Dated on disk 2026-06-04. | **HIGHLY RELEVANT.** This is the design contract the `olympus/` data above was produced under, and the most directly reusable prior art for a council/agent redesign. Rules extracted into §2 and §7 and tagged `(LAPTOP-LOCAL)`. |
| `council_architecture_note.md` | 99 lines, drafted 2026-05-29. "Investment Council — Target Architecture (Precondition-Gated)", status **TARGET / DO NOT BUILD YET**. Three traps, the precondition gate, three-tier architecture, ring-fenced learning layer, hosting principle. | **HIGHLY RELEVANT** — the standing gate that governs whether a council may be built at all (§7 D-06). |
| `lessons_learned.md` | 90 lines, drafted 2026-06-02. Cross-strategy post-mortem: 10-strategy corpus table with recorded verdicts, 7 grouped failure modes with counts, "one bet in many coats" analysis, the 2026-06-02 Nemesis/Plutus update and the **cost-access pattern**. | **HIGHLY RELEVANT** — the closest thing to a falsification ledger for the pre-registry era (§4B). |
| `olympus_system_review.md` | 65 lines, drafted 2026-05-29, updated 2026-06-01. Whole-system audit: roster/status, 9 flaws, 7-item priority plan, candidate future members, **Architecture 9/10 vs Evidence ~1/10**. | **HIGHLY RELEVANT** (§7 D-05, §8 Q-07). |
| `hades_design_note.md` | 67 lines, 2026-05-29. Crash/de-risk member — **FALSIFIED AS DESIGNED**; look-ahead artifact; net-negative on all 8 crash episodes once recovery counted. | **RELEVANT** — a conclusive falsification (§4B). |
| `caerus_design_note.md` | 47 lines, 2026-06-02. Short-horizon catalyst-momentum — **FALSIFIED** on its pre-registered kill-check; loses to a random liquid-mover control by −1.59pp. | **RELEVANT** — the second conclusive falsification (§4B). |
| `mercury_design_note.md` | 157 lines, 2026-05-29. Short-horizon mover-detection lab — **PRELIMINARY DESIGN, not built.** | **RELEVANT** — design-not-built; renamed Kairos in the naming map. |
| `metis_design_note.md` | 23 lines, 2026-06-02. AI trading agent — **PARKED / build cancelled 2026-06-02**; superseded by Phaethon. | **RELEVANT** (§7 D-04). |
| `NEXT_STEPS.md` | 47 lines, captured 2026-06-05, updated 2026-06-24. Work queue; records Phaethon Arm B build/isolation (2026-06-07), Gaia rebalancing/glidepath, dashboard panel, and the **v1.1 "broadened aperture" deploy 2026-06-24** with its 40–60-day verification obligation. | **RELEVANT** — contains dated decisions and one unmet verification (§8 Q-08). |
| `OLYMPUS_STATUS_BRIEFING_2026-06-16.md` | 72 lines, 2026-06-16. Self-contained context handoff for a fresh advisory session. | **RELEVANT but SUPERSEDED** — `docs/OLYMPUS_SYSTEM_STATE.md §7 #2,#10` records that it predates the whole framework layer and cites a `safe_deploy.sh` that does not exist. |
| `INFRA_INVENTORY.md` | 156 lines, 2026-06-08. Three-host cron/launchd/systemd inventory (Mac, `ats-trading`, `ats-research`) with leftover flags and a **reversible decommission log**. | **RELEVANT** — infrastructure decisions (§7 D-07); also the source for where the live Olympus loop runs. |
| `NAME_MAP.md` | 24 lines, 2026-06-01. Pantheon display names — explicitly **label layer only**, no renames. | **RELEVANT** — clarifies that pantheon names are render-time labels (agrees with `OLYMPUS_SYSTEM_STATE.md §1.3`). |
| `WORKING_STYLE.md` | 7 lines, set 2026-06-01. Response-style rule: concise, no jargon, plain terms, keep the rigour. | **RELEVANT** — a standing operator instruction (§7 D-13). |
| `epe_public_summary.md` | 46 lines, 2026-06-01. Sanitized MOM_TOP5 / Experimental Pot Engine summary; paper-only; 15% satellite intent. | **RELEVANT** — external-facing research record. |
| `ese_public_summary.md` | 31 lines, 2026-06-01. Sanitized Event Signal Engine summary; verdict **fair-weather satellite**. | **RELEVANT** — external-facing research record. |
| `Olympus_System_Overview.docx` | 20,684-byte binary Word document, 2026-06-03. | **RELEVANT (UNVERIFIED)** — binary; not parsed in this run. Flagged so it is not silently lost. |
| `.crontab.mac.bak.20260608` | 2-line backup of the Mac crontab taken at the 2026-06-08 decommission. | **RELEVANT (minor)** — evidence for D-07. |
| `.DS_Store`, `data/.DS_Store`, `docs/.DS_Store`, `src/.DS_Store`, `swing-bot/.DS_Store` | macOS Finder metadata. | **INCIDENTAL.** |

## C. Ignored but present (`git status --porcelain --ignored`, 49 entries)

| Path(s) | Content | Relevance |
|---|---|---|
| `data/governance/` (`calibration_log.jsonl`, `exposure_log.jsonl`, `regime_log.jsonl`, `signal_tracker_log.jsonl`), `data/governance_journal/governance_20260526_170516.json` | Governance-layer runtime logs, last written 2026-05-26. | **Location-specific runtime.** Only one governance-journal snapshot exists — consistent with no screen having run since 2026-05-26 (§3). |
| `data/attribution_log.jsonl`, `data/eps_trend_history.jsonl`, `data/last_digest_state.json` | Attribution snapshots; the EPS-trend forward-observation log (Study A, §4C); digest state. | **RELEVANT (runtime).** `eps_trend_history.jsonl` is the accruing forward sample for the ~18-month revisions read. |
| `logs/live_dashboard.log` (1.2 MB, live to 2026-09-01 19:45), `logs/full_run_20260526_150058.log` | Mac live-refresh job log; one full screen run log from 2026-05-26. | **RELEVANT (operational).** 2,019 lines match error/fail/traceback; the tail shows repeated `Skipped scai_live.json / hermes_live.json (new n_priced=0, keeping last good data)` and `portfolio=None% SPY=None% alpha=None%` — a degraded but non-fatal refresh (§8 Q-10). |
| `gaia/current_allocation.real.yaml`, `gaia/fee_report.real.md`, `gaia/data/gaia_private.json` | The operator's **real-money** allocation and fee report. | **Deliberately excluded by design** (the "no personal data on the public dashboard" rule, `NEXT_STEPS.md`). Contents intentionally not read or reproduced here. |
| `runs/` (148 entries incl. `runs/_screen/`), `swing-bot/data/`, `research/momentum_validation/{_price_cache.parquet,run.log}` | Per-run artifacts, screen outputs, price caches, study logs. | **RELEVANT (evidence trail)** — `runs/_screen/` is the basis for the §3 finding that no screen has run under the lock. |
| `olympus/.pytest_cache/`, `olympus/olympus/*/`, `olympus/tests/` | Ignored subtree of the untracked `olympus/` build — **no `.py` files present locally.** | **RELEVANT AS AN ABSENCE** — see §9. |
| `.claude/`, `.pytest_cache/`, all `__pycache__/` | Tooling/caches. | **INCIDENTAL.** |

## D. Local material outside the repo (location-awareness step 4)

Checked: the repo root's parent `/Users/jackgardiner`, plus `notes/` and `scratch/` (neither exists).

| Path | Content | Relevance |
|---|---|---|
| `~/droplet_ats-trading_inventory_20260512.md` | Full inventory of `ats-trading` (DO id 563712595, lon1, s-2vcpu-4gb), 2026-05-12. | **RELEVANT (infra history).** |
| `~/droplet_ats-research-simfin_inventory_20260512.md` | Inventory of `ats-research-simfin` (DO id 568342162, s-4vcpu-8gb), 2026-05-12. | **RELEVANT but SUPERSEDED** — `docs/CONSTITUTIONAL_EXCEPTIONS.md` records this host **no longer exists** as of 2026-07-05. |
| `~/droplet_comparison_20260512.md` | Side-by-side comparison written for the consolidation decision, 2026-05-12. | **RELEVANT** — the input to the host-consolidation decision (§7 D-07). |
| `~/Olympus memory build/` | **Empty directory**, created 2026-08-18. | Incidental; noted only because its name implies intent. |
| `~/trading/ecosystem_architecture.md` (+ `hermes_*.md`) | The document `lessons_learned.md` repeatedly cites as source (§11, §12) for the RP/QRE closure and the Nike/Iris verdicts. **Outside the ATS repo entirely.** | **RELEVANT** — the citation target for several §4B verdicts is not in this repo at either location. |
| `~/phaethon_shadow/`, `~/phaethon_trader_stage/` | Phaethon shadow-run and trader staging trees (`run_cycle.py`, `test_goodhart.py`, `test_killswitch.py`, `seed_memory.py`, `skills/`). | **RELEVANT** — the Phaethon **strategy** code (the frozen half the repo deliberately does not own). Not in the ATS repo. |
| `~/labs/`, `~/epimetheus/`, `~/trading/{scai,hermes,hermes_learning,hermes_v3}_lab/`, `~/capability_atlas*/`, `~/harness/`, `~/results/`, `~/backups/ats-consolidated/` | Separate git repos / working trees for the `labs/` engines the dashboard labels refer to. | **RELEVANT AS CONTEXT** — `OLYMPUS_SYSTEM_STATE.md §7 #3` flags that `labs/` is absent from the ATS repo; it is present on this laptop as sibling repos. Their internal history is out of scope for this consolidation. |
| Mac `crontab -l` + `~/Library/LaunchAgents/` | Active: `com.ats.live-refresh` (launchd), `com.ats.backup`, `com.hermes.v2-weekly`, plus a nightly `experimental_pot_engine/run_nightly_track.sh` cron. Disabled: `com.ats.agent-pull.plist.disabled`, and the commented-out duplicate dashboard-refresh cron line. | **RELEVANT (and in tension with a standing rule)** — the laptop is an **active publisher** to `main`: `com.ats.live-refresh` produces the `ATS Live Refresh` commits that put this location 2 ahead of the droplet. `council_architecture_note.md` states the standing principle that a continuously-running system belongs on an always-on machine, not a laptop (established 2026-05-29). Flagged, not resolved (§8 Q-09). |

## E. Files the spec named that are **absent at this location**

- `config/locks/*` — **does not exist**. The lock lives in the single file `config/protocol_lock.yaml` (which now carries a nested `live_pilot:` block — see §2).
- `config/retired.yaml` — **does not exist**. Retirement is recorded per-entry via `registry.yaml` status (`RETIRED` is a valid status in the machinery) and, historically, in prose (`pantheon_naming_map.md` "Dissolved / retired").
- `docs/OLYMPUS_KNOWLEDGE_BASE.md` / `..._INDEX.md` — **not in git at any commit** (`git log --all -- '*KNOWLEDGE_BASE*'` returns nothing) and not on this disk. Prior-session records indicate these were written directly onto the droplet on 2026-08-07 and never committed. **This is a real cross-location gap** (§9).

---

# 1. System identity

Olympus (repo name **ATS**) is a **paper-only equity research system with no ability to place an
order**. Software reads public company filings and prices, builds a valuation for each company in a
fixed 147-name list, and turns that into a rating — Strong Buy through Strong Sell — plus a
confidence label. A simulated portfolio ("paper book") then opens and closes make-believe positions
using rules that were written down, hashed, and frozen in advance, so nobody can quietly change the
rules once results start coming in. Nothing touches real money: a test fails the build if any
broker software is even imported (`tests/test_constitutional_guards.py`).

Wrapped around that core are three separate honesty mechanisms: a **protocol lock** (a checksum over
the decision files, so a change is either deliberate and logged or the run halts); a **hypothesis
registry** (every idea is written down as a falsifiable claim with its pass/fail number *before* it
is tested, and the count of tests is used to correct for the fact that testing many ideas produces
lucky-looking winners); and a **sleeve contract** layer (no strategy may run without a registered
hypothesis and pre-written conditions for stopping it).

Alongside sits **Phaethon** — a separate, isolated experiment where a language model generates
investment ideas, run as two paper arms (a disciplined one and a deliberately aggressive one), which
is allowed to learn only at rare, governed boundaries, never continuously from its own profits and
losses. Most of the Greek names on the dashboard (Zeus, Hermes, Themis…) are **labels, not code**
(`docs/OLYMPUS_SYSTEM_STATE.md §1.3`); only the rating engine ("Oracle") and Phaethon have
implementations in this repo. Separately, a **live pilot** ("E1") has been designed and built where
a human — never the machine — would place a small number of real orders from system-generated
cards; it is **built, drilled, and unfunded** (§6).

---

# 2. Governance constitution — every hard rule and where it is enforced

## 2.1 Hard prohibitions — `config/constitution.yaml` (v1.0, effective 2026-05-26) — **CURRENT**

Seven immutable booleans, all required `true`. The file header states it is human-editable only and
never programmatically modified.

| Rule | Enforced by |
|---|---|
| `NO_LEVERAGE` | `tests/test_constitutional_guards.py::test_constitution_hard_booleans_all_true` |
| `NO_SHORT_SELLING` | same; also `src/live/intents.py` (BUY/SELL only, no SHORT) |
| `NO_AUTONOMOUS_EXECUTION` | same; `config/live_limits.yaml` rejects `execution_stage: E2` at load |
| `HUMAN_APPROVAL_REQUIRED` | same; `live_limits.yaml::HUMAN_EXECUTES_ALL_ORDERS: true` |
| `NO_LIVE_PNL_LEARNING` | `test_no_outcome_data_imported_in_engine_or_signals`, `test_no_outcome_files_referenced_in_engine_or_signals`, `tests/test_no_feedback_imports.py`, `test_phaethon_no_live_pnl_read_in_prompt_paths` |
| `NO_BROKER_INTEGRATION` | `test_no_broker_library_imports`, `test_no_broker_library_in_requirements`, `test_swingbot_place_real_order_raises`, `test_live_layer_no_broker_and_no_decision_math` |
| `NO_SELF_MODIFYING_RISK_RULES` | `test_constitution_hard_booleans_all_true`; `test_locked_configs_report_locked_true` |

## 2.2 Concentration and exposure limits — `config/constitution.yaml` — **CURRENT**

`MAX_SINGLE_POSITION 0.10` · `MAX_SINGLE_THEME_EXPOSURE 0.25` · `MAX_SINGLE_FACTOR_EXPOSURE 0.40` ·
`MAX_SATELLITE_CAPITAL 0.30` · `MAX_LEVERAGE_CLUSTER_EXPOSURE 0.20` (net debt/EBITDA > 2.5×) ·
`MAX_POLICY_DEPENDENCY_EXPOSURE 0.25` · `MAX_CYCLICAL_PEAK_EXPOSURE 0.30`.
Enforced: `src/governance/constitution.py`, `src/governance/concentration_governor.py`,
`src/phaethon/governance.py` (surfacing only — see §5), `tests/test_portfolio_concentration_governor.py`.

**Warning (soft) thresholds:** `WARN_CORRELATED_CLUSTER_SIZE 4` (≥4 positions at ≥0.70 rolling
correlation) · `WARN_REGIME_DEPENDENT_EXPOSURE 0.40` · `WARN_CONFIDENCE_LOW_FRACTION 0.50` ·
`CONFIDENCE_COMPRESSION_WARN_THRESHOLD 0.50`. Plus code-level (deliberately **not** in the locked
yaml, `docs/BATCH_AUDIT_2026-07-05.md §5`): `WARN_STRONG_BUY_FRACTION 0.20`,
`WARN_EXTREME_TAIL_FRACTION 0.35` in `src/governance/constitution.py`.

**Signal-reliability thresholds:** `MIN_SIGNAL_QUALITY_THRESHOLD 0.45` ·
`SIGNAL_DECAY_LOOKBACK_WEEKS 8` · **`MIN_OBSERVATIONS_FOR_CALIBRATION 20`** (reused as the n-floor
for Phaethon lesson adoption — `src/phaethon/lessons_ledger.py`, explicitly "NOT a new magic number").

**DCF-skepticism thresholds:** aggressive-upside 0.40 · review 0.80 · anomaly 1.20 ·
`DCF_WACC_DESTROYS_UPSIDE_FRACTION 0.50` · `DCF_CYCLE_PEAK_THRESHOLD_DEFAULT 0.25`
(`src/governance/dcf_skeptic.py`).

## 2.3 Protocol lock — `config/protocol_lock.yaml` — **CURRENT** (`locked: true`, `registered: 2026-07-05`)

Covers seven ruleset files (`src/paper_trading.py`, `src/engine/calculator.py`,
`src/signals/momentum.py`, `src/signals/revisions.py`, `config/constitution.yaml`,
`config/settings.yaml`, `config/universe.yaml`) plus a `protocol_sha` over
`docs/OBSERVATION_PROTOCOL.md`. Verified by `scripts/verify_protocol_lock.py` and
`tests/test_protocol_lock.py` (`test_lock_matches_current_repo_state`,
`test_one_byte_tamper_is_detected_and_named`, `test_tamper_in_protocol_doc_is_detected`,
`test_reregistration_restores_green`). **Rule:** never auto-update to go green; change only via
`--register` with the reason logged in `docs/PROTOCOL_CHANGELOG.md`. A `lock_sha` mismatch **halts
the screen** (`OBSERVATION_PROTOCOL §0`).

`config/portfolio.yaml` is **deliberately excluded** from the ruleset files so NAV-accounting
parameters (`paper_nav_start 100000`, `n_target_positions 20`, `paper_cost_bps 20`) can be tuned
without forcing a re-registration — the file says so in its own header.

**Nested live-pilot lock** (added 2026-07-06, commit `0ce82c5`): `live_pilot.locked: true`,
`registered: 2026-07-06`, `protocol_doc: docs/LIVE_PILOT_PROTOCOL.md`, `ruleset_files: null`.
Guarded by `tests/test_live_pilot_lock.py`.

## 2.4 Isolation and ringfence rules — **CURRENT**

| Rule | Enforced by |
|---|---|
| Agent and swing-bot may not import each other | `test_swingbot_and_agent_are_ringfenced` |
| `src/phaethon/` may not reach engine or signals | `test_phaethon_does_not_import_engine_or_signals` |
| Phaethon learning modules unreachable from Phaethon-facing code | `test_learning_modules_unreachable_from_phaethon_facing_code` |
| Learning modules write only human-side paths | `test_learning_modules_write_only_human_side` |
| Live layer holds no broker libs and no decision math; never writes a paper cohort file | `test_live_layer_no_broker_and_no_decision_math` + a filesystem-sandbox test |
| Deploy refuses unless host/hostname contains "trading" (two independent checks) | `test_deploy_sh_has_both_trading_guards` + `scripts/deploy.sh` |
| The two Phaethon arms are never blended into one series | `test_arms_are_separate_series_never_blended` |
| Publish aborts if any personal/account term appears in rendered JSON | `test_sanitize_gate_catches_personal_data` |
| Governance surfaces violations but never clamps | `test_run_governance_does_not_clamp` |
| Weekly push must rebase (avoids collision with the Phaethon daily cron push) | `tests/test_weekly_push_rebase.py` |

## 2.5 Registry / sleeve admission rules — **CURRENT**

- **Sleeve admission (Themis), `config/sleeves/_schema.yaml`:** *"a sleeve may not load without (a) a
  registered, falsifiable hypothesis (`registry_ref`) and (b) non-empty, pre-registered
  `kill_criteria`. No sleeve runs capital — paper or real — without a hypothesis it can fail and the
  numeric conditions under which it will be stopped. There is no default and no exception."*
  Enforced: `src/sleeves/manifest.py`, `tests/test_sleeve_manifest.py`,
  `tests/test_registry_discipline.py`. Stage ≥ S2 must reference a **PASSED** entry
  (`test_s2_testing_ref_fails`, `test_s2_passed_ref_ok`, `test_s2_missing_ref_fails`).
- **Registry append-only hash chain:** `src/research/registry.py::verify_registry_chain` +
  `verify_migration_chain`; editing an immutable field breaks the chain; status advances forward-only.
- **F5 interpretation contract:** every new entry must carry `{licenses, does_not_license}` or fails
  to load (`add_entry`, `tests/test_registry_machinery.py`).
- **F7a counting rule:** the correction denominator `m` counts only TESTING+ entries; REGISTERED
  (Stage-0) is free — *registration is encouraged; initiating a test is what spends credibility*
  (`research/README.md`).
- **F7b double-gate (declared choice):** a candidate must clear **both** Bonferroni significance
  **and** the deflated Sharpe — *"a deliberate double-gate accepting an elevated false-negative rate,
  chosen given this operator's documented history of over-iterating on under-powered results. This is
  discipline, not miscalibration."* (`research/README.md`; `src/research/corrections.py`.)
- **F7d queue:** `registry.py queue` ranks REGISTERED entries by `survival_prior × strategic_fit`;
  informational only — advancing to TESTING is a human act.

## 2.6 Change policy inside an observation window — `docs/OBSERVATION_PROTOCOL.md §6` — **CURRENT**

- **Forbidden mid-window** (forces a re-registered Cohort-2): any change to entry/exit rules,
  universe membership, the cadence table, or rating-engine math.
- **Allowed mid-window:** crash-class bug fixes only, plus reporting/logging/refactors *proven
  output-identical by a golden test*.
- **Calibration-class fixes** (things that move numbers without crashing) are **queued for Cohort-2,
  documented, not applied.** *"Fixing a number mid-window silently re-writes the experiment — so we
  don't."*

## 2.7 Reporting rule — `OBSERVATION_PROTOCOL §7` — **CURRENT**

Legacy Cohort and Cohort-1 must render as two visually distinct sections. **No combined performance
number and no combined chart series — ever.** A build emitting a blended figure is non-conforming and
must fail the report check. Legacy always carries its §1.1 label *"informational only — not evidence
of system validity."*

## 2.8 Constitutional exceptions log — `docs/CONSTITUTIONAL_EXCEPTIONS.md` — **CURRENT**

One entry: **2026-07-05**, `research/revisions_pt_validation/pt_calibration_study.py` was run on the
trading host because `ats-research-simfin` no longer existed. Human-approved; read-only script, no
broker libs, no credentials, no decision-path writes. Explicitly recorded as **not a precedent** —
research returns to a dedicated environment when one is re-provisioned.

## 2.9 Council-design rules — `(LAPTOP-LOCAL)`, `Olympus_Build_Prompt_v1.2.md` §2, §6–§9 — **CURRENT as design constraints, UNENFORCED in this repo's tests**

These are the binding rules for any council/agent layer and are the most directly relevant prior art
for a redesign:

- **§2.1 Paper-only** — all outputs paper/simulated/recommendation-only.
- **§2.2 Human final authority** — every actionable recommendation must end *"Human authorisation required."*
- **§2.3 No live broker integration** without a separate explicit prompt.
- **§2.4 No autonomous optimisation** — no ML optimisation, RL, self-modifying strategies, automatic
  rule updates, or autonomous model promotion. *Learning is observational only.*
- **§2.5 Build small first** — *"Do not scaffold 16 functional gods… Complexity must be earned."*
- **§6 Aeolus/Hades trap rule** — no regime-based sizing in the MVP; any macro/regime module stays
  observational until it earns authority forward. *Macro may inform commentary; it may not alter
  position sizing until validated.*
- **§7 Correlated-council rule** — *"Zeus must not increase confidence merely because several modules
  agree if those modules share inputs, data, model, or reasoning chain."* Reports must carry a
  shared-input warning and an evidence-independence assessment. (This rule **fired in the one real
  decision** — see §3, ORCL.)
- **§8 Benchmark & ETF-alternative rule** — every single-name recommendation must answer *"Why own
  this rather than the cheapest relevant ETF?"* If it cannot, reduce confidence or HOLD/WATCH.
  Explicitly encodes the cost-access lesson (§4B).
- **§9 Core+satellite rule** — candidate exposure is judged against the satellite book **and** the
  operator's real-money core; duplication must be flagged.

---

# 3. Cohort / sleeve history

| Cohort / arm | Inception | Lock / window | State at this location (2026-09-01) |
|---|---|---|---|
| **Legacy Cohort** (`legacy_pre_fix`) | 12 positions opened **2026-05-25** under the pre-fix engine | No gates, no kill criteria. Sunset rule §1.2: **forced close 2026-08-23** (open + 90 days), tagged `forced_sunset`, not counted as an exit signal | **12 positions still open** in `data/paper_positions.yaml`, all `legacy_pre_fix`, all opened 2026-05-25. **⚠ The 2026-08-23 forced sunset has NOT executed here — 9 days overdue.** Mechanism exists (`LEGACY_SUNSET_DATE = date(2026,8,23)` in `src/paper_trading.py`, re-registered 2026-07-05) but it only fires inside `process_screener_results`, and **no screen has run since 2026-05-26** (`runs/_screen/` latest = `20260526_140059`). See §8 Q-01. |
| **Cohort-1** / sleeve `oracle_v1` | Defined as the first screen run under the locked ruleset (`OBSERVATION_PROTOCOL §2.1`) | Lock registered **2026-07-05**; window **52 weeks**; `exit_rules_v2` ACTIVE, params frozen (`pt_fraction 1.0`, `max_hold_days 270`, `stale_days 28`); precedence `RATING_DOWNGRADE > PT_HIT > TIME_STOP > STALE`; benchmark SPY TR | **0 positions, 0 closed trades** (`data/paper_trades.jsonl` **absent**). Sleeve stage **S1** (downgraded from S2 on 2026-07-05 because hypothesis 003 is TESTING, not PASSED). Unchanged since the 2026-07-06 snapshot flagged it. **The 52-week evidence clock is registered against an empty book.** |
| **Phaethon Arm A** (`phaethon_a`, "Disciplined (A)") | Mandate verbatim: *"research-grade discipline"* | No kill switch (`kill_switch: "n/a (disciplined arm)"`); benchmark QQQ (primary) | **14 positions, 66.5% cash, 33.5% gross — CONFORMING**, `as_of 2026-08-31`, 75 marks, active return +8.35%, vs QQQ +9.32pp, trend **DEGRADING vs QQQ** (`docs/data/phaethon_live.json`). |
| **Phaethon Arm B** (`phaethon_b`, "Aggressive (B)") | Built/isolated/live **2026-06-07** `(LAPTOP-LOCAL: NEXT_STEPS.md)`; mandate verbatim: *"+10%/qtr, concentrated"* | Kill switch **−25% peak-to-trough**; relaxed gate (bar 65→50, caps widened) with Zeus still governing risk; Goodhart guard: learning keyed on realized return vs QQQ, never on the +10% target `(LAPTOP-LOCAL)` | **10 positions, 13.1% cash, 86.9% gross — CONFORMING**, `halted: false`, drawdown −2.8%, 50 marks, active return +12.48%, vs QQQ +11.12pp, trend **IMPROVING vs QQQ** (`docs/data/phaethon_b_live.json`). |
| **Olympus MVP arms A / B / C** `(LAPTOP-LOCAL)` | `olympus/data/arm_{A,B,C}_portfolio.json`, all `as_of 2026-06-04`, core_value 10000 each | Arm C is the walled-off naive-screener benchmark arm (`forward_scorecard.md`) | Frozen at 2026-06-04. **Arms A and B hold identical satellites** (TSM/AMD/NV… at identical 1.7 shares, price 100.0) and **all three carry negative cash** (A/B −1368.40, C −1197.35) — the same cash-accounting failure mode later diagnosed in Phaethon Arm B (§5). See §8 Q-06. |
| **Legacy `paper_portfolio.json`** `(LAPTOP-LOCAL)` | `olympus/data/paper_portfolio.json`, `as_of 2026-06-04` | — | core 77,513.95, satellite VRT + SMCI — the "Jaccard 1.0, one bet in many coats" holdings named in `olympus_system_review.md`. |
| **Gaia** (passive core) | Rules **locked 2026-06-07**, `lock_sha f6592d14e2046481` (`gaia/rules.yaml`) | Rebalance band **5pp**, monthly schedule, *"mechanical DISCIPLINE, never condition-timing"*; glidepath **disabled**, current tier 8, steps 2035→tier 7, 2040→tier 6, horizon-driven not market-driven | Locked, unchanged. Real allocation is gitignored (§C). |
| **swing-bot** | First paper run **2026-05-25** | **6-month auto-disable `disable_date: 2026-11-25`** (hard rule #9, `SYSTEM_AUDIT_2026-05-25.md §1.9`); `paper_only: true` immutable; `alert_mode_only: true`; `hard_kill_pct: −20.0` | Verdict **NO_GO** (§4B). Cron entries disabled 2026-06-08 `(LAPTOP-LOCAL: INFRA_INVENTORY.md)`. Auto-disable date not yet reached. |

**Only one sleeve manifest exists** (`config/sleeves/oracle_v1.yaml`). The framework supports many;
the second has never been written (`OLYMPUS_SYSTEM_STATE §6(a)`).

---

# 4. Research registry — IN FULL

## 4A. `research/registry.yaml` — every entry, verbatim fields

### Entry `001` — created 2026-07-05 — status **FAILED**
- **Hypothesis:** "12-1 month cross-sectional momentum predicts forward excess return in large-cap US
  equities: Q1-Q5 monthly net spread > 0 with Newey-West t >= 2.0."
- **Mechanism:** "Underreaction to persistent fundamental trends by attention-constrained investors;
  the counterparty is a disposition-prone holder who sells winners early and holds losers. The edge
  erodes as the trade crowds and as turnover costs bite."
- **Universe:** large-cap US equities (`config/universe.yaml`). **Window:** monthly rebalance,
  2018-2024 backtest. **Metric:** Q1-Q5 monthly net-of-cost spread; Newey-West HAC t-stat (lag 6).
- **Threshold:** net spread > 0 AND t >= 2.0.
- **analysis_plan_sha:** `5d2f34ef…39b38` · **content_hash:** `99093ba8…5d477c` · **prev_hash:** all-zero (chain head).
- **Result:** `research/momentum_validation/MEMO_momentum.md`. Status event 2026-07-05 → FAILED.
- **Interpretation contract (backfilled 2026-07-06):** *licenses* — a tradeable long-short quintile
  spread net of costs in this large-cap universe over the tested 2018-2024 window; *does not license*
  — any claim about momentum's cause, its persistence beyond this universe/window, or its survival at
  other cap sizes or rebalance frequencies.
- **Actual finding** (`MEMO_momentum.md`, 2026-07-05, data 2015-01..2025-12, 20 bps/side): Q1−Q5
  spread **+0.032%/mo ≈ +0.38%/yr, Newey-West t = 0.09** (lags 4, n = 121). Q1 18.3% ann / Sharpe
  1.06; Q5 17.2% / 0.88; **Universe EW 18.0% / Sharpe 1.13 — the best of the four**; SPY TR 14.5% /
  0.98. Q1 beat SPY in 58.7% of months. Momentum provides **essentially no quintile sorting** in
  these 147 names. Survivorship honestly accounted: absolute levels biased **up**; spread sign
  ambiguous but likely *deflated*, so no plausible correction rescues significance.
  **Decision: neutralize momentum to observation-only** — quintile is still computed and logged for
  attribution but no longer moves entry confidence (`src/signals/escalation.py` always NEUTRAL;
  `src/signals/momentum.py` carries an OBSERVATION-ONLY docstring note).

### Entry `002` — created 2026-07-05 — status **FAILED**
- **Hypothesis:** "Post-earnings-announcement drift: large positive earnings surprises are followed by
  positive net-of-cost excess return over the drift window in the traded universe."
- **Mechanism:** "Slow information diffusion and analyst anchoring leave surprises under-priced at the
  event; the counterparty is the under-reactor. In liquid large caps the drift is largely arbitraged
  away, so net-of-cost edge is thin."
- **Universe:** US equities with scheduled earnings events (swing-bot universe). **Window:**
  event-driven backtest. **Metric:** mean net-of-cost excess return over the drift window vs
  benchmark. **Threshold:** positive net excess clearing the significance bar.
- **analysis_plan_sha:** `a613b487…e800b46` · **content_hash:** `537f95c3…3973e1` · **prev_hash:** `99093ba8…5d477c`.
- **Result:** `swing-bot/backtest/PEAD_RESULTS.md`. Status event 2026-07-05 → FAILED.
- **Interpretation contract (backfilled 2026-07-06):** *licenses* — an exploitable net-of-cost drift
  after large positive earnings surprises in the tested event universe; *does not license* — any claim
  that the drift generalizes to negative surprises or other universes, or persists against the
  arbitrage documented in the result.
- **Actual finding** (`PEAD_RESULTS.md`, generated 2026-05-25, window 2024-01-01→2025-12-31, 3,797
  earnings events → 390 candidates → **122 trades**, 10,000 bootstrap sims): win rate **40.2%**, avg
  win +14.71%, avg loss −9.77%, **expected return +0.06%/trade, profit factor 1.01×, annualised
  +0.4%** against **SPY +48.9%** over the same window. P(hard kill ≤ −20%) = 19.4%. Exits:
  69 stop-loss vs 39 profit-target. Sensitivity on the EPS-beat threshold (3/5/7/10%) shows the
  default 5% is the **worst** cell (PF 1.01, P(kill) 20.2%) while 3% shows PF 1.26 — i.e. the
  parameter surface is noise, not signal.

### Entry `003` — created 2026-07-05 — status **TESTING** (open)
- **Hypothesis:** "STRONG_BUY-gated entries (MED/HIGH confidence) beat SPY TR net of costs over a
  52-week window, per the pre-declared OBSERVATION_PROTOCOL §5 success gate."
- **Mechanism:** "A causal-reasoning rating engine emits ratings with a pre-logged falsifiable
  invalidation line; the tested claim is that its STRONG_BUY gate carries information vs SPY TR. Per
  §3 power reality a 52-week window CANNOT establish alpha != 0 (realistic skill alpha ~1-4%/yr sits
  below the ~8-16% ann. detection floor); it establishes process integrity, cost realism, and a
  ~30-60-trade calibration sample. No counterparty edge is asserted beyond the engine's rating skill."
- **Universe:** ~20-stock equal-weight book from the locked universe, benchmarked vs SPY TR.
  **Window:** 52 weeks. **Metric:** TWR vs SPY TR (dividends included); Information Ratio; hit-rate of
  closed trades; PT-calibration Spearman.
- **Threshold (SUCCESS, all at ≥52wk):** IR ≥ 0.5; Max-DD ratio ≤ 1.2; PT-calibration Spearman ≥ 0.30;
  hit-rate ≥ 50% over ≥30 closed trades; zero process violations.
- **analysis_plan_sha:** `28b02e6d…6df2605` · **content_hash:** `765840bd…67594a8` · **prev_hash:** `537f95c3…3973e1`.
- **Result ref:** `docs/OBSERVATION_PROTOCOL.md` — **no result; window mid-flight and the book is empty** (§3).
- **Interpretation contract (backfilled 2026-07-06):** *licenses* — process integrity, cost realism,
  and a calibration sample; a PASS would license only "the STRONG_BUY gate cleared the pre-declared §5
  gates over one 52-week window"; *does not license* — any claim that alpha != 0 is statistically
  established, or that the result generalizes beyond the single observed window.

### `migrations` block — one event — 2026-07-06
`type: backfill_interpretation_contract`. Note verbatim: *"F5: interpretation_contract added as a
required field; backfilled onto pre-existing 001-003 via append (entries NOT edited)."*
`prev_hash` all-zero · `hash e535fb6e…528b65b9`. Both chains verify independently.

### Registry statistics (as printed on `main` @ `73be0ab`, `OLYMPUS_SYSTEM_STATE §4`)
`m (correction denominator, TESTING+) = 3` · total entries = 3 · **Bonferroni alpha = 0.0167** ·
**pass rate (resolved) = 0.00% (0/2)** · queue empty (no REGISTERED entries).

## 4B. Pre-registry falsification record `(LAPTOP-LOCAL: lessons_learned.md 2026-06-02, olympus_system_review.md, design notes)`

Not in `registry.yaml` — these predate it. Recorded here because they are the binding prior art on
what has already been tried and killed.

| Strategy | Bet | Verdict | Reason | Status |
|---|---|---|---|---|
| **RP / reversion (ATS QRE)** | US-equity price-pattern/reversion | CLOSED — no active edge | Honest baseline win-rate **19.86%** vs claimed **66.17%**; discrepancy **never reconciled**; all QRE models closed | **FAILED / unresolved** |
| **Apollo / SCAI-II** | Thematic AI-infrastructure structural momentum | Unvalidated; **selection adds nothing** | *"Static basket dominates"* the active selection; 1 live position; AI-regime monoculture; never scored against its own theme calls | **OPEN QUESTION** (§8 Q-07) |
| **Mercury / Kairos** | Post-earnings drift, liquid names | Parked — ~null **by design** | Drift lives in small/illiquid/under-covered names; the liquidity filter removes exactly those. The pre-registered prior was confirmed | **FAILED (as predicted)** |
| **Nike / MOM_TOP5** | Long top-momentum US basket | Marginal, regime-dependent, **in-sample only** | ~+6pp/yr in-sample, survivorship ~10×, bull window; "alpha vs QQQ" suspect when picks are QQQ constituents. Live OOS started 2026-06-30 | **OPEN** |
| **Iris / ESE** | STRONG-tier 8-K events | **Fair-weather** | bull ≈ +14% vs passive; bear −10.0% vs −7.1%; survivorship-flattered; *"two periods is not proof."* Live OOS started 2026-06-01. Hit rates: partnership 58%, contract_win 54%, capacity 53%, guidance_raise 22% | **OPEN / marginal** |
| **Demeter / val_v1** | Cross-sectional value, sector-neutral | In-progress, no verdict (**THIN**) | "likely junk-loading"; decorrelation check was pending ~Oct 2026 | **OPEN** |
| **Hades** | Automated crash/regime **de-risk overlay** | **FALSIFIED 2026-05-29** | Look-ahead was the whole win; under a 1-day lag always-invested wins. Net-negative on **all 8 episodes** once recovery counted (GFC SPY: +21.8pp avoided vs −39.5pp recovery missed = −17.7pp; SMH dot-com −70.3pp). −1.2 to −1.5pp/yr in calm markets | **FAILED.** Detector retained as a logged signal only; exposure action retired. **Reframed 2026-06-01** as a human-in-the-loop master kill switch that surfaces context at ~−20% drawdown and never auto-sells; default lean "hold through unless structural" |
| **Caerus** | Short-horizon catalyst-momentum (8-K + momentum/rel-vol/gap) | **FALSIFIED 2026-06-02** on its pre-registered kill-check | PIT backtest 2024–26, 45 trades: mean net **−0.43%/trade**; beat own buy-and-hold by only +0.30pp (only 20% of trades beat holding; Monte-Carlo straddles zero); **lost to a random liquid-mover control by −1.59pp** — the catalyst is anti-predictive. Stops fired 3× the take-profits | **FAILED.** Droplet `/root/caerus` dormant, no cron, no feed |
| **Nemesis** | Short-horizon mean-reversion (market-neutral CFD + long-only ISA) | **FALSIFIED 2026-06-02** | Signal **real gross (~+17.5%/yr spread)** but CFD overnight financing (~6%/yr) crushed it to net +2.5%/yr with a luck band straddling zero; long-only lost to holding the index | **FAILED** |
| **Plutus** | FX carry / trend / value, G10, CFD | **FALSIFIED 2026-06-02 (all three, multiple-testing corrected)** | Carry +2.4%/yr and value +1.9%/yr are **real gross premia** but the ~2%/yr CFD swap markup ate them whole; trend negative even gross | **FAILED** |
| **Phobos** | Volatility / variance premium | **SHELVED** — not buildable on free data | SPX-level short-vol ≈ long-risk (not orthogonal, fat-tailed); single-stock vol forward-only/blocked | **BLOCKED (data)** |
| **swing-bot** | 8-K event bot, +10%/−5% brackets | **NO_GO** | Same 8-K event family; M&A-concentrated; tight exits + costs | **FAILED** (rejected pre-live) |
| **Metis** | Once-daily LLM agent, leaderboard contestant | **PARKED / cancelled 2026-06-02** | Cost was never the blocker (£1–10/mo); evidence prior against LLM traders. Superseded by Phaethon | **SUPERSEDED** |

**Grouped failure modes with counts** (`lessons_learned.md`): (1) survivorship + single-regime
flattery — *system-wide contaminant*, primary in ~4; (2) selection adds nothing over passive/random —
**3 clean cases**; (3) already-priced / structurally late — 3–4; (4) look-ahead / measurement artifact
— **2 clean kills** (Hades, RP); (5) costs eat the edge — 3+; (6) below-noise-floor — primary in
Mercury; (7) data ceiling — Phobos, Kairos, RP.

**Two durable findings, stated as the corpus states them:**
- **The cost-access pattern (2026-06-02):** across Caerus, Nemesis, and Plutus the edges were **not
  absent — they were real gross and captured by retail trading costs.** *"The edge isn't missing —
  the broker takes it."* Implication: the real premia (value, carry, momentum, quality) are **cheaply
  ownable via low-cost factor funds (~0.2–0.5%/yr), not DIY-tradeable at ~2%/yr** in retail
  spread/financing/swap. Capture them cheaply; don't trade them expensively.
- **The one durable lesson:** the only two conclusive kills came from **the harness, not cleverer
  strategies** — *remove look-ahead, count every cost, benchmark net-of-cost against a random/passive
  control with a Monte-Carlo luck band.* That harness is the project's real asset. The strategies
  were *"ten coats on one already-arbitraged bet."*

**Untried by elimination** (structurally different, none built): mean-reversion (Nemesis — now
falsified in its CFD form), FX/carry (Plutus — falsified in its CFD form), commodities/real assets
**held not timed** (Hephaestus), quality/durability (Hestia), volatility (Phobos — blocked).
Priority order when a slot is earned: **Nemesis → Plutus → Hephaestus** (`pantheon_naming_map.md`).

## 4C. Studies that are not registry entries

**Study A — EPS-revisions signal** (`research/revisions_pt_validation/STUDY_A_revisions_memo.md`,
2026-07-05) — **OPEN, clock running.** yfinance `eps_trend` returns **only current snapshots**, so a
true historical backtest is **impossible**; no defensible free point-in-time source exists, and
proxy-backtesting on an unreliable feed was **explicitly refused** ("that would manufacture a false
result"). Resolution: start forward-logging now — `scripts/log_eps_trend.py` →
`data/eps_trend_history.jsonl`, weekly, logging only, no `src/` change; began **2026-07-05** (README
status). Power sketch: ~21 independent monthly cross-sections needed, ~30 with HAC inflation →
**first weak read ~12–18 months out (≈2027-07 to 2028-01); robust test ~2.5–3 years.**

**Proxy PT-calibration study** (`research/revisions_pt_validation/FINDINGS_pt_calibration.md`,
2026-07-06) — **COMPLETE, does not resolve 003.** Full run 1,029 ticker-years, **711 OK**. Rank IC
**+0.136 (all, p=0.0003, n=711)** / **+0.097 (ex-flagged, p=0.019, n=591)** — both significant, both
**well below the §5 bar of ≥0.30**. STRONG_BUY-band forward excess: median **+5.3% (all)** but
**−0.3% (clean subset, n=45)** against a mean of +9.4% — *"the typical STRONG_BUY-band outcome is
essentially zero; the mean is carried by a small number of large winners."* Removing invariant-flagged
rows cut the mean +22.7% → +9.4%. Decile ordering **non-monotonic** — signal concentrated in D7–D8,
D9–D10 fade. Caveats stated in the memo: it is a **fixed EV/EBITDA = 10 proxy, not the live engine's
price targets**, and it **neither passes nor fails entry 003** — the two are different experiments.
**Conclusion: a weak, fragile, proxy-level positive; the entry gate remains UNVALIDATED at the
standard this system requires.** §6 notes (does not propose) a possible Stage-1 study on the real
engine's PTs — an open operator decision, deliberately not registered (§8 Q-04).

## 4D. Known bugs — `KNOWN_BUGS.md` (all calibration-class; none affect order placement or hard rules)

Bug classes (mandatory on entry): **unit** / **label** / **cohort** / **plumbing**.

| ID | Status | Class | Summary |
|---|---|---|---|
| BUG-001 | **FIXED** | label | SUM delisted (acquired by Quikrete 2024) → removed from universe + peer groups |
| BUG-002 | **FIXED** | unit | AVAV PT ~$148M/share — dollars↔$mm mismatch; conversion threshold `>1e9` → `>1e6` |
| BUG-003 | **OPEN** | cohort | **LMT/MA price target floored to $0, confidence=BROKEN.** Peer EV/EBITDA calibrated to EPC/industrial produces negative equity for financial-services/mega-cap-defense names. Workaround: `assess_confidence` returns BROKEN for PT ≤ 0, suppressing actionability. Proper fix = per-sector multiple calibration (Path B), **not done** |
| BUG-004 | **FIXED** | label | HON-class conglomerates: `gross_profit=None` → EBITDA underestimated ~67%; label map expanded + computed fallback |
| BUG-005 | **FIXED** | cohort | LLY-class: peer multiples unrepresentative; cohort-outlier detection (target EV/EBITDA > 1.5× peer median → confidence capped at LOW, rating unchanged) |
| BUG-006 | **FIXED** | label | Health-insurer gross-profit inflation (UNH PT ~$4,583 vs ~$290); medical-costs label map + >70% GM back-compute guard |
| BUG-007 | **FIXED** | plumbing | `run_pipeline.py` argparse defaults bypassed the live peer fetch; defaults → `None` |

---

# 5. Phaethon

## 5.1 Identity and both arms' mandates — **CURRENT**

Phaethon is an **isolated, forward-only LLM idea-generation experiment**, paper, two arms
(`src/phaethon/__init__.py`). The **strategy is FROZEN and lives outside this repo** (the trader
writes `scorecard_public.json` / `book.json` under `/home/phaethon/phaethon/trader{,_b}/state` on the
droplet); the repo owns only the **publish path** — render, governance checks, cohort tagging.

- **Arm A — "Disciplined (A)"**, cohort `phaethon_a`, mandate verbatim **"research-grade discipline"**.
- **Arm B — "Aggressive (B)"**, cohort `phaethon_b`, mandate verbatim **"+10%/qtr, concentrated"**,
  kill switch **−25% peak-to-trough**. Built and isolated 2026-06-07 with a separate
  instance/image/book/memory (`trader_b/`), relaxed gate (bar 65→50, caps widened) with Zeus still
  governing risk, and a **Goodhart guard: learning is keyed on realized return vs QQQ, never on the
  +10% target** `(LAPTOP-LOCAL: NEXT_STEPS.md)`.

Benchmark decision (`docs/PHAETHON_BENCHMARK_MEMO.md`, 2026-07-05): **one primary benchmark per book,
dual display allowed.** Phaethon → **QQQ primary** (mandate-appropriate for concentrated growth/tech);
Olympus → **SPY TR primary** (already pre-registered in `OBSERVATION_PROTOCOL §4`). Never an unlabeled
number, never a blended cross-book comparison. Implemented as labeling only —
`benchmark_primary: "QQQ"` and `benchmark_headline` fields; **no returns were recomputed.**

## 5.2 The cash-accounting bug and its fix — **FIXED / CURRENT**

`docs/PHAETHON_ARM_B_LEDGER_MEMO.md` (2026-07-05). Reconstructed from `trader_b/state/book.json`
(17 holdings, `cash: −3834.5`, `peak_value: 10715.4`): implied starting capital
`−3834.5 + 13994.5 = 10160`. The 2026-06-24 batch reached **95.0%** invested over 11 positions; PLTR
was the **first breach at 100.9%**; the 06-29 rebalance added FSLR/ENPH/REGN/JPM/ISRG, ending at
**137.7%**. Σ cost basis **$13,994 on $10,160** → **138% gross, cash −38%**.

**Exact defect** (pinpointed, not guessed): cash **is** debited on every fill — the bug is that
**position sizing never caps cumulative buys against remaining available cash**. Each buy is sized to
a target %-of-**NAV** weight using full book value as the denominator, so the second rebalance sized
5 new positions as if cash were available and funded them by driving cash negative. **Not** a
unit/notional mismatch and **not** a missing debit. Operator determined it was a **bug, not intended
leverage**, before the memo was written.

**Fix:** `src/phaethon/ledger.py` — replay fills in order with a **hard available-cash cap**; a buy
exceeding current cash is **rejected/flagged, never executed into negative cash**. Applied on every
publish (`assemble_arm(restate=True)`) so `cash_pct ∈ [0,100]` and gross ≤ 100%. A within-cash book
(Arm A) is unchanged — no false rejections. Proven by `tests/test_phaethon_ledger.py`.
**Restatement:** Arm A unchanged (was within cash) → 38.0% gross / 62% cash CONFORMING; Arm B →
**94.8% gross / +5.1% cash**, with **6 over-cash buys rejected** (PLTR, FSLR, ENPH, REGN, JPM, ISRG).
Originals archived at `docs/data/archive/phaethon_{live,b_live}_pre_restatement_2026-07-05.json`.

**Stated limitation:** balance-sheet figures were restated with full fidelity, but a full
**return-series** restatement (active-return / vs-QQQ recomputed over corrected holdings) needs the
trader's per-mark price history and **was not done** — a follow-up if the operator wants it.

**Two document states on the restatement date — both recorded:** the memo and
`docs/OLYMPUS_SYSTEM_STATE.md §3` say **"restated 2026-07-05"**; the **live JSON read directly today
says `"restated": "restated 2026-08-31, cash-accounting bug fixed"`** in both arms. The **live JSON is
current** — the string is re-stamped by each governed publish, and the 2026-07-05 memo describes the
first restatement.

## 5.3 The concentration trim — **CURRENT, live status confirmed by direct read**

The cash bug had been **masking an independent position-limit breach**. Post-restatement Arm B was
still NONCONFORMING on **concentration** (memo §4: CEG 13.5%, GOOGL 13.8% > `MAX_SINGLE_POSITION` 0.10)
— *"the aggressive arm's 'concentrated' mandate collides with the constitution's 10% cap."*

**Trim executed 2026-08-07** (commit `c9d53c6`, author `Phaethon Panel <noreply@ats>`): CEG 13.4%,
AMZN 11.5%, MSFT 11.4% each reduced to **exactly 10%**, excess released to cash and **never
redistributed** (redistribution is explicitly deferred as "a separate, later cash-deployment feature"
— `src/phaethon/rebalance.py` docstring). Arm B **93.2% gross / 6.88% cash → 86.9% gross / 13.1%
cash, CONFORMING.** Pre-trim state archived at
`docs/data/archive/phaethon_b_live_pre_trim_2026-08-07.json`; `trim_log` written onto the live JSON.
Machinery: `src/phaethon/rebalance.py::trim_to_cap` (pure), operator script
`scripts/phaethon/trim_arm_b_to_cap.py` (the only real book mutation), 5 new tests plus
`test_archived_pre_trim_arm_b_shows_original_concentration_breach` locking the pre-trim breach into
the audit trail.

**Root cause found at the same time and worth its own line:** the same commit records that the
2026-07-05 governance/restatement pipeline (`publish.py`, `ledger.py`, `governance.py`) **had never
actually been wired into production** — the droplet cron was still running the old ungoverned script,
so **NONCONFORMING had never once surfaced on the live dashboard.** `c9d53c6` was the *first real run
of the governed pipeline against production state* (Arm A picked up cohort tags and a status field
for the first time, values unchanged). See §7 D-11.

**Live status read directly from `docs/data/phaethon_b_live.json` (not from memory), `as_of 2026-08-31`:**

```
status: CONFORMING · governance.conforming: true · violations: [] · gross_exposure_pct: 86.9
n_positions: 10 · cash_pct: 13.1 · halted: false · drawdown_pct: −2.8 · kill_switch: −25% peak-to-trough
n_marks: 50 · active_return_pct: +12.48 · vs_qqq_pp: +11.12 · trend: IMPROVING vs QQQ
restated: "restated 2026-08-31, cash-accounting bug fixed" · restated_rejected_over_cash: []
holdings (weight_pct): CEG 10.0 · MSFT 10.0 · AMZN 10.0 · ANET 9.6 · FSLR 9.1 · REGN 8.9 ·
                       PLTR 7.5 · VST 7.4 · GEV 7.3 · JPM 7.1
```

Three holdings sit **exactly at** the 10.0% cap — at the boundary, not over it. `rejected_over_cash`
is now **empty**, i.e. the current book needs no rejections. **Arm B is CONFORMING as of 2026-08-31.**

`docs/data/phaethon_live.json` (Arm A, same date): 14 positions, **CONFORMING**, gross 33.5%, 75
marks, active return +8.35%, vs QQQ +9.32pp, **trend DEGRADING vs QQQ**, `halted: null`,
`kill_switch: "n/a (disciplined arm)"`.

## 5.4 Frozen prompt / boundary ceremony — **CURRENT**, and why

`docs/PHAETHON_LEARNING_DECISION.md` (2026-07-05) is the settled answer to *"should Phaethon learn
from its own trades?"* Verdict: **`NO_LIVE_PNL_LEARNING`'s bright line stays** — no outcome data in
any prompt or context, no mid-window policy change, no automated adjustment, ever. What was **added**
is the named channel **`OUTCOME_LEARNING_VIA_BOUNDARY_ONLY`**:

1. **Trigger (changed from calendar to information):** review eligible at **≥25 closed trades since
   the last boundary AND ≥13 weeks elapsed** — both, not either (`src/phaethon/review_trigger.py`).
2. **Input — the lessons ledger:** every candidate lesson emitted **with its n, statistic, and
   p-value/CI**, including failures marked *"insufficient — carried forward."* Meta-level only, never
   per-ticker. Adoption bar: binomial p < 0.05 vs a 50% null **or** a calibration gap whose CI
   excludes zero, **AND** n ≥ `MIN_OBSERVATIONS_FOR_CALIBRATION` (20, from the constitution — *"NOT a
   new magic number"*). (`src/phaethon/lessons_ledger.py`.)
3. **Change budget: maximum 2 adopted lessons per revision** — wholesale rewrites are structurally
   impossible, which keeps v_n → v_n+1 interpretable.
4. **Forward prediction:** every adopted lesson ships a falsifiable prediction resolved at the next
   review; unresolvable ones are **AMBIGUOUS = a defect in the prediction**, logged as such, not a
   null result (`src/phaethon/prediction_resolution.py`).
5. **Firewall unchanged:** all of it is human-side; the model learns only by receiving a new frozen
   prompt at a boundary.

**Kill criterion for the learning mechanism itself** (`src/phaethon/learning_kill_switch.py`):
suspended — reverting to annual calendar reviews with the ledger observing only — if across any 4
consecutive cycles **(a)** ≥50% of resolved forward predictions resolve FALSE (AMBIGUOUS excluded), or
**(b)** a lesson is adopted, reversed, then re-adopted (**oscillation** — the signature of tuning to
noise). Suspension writes `data/phaethon/LEARNING_SUSPENDED`; reinstatement needs its own
re-registration with a diagnosis.

**Why (the reasoning, in one place):** at ~2–4 closures/month across 4–6 thesis categories the
per-category sample at any review is **2–5 observations** — nothing statistically real to learn from.
Detecting 55% vs 45% needs ≈380 resolved trades per category; even 65% vs 35% needs ≈40. A
continuous learner would therefore be **fitting noise with a fluent narrator attached** — and an LLM
is a superb rationalizer, removing the fatigue/embarrassment friction that stopped the human version
of this loop at 80 iterations. Fed its own losses it reproduces the behavioural patterns saturating
its training data (loss aversion, recency chasing) — tuning to noise *in the worst documented
directions*. And the system-level cost outweighs all of it: **continuous adaptation destroys window
interpretability, which destroys the forward record, which is the only path Phaethon has to live
capital.** Stated plainly in the memo: *"if the aim is Phaethon eventually holding live capital,
freezing is the fast path, not the slow one."*

**Status of the mechanism: BUILT, NEVER RUN.** `OLYMPUS_SYSTEM_STATE §6(c)2` records
`data/phaethon/` and `runs/phaethon/` as empty — no journal, no lessons ledger, no review artifact,
no `LEARNING_SUSPENDED`. Confirmed unchanged at this location.

**Design-level priors that still stand** (`phaethon_design_note.md`, concept 2026-06-04): Phaethon
**cannot be backtested** — the hindsight is in the model's weights, not the prompt; *"the
world-knowledge that makes an LLM worth using IS the contamination."* Showing it history ≠ learning.
**Goodhart risk:** a self-learner pointed at a fixed governance filter learns to game the filter.
Evidence prior: LLM trading agents mostly lose. Honest prior going in: *it will probably lose to
passive* — the forward parallel run settles it with evidence instead of assumption.

## 5.5 Current cash_pct — **FLAGGED**

| Arm | cash_pct (2026-08-31) | Last figure recorded in a `docs/PHAETHON_*.md` | Δ |
|---|---|---|---|
| Arm A | **66.5%** | 62% (`PHAETHON_ARM_B_LEDGER_MEMO §4`, restated 2026-07-05) | **+4.5pp** |
| Arm B | **13.1%** | 5.1% (memo §4) → 13.1% after the 2026-08-07 trim (commit `c9d53c6`) | as expected |

**Arm B's 13.1% is explained and intended**: the trim releases excess to cash and deliberately does
not redistribute it. **Arm A's 66.5% is not explained by any document in this corpus.**

**No `docs/PHAETHON_*.md` file states a deployment target, target cash level, or minimum invested
percentage for either arm.** So the flag is stated precisely rather than against an invented bar:
Arm A is **two-thirds in cash**, is **1.5pp further into cash than at its last documented
restatement**, and is simultaneously **DEGRADING vs QQQ** — the combination a reader would want
explained, and there is no document that authorises or explains it. Recorded as **OPEN — §8 Q-05**,
not as a violation: nothing in the constitution or the protocol caps cash.

---

# 6. Live pilot — E1

**Status: DESIGNED, BUILT, HASH-LOCKED, DRILLED, UNFUNDED, NEVER STARTED.**

## 6.1 Design — `docs/LIVE_PILOT_PROTOCOL.md` (2026-07-06, "DRAFT for hash-lock")

- **Stage E1** — the system proposes order cards; **a human places every order.** Start: **November
  2026.** Duration: **13 weeks**, with a **pre-declared week-13 review** whose decision rule
  (continue to a re-registered pilot-2 / stop / extend) is fixed in advance and decided **against the
  §4 operational criteria only, never against return**. No mid-pilot lengthening on results.
- **What it can and cannot claim (§1):** *"At the start of this pilot, the statistical evidence that
  this system generates alpha is effectively zero."* Outperformance vs SPY is **not claimable at the
  start and will not become claimable during the pilot** at this capital and duration — a positive or
  negative return over the pilot is **noise**. *"This is a live rehearsal of the machinery, not a bet
  on returns."* Capital is **tuition** — money the operator is prepared to lose in full.
- **Success criteria — all operational, returns explicitly excluded (§4):** (1) 100% intent/fill
  reconciliation, zero unreconciled orders; (2) realized slippage within **±10 bps/side of the modeled
  20 bps/side**; (3) **zero** guard violations; (4) zero unexplained data gaps; (5) all drills passed
  pre-start (halt, kill, reconciliation, data-outage).
- **Non-goals (§6):** no scaling intra-pilot; **no automation beyond E1** (`execution_stage: E2`
  cannot even parse under the current constitution — it requires constitution v3); **no Phaethon
  routing** unless Phaethon's own onboarding protocol is separately drafted and hash-locked.
- **Relationship to Cohort-1 (§7):** Cohort-1 continues to its full 52-week window **completely
  untouched**; the pilot does not terminate/pause/shorten/modify it, does not borrow or cite its data
  in either direction, and produces **operational evidence only**. Separate books, separate evidence
  ledgers.
- **Termination (§8):** on cumulative kill, any definitively failed §4 criterion, a week-13 "stop", or
  operator halt. Then freeze → reconcile → **write the post-mortem** → decide deliberately; nothing
  carries forward automatically.

## 6.2 Guard layer — `config/live_limits.yaml` (v1.0, effective 2026-07-06) + `src/live/`

| Key | Value today | Meaning |
|---|---|---|
| `execution_stage` | **E1** | Enum E0/E1 only; the loader **rejects E2** |
| `MAX_LIVE_CAPITAL_GBP` | **0** | Placeholder = **pilot not funded**; the loader refuses to generate order cards while 0. Changes **only** by re-registration — *"never intra-pilot, never by the system, never 'just this once' to average down or press a winner"* |
| `MAX_SINGLE_POSITION_LIVE` | 0.10 | |
| `MAX_ORDERS_PER_WEEK` | 5 | Hard cap on cards issued per calendar week |
| `DAILY_LOSS_HALT_PCT` | **null** | Protocol §5 proposes **−3%** |
| `WEEKLY_LOSS_HALT_PCT` | **null** | Protocol §5 proposes **−6%** |
| `CUMULATIVE_KILL_PCT` | **null** | Protocol §5 proposes **−20%** (with a **−10% soft** cumulative review/pause, not a kill) |
| `HUMAN_EXECUTES_ALL_ORDERS` | **true** | Same immutability treatment as the constitution booleans |
| `POST_MORTEM_PATH` | **null** | A cumulative-breach KILL is **terminal**; resume is refused until this points at a completed post-mortem |

**Fail-safe (important):** while any breaker threshold is `null`, breaker evaluation **blocks card
generation** rather than silently skipping the check (`src/live/breakers.py`). The −3/−6/−20 numbers
are **not hardcoded anywhere** — they are config, set later by deliberate re-registration.

**Layer modules** (`src/live/`): `intents.py` (BUY/SELL only — no SHORT), `cards.py` (proposal render,
pure, sending is separate), `fills.py` (human-reported; PENDING cards auto-EXPIRE after 2 trading
days), `reconcile.py` (any mismatch writes `data/live/RECONCILE_BLOCK` and card generation refuses),
`slippage.py` (decision → card → fill in bps; adverse slippage is positive by convention), `kill.py`,
`breakers.py`, `limits.py`. The layer holds **no broker libraries, imports no decision math, and never
writes a paper cohort file.**

## 6.3 Kill switch and drills — `docs/LIVE_RUNBOOK.md`

**The KILL file is the single source of truth**, so the controls work with Telegram down.
`scripts/live_kill.py`: `status` / `engage "<reason>"` / `engage "<reason>" --terminal` /
`confirm-resume "<reason>"` / `clear-weekly "<reason>"`. **Resume is deliberately two steps** —
`confirm-resume` (logged, with a reason) **and** manual deletion of `data/live/KILL`. A `--terminal`
kill refuses resume until `POST_MORTEM_PATH` points at a completed post-mortem.

**Pre-go-live drill** (`python3 scripts/live_drill.py`, dry-run sandbox) exercises three failure paths
— (a) kill mid-pending-cards, (b) daily-loss breach (`HALT_DAILY`, date-stamped, auto-clears next
session; weekly breach → `HALT_WEEKLY` with a two-step reset), (c) reconcile mismatch
(`RECONCILE_BLOCK`). Runbook rule: **do not fund the pilot until the drill passes AND the thresholds
are set.** Prior-session records report a 32/32 drill pass.

## 6.4 Current activation state at this location

`data/live/` **exists and is empty** — no `KILL`, no `HALT_DAILY`, no `HALT_WEEKLY`, no
`RECONCILE_BLOCK`, no intents, no cards, no fills. Combined with `MAX_LIVE_CAPITAL_GBP: 0` and three
null breakers, the pilot is **inert and cannot issue a card**. Timeline: protocol drafted and locked
**2026-07-06**; planned start **November 2026**; **capital authorization is the outstanding gate**
(§8 Q-02).

---

# 7. Major standing decisions — dated, with one-line reasoning

| # | Date | Decision | Reasoning (one line) | Status |
|---|---|---|---|---|
| D-01 | 2026-05-25 | Paper-only, no broker, human-gated, no P&L learning — the five architectural constraints | Stop the system ever being able to lose real money or to tune itself on its own outcomes (`README.md`; `SYSTEM_AUDIT_2026-05-25.md §1`) | **CURRENT** |
| D-02 | 2026-05-25 | swing-bot gets a **6-month auto-disable**, `disable_date: 2026-11-25` | A dated expiry beats an open-ended experiment nobody ends (`SYSTEM_AUDIT_2026-05-25.md §1.9`) | **CURRENT** (bot itself already NO_GO) |
| D-03 | 2026-05-26 | Constitution v1.0 — seven immutable booleans + concentration caps in one human-only file | One source of truth for hard limits, never programmatically modified (`config/constitution.yaml`) | **CURRENT** |
| D-04 | 2026-05-29 → 2026-06-02 | **Do not build the council** until ≥2 members each show a validated, decorrelated edge; Metis parked 2026-06-02 | Combining nulls or correlated members is *"laundered noise"*; current count meeting the bar = **0** `(LAPTOP-LOCAL: council_architecture_note.md)` | **CURRENT — the binding gate for any redesign** |
| D-05 | 2026-05-29 | Council must stay **dumb and fixed** (equal-weight/risk-parity, pre-registered thresholds, **no learned meta-model**); argumentation is the **explanation layer only** | The aggregator is a giant overfitting surface; LLM debate is fluent regardless of truth `(LAPTOP-LOCAL)` | **CURRENT** |
| D-06 | 2026-05-29 | Learning layer is **ring-fenced**: observe + propose only, cannot mutate a live system, cannot auto-promote; **council critique ≠ validation**; proposals validate only on held-out/forward data | A pattern-searching layer *will* find spurious patterns; ring-fencing is **data isolation**, not just execution isolation `(LAPTOP-LOCAL)` | **CURRENT** — later realised concretely as `OUTCOME_LEARNING_VIA_BOUNDARY_ONLY` (§5.4) |
| D-07 | 2026-05-12 → 2026-06-08 | Host consolidation and **reversible decommission** of confirmed-dead crons/launchd jobs; nothing deleted, code + tokens preserved, crontab backups kept | Silent leftovers are worse than an inventory; reversibility keeps the decision cheap to undo `(LAPTOP-LOCAL: droplet_comparison_20260512.md, INFRA_INVENTORY.md)` | **CURRENT** |
| D-08 | 2026-05-29 | **Never host a continuously-running system on a laptop** — cron on a sleeping MacBook silently skips days | Silent holes in the evidence are indistinguishable from results `(LAPTOP-LOCAL)` | **CURRENT but VIOLATED at this location** — see §8 Q-09 |
| D-09 | 2026-06-01 | Pantheon names are a **display label only** — no directory, module, config, or data renamed | Cosmetics must not become a refactor `(LAPTOP-LOCAL: NAME_MAP.md)`; corroborated by `OLYMPUS_SYSTEM_STATE §1.3` | **CURRENT** |
| D-10 | 2026-06-01 | **Penny stocks / micro-caps permanently excluded**; universe gated to $500M–$200B market cap | *"Biggest movers = least tradeable"* — spreads eat any edge (`pantheon_naming_map.md`; `config/settings.yaml`; `src/universe/admission.py`) | **CURRENT** |
| D-11 | 2026-06-02 | **Hades' de-risk overlay retired; detector kept as a logged signal**, reframed as a human-in-the-loop kill switch that never auto-sells | The overlay's win was a look-ahead artifact and net-negative once recovery was counted `(LAPTOP-LOCAL: hades_design_note.md)` | **CURRENT** |
| D-12 | 2026-06-02 | **Capture premia cheaply, don't trade them expensively** — real premia are ownable at ~0.2–0.5%/yr in funds, not at ~2%/yr in retail spread/financing/swap | Caerus, Nemesis and Plutus all had **real gross edges eaten by access costs** `(LAPTOP-LOCAL: lessons_learned.md)` | **CURRENT** |
| D-13 | 2026-06-01 | Working-style rule: concise, no jargon, plain terms, rigour retained | Set by the operator for all responses `(LAPTOP-LOCAL: WORKING_STYLE.md)` | **CURRENT** |
| D-14 | 2026-06-04 | **Build small first** — do not scaffold 16 gods; most pantheon members stay named placeholders; complexity must be earned | The project's gravity is toward more architecture; *"a beautiful pantheon, no proven god"* `(LAPTOP-LOCAL: Olympus_Build_Prompt_v1.2 §2.5, §3, §5)` | **CURRENT** |
| D-15 | 2026-06-04 | **Correlated-council rule** — agreement between modules sharing inputs/data/model/reasoning must **not** raise confidence; reports must carry an independence assessment | Several voices agreeing is *more* dangerous, not less `(LAPTOP-LOCAL: Build Prompt §7)`. **It fired in the only real decision** — the ORCL card lists *"member agreement is correlated, not independent (no confidence uplift)"* as a confidence constraint | **CURRENT — empirically exercised once** |
| D-16 | 2026-06-04 | **ETF-alternative rule** — every single-name recommendation must justify itself against the cheapest relevant ETF or reduce confidence / HOLD | Encodes D-12 into the decision path `(LAPTOP-LOCAL: Build Prompt §8)`. Also fired on ORCL: the human override reason was *"core already covers AI/tech via QQQ; single-name risk not worth it"* | **CURRENT** |
| D-17 | 2026-06-04 | **Aeolus/Hades trap rule** — no regime-based sizing; any macro/regime module is observational until it earns authority forward | Prevents rebuilding the falsified Hades overlay under a new name `(LAPTOP-LOCAL: Build Prompt §6)` | **CURRENT** |
| D-18 | 2026-06-07 | **Gaia rules locked** — 5pp rebalance band, monthly, glidepath off (tier 8, steps 2035/2040), horizon-driven not market-driven | Mechanical discipline, never condition-timing; locked so it cannot be tuned to flatter (`gaia/rules.yaml`) | **CURRENT** |
| D-19 | 2026-06-07 | **Phaethon Arm B built as a separate, isolated instance** with its own image/book/memory, −25% kill switch, and a Goodhart guard keying learning on realized return vs QQQ, never on the +10% target | An aggressive arm must not contaminate the disciplined one; matching SHAs proved Arm A untouched `(LAPTOP-LOCAL: NEXT_STEPS.md)` | **CURRENT** |
| D-20 | 2026-06-24 | Phaethon **v1.1 "broadened aperture"** deployed — 8-theme universe (37 names) + mandatory cross-theme scan, both arms, bar unchanged and test-asserted, de-overlapped, versioned/dated/segmented/reversible | Broaden the opportunity set without moving the bar `(LAPTOP-LOCAL: NEXT_STEPS.md)`. **Carries an explicit verification obligation at 40–60 days** — see Q-08 | **CURRENT, verification OVERDUE** |
| D-21 | 2026-07-05 | **Protocol lock established and re-registered 9 times in one day**, each with a written reason; the lock is never auto-updated to go green | Baseline-before / re-register-after pairing makes every ruleset edit deliberate and auditable (`docs/PROTOCOL_CHANGELOG.md`) | **CURRENT** |
| D-22 | 2026-07-05 | **Momentum neutralized to observation-only** | Net Q1−Q5 spread t = 0.09 — the evidence does not support letting momentum move entry confidence (registry 001) | **CURRENT** |
| D-23 | 2026-07-05 | **Legacy Cohort sunsets on a fixed date (2026-08-23)**, not at natural exit; forced close is mechanical, tagged `forced_sunset`, not an exit signal | A fixed date gives bounded closure and stops legacy contaminating Cohort-1 via the fixed engine's downgrade logic (`OBSERVATION_PROTOCOL §1.2`) | **CURRENT — but not executed, see Q-01** |
| D-24 | 2026-07-05 | **exit_rules_v2 ACTIVATED at Cohort-1 day-0**, params frozen (1.0 / 270d / 28d), scoped to `cohort_1` only, legacy exempt | Activate before inception so the window yields closed-trade evidence under the full exit ladder — and never mid-window (`PROTOCOL_CHANGELOG`, `OBSERVATION_PROTOCOL §2.2`) | **CURRENT** |
| D-25 | 2026-07-05 | **`oracle_v1` downgraded S2 → S1** | Hypothesis 003 is TESTING, not PASSED — S2 was a premature retrofit (`config/sleeves/oracle_v1.yaml`) | **CURRENT** |
| D-26 | 2026-07-05 | **Sleeve admission rule** — no sleeve loads without a registered falsifiable hypothesis **and** non-empty pre-registered kill criteria; *"no default and no exception"* | Nothing runs capital, paper or real, without a way to fail and a stopping rule (`config/sleeves/_schema.yaml`) | **CURRENT** |
| D-27 | 2026-07-05 | **F7b double-gate declared** — Bonferroni **and** deflated Sharpe, accepting a high false-negative rate | Chosen explicitly against the operator's documented history of over-iterating on under-powered results (`research/README.md`) | **CURRENT** |
| D-28 | 2026-07-05 | **Refuse to proxy-backtest EPS revisions on an unreliable feed**; start forward logging instead | *"That would manufacture a false result"* — a real 12–18-month wait beats a fake answer now (`STUDY_A_revisions_memo.md`) | **CURRENT** |
| D-29 | 2026-07-05 | **Boundary-only learning for Phaethon** — n-triggered (≥25 closed trades **and** ≥13 weeks), 2-lesson change budget, forward predictions, own kill criterion | At per-category n of 2–5 there is nothing real to learn; frozen policy is the *fast* path to live capital, not the slow one (`PHAETHON_LEARNING_DECISION.md`) | **CURRENT** |
| D-30 | 2026-07-05 | **One primary benchmark per book** — Phaethon → QQQ, Olympus → SPY TR; dual display allowed, blended cross-book comparison forbidden | A QQQ-relative and an SPY-relative number are not the same bar (`PHAETHON_BENCHMARK_MEMO.md`) | **CURRENT** |
| D-31 | 2026-07-05 | **PART F and PART G stopped at the protocol lock rather than break it** | The boundary is worth more than the feature; both were later delivered via deliberate re-registration (`BATCH_AUDIT_2026-07-05.md §7`) | **SUPERSEDED** (both landed the same day, re-registered) |
| D-32 | 2026-07-05 | **One-off constitutional exception**: a read-only research script ran on the trading host because the research droplet no longer existed — *explicitly not a precedent* | Logging the exception preserves the rule; silence would erode it (`docs/CONSTITUTIONAL_EXCEPTIONS.md`) | **CURRENT** |
| D-33 | 2026-07-05 | **Phaethon publisher migrated off-repo → under repo governance**; the original script committed verbatim for audit and **not run** | An ungoverned cron on the droplet was outside every check that exists (`docs/LIVE_RUNBOOK.md`; `scripts/phaethon/publish_original_reference.sh`) | **CURRENT** |
| D-34 | 2026-07-05 | **Governance surfaces, never clamps** — a violation writes `NONCONFORMING` into the arm JSON and alerts; it does not fix the book | Silent correction destroys the record of what the strategy actually did (`src/phaethon/governance.py`; `test_run_governance_does_not_clamp`) | **CURRENT** |
| D-35 | 2026-07-05 | **Decoupled fetch/push credentials** — `origin` over HTTPS (read-only), push over an explicit SSH URL with a dedicated write key | Lets the read path work without granting the read path write access (`docs/LIVE_RUNBOOK.md`) | **CURRENT** |
| D-36 | 2026-07-06 | **Live-pilot protocol hash-locked** as a separate `live_pilot` artifact inside `protocol_lock.yaml`; capital placeholder 0; breakers null and **fail-safe blocking** | Nothing about the pilot should be softenable later; an unset threshold must block, never skip (`config/protocol_lock.yaml`, `src/live/breakers.py`) | **CURRENT** |
| D-37 | 2026-07-06 | **`OLYMPUS_SYSTEM_STATE.md` is the system of record**, regenerated from the repo rather than from the prior snapshot; *"where this doc and the code disagree, the code wins"* | The document/reality divergence class of error recurs here, so the snapshot hunts it explicitly (§7 of that file, 15 divergences listed) | **CURRENT, but STALE — 2026-07-06, ~8 weeks old** |
| D-38 | 2026-08-07 | **Arm B trimmed to the 10% cap**, excess released to cash and **not redistributed**; pre-trim state archived and locked into a test | The concentrated mandate does not override a constitutional cap; redistribution is a separate feature that must be decided on its own (`c9d53c6`, `src/phaethon/rebalance.py`) | **CURRENT** |
| D-39 | 2026-08-07 | **The governed publish pipeline was wired into production for the first time** — until then the droplet cron ran the old ungoverned script and NONCONFORMING had never surfaced live | Governance that is committed but not wired is not governance (`c9d53c6` commit body) | **CURRENT — and the standing lesson: verify the cron actually calls the governed path** |

---

# 8. Open questions awaiting operator decision

| # | Question | Where it was flagged and left unresolved |
|---|---|---|
| Q-01 | **The Legacy Cohort's forced sunset (2026-08-23) has not executed — 9 days overdue at this location.** 12 `legacy_pre_fix` positions remain open in `data/paper_positions.yaml`. The mechanism exists but only fires inside `process_screener_results`, and the last screen on disk is **2026-05-26**. Does the operator run a screen to trigger it, close them out of band, or amend §1.2? | **NEW — surfaced by this consolidation.** Mechanism: `src/paper_trading.py::LEGACY_SUNSET_DATE`; rule: `OBSERVATION_PROTOCOL §1.2`; evidence: `runs/_screen/` latest `20260526_140059`. *Cannot rule out that the droplet ran it — see §9.* |
| Q-02 | **Live-pilot capital authorization.** `MAX_LIVE_CAPITAL_GBP` is 0 and the three breakers are null, so no card can be generated. The protocol's November-2026 start needs the operator to set the amount (as loss tolerance, not a return target) and re-register both files. | `config/live_limits.yaml`; `LIVE_PILOT_PROTOCOL §2, §5`; `LIVE_RUNBOOK` ("do not fund until the drill passes AND thresholds are set") |
| Q-03 | **Arm B: live candidate or falsification control?** Posed at the top of the ledger memo as an explicit operator question, with the note that it was then still NONCONFORMING. It is now CONFORMING (§5.3) — the question was never answered, and the condition attached to it has changed. | `docs/PHAETHON_ARM_B_LEDGER_MEMO.md` (top); `OLYMPUS_SYSTEM_STATE §6(a)` |
| Q-04 | **Real-engine PT-calibration study — worth the cost?** The proxy gives rank IC +0.10/+0.14 against a ≥0.30 bar, with a clean-subset median ≈0. A Stage-1 study on the actual engine's price targets is *noted, not proposed*, and deliberately not registered. | `FINDINGS_pt_calibration.md §6`; `OLYMPUS_SYSTEM_STATE §6(a)` |
| Q-05 | **Arm A is 66.5% in cash and DEGRADING vs QQQ, with no document stating a target.** Is two-thirds cash the intended posture for the disciplined arm, or an artifact? No `docs/PHAETHON_*.md` sets a deployment target, so there is no bar to measure it against — which is itself the gap. | **NEW — surfaced by this consolidation** from a direct read of `docs/data/phaethon_live.json` against `PHAETHON_ARM_B_LEDGER_MEMO §4` (62% at the 2026-07-05 restatement) |
| Q-06 | **The Olympus MVP arms A and B hold identical satellites, and all three arms carry negative cash** (A/B −1368.40, C −1197.35) at `as_of 2026-06-04`. If A and B were meant to be a discovery comparison, an identical book means the comparison produced no signal — and the negative cash is the same failure mode later diagnosed in Phaethon Arm B. Never reconciled anywhere in the corpus. | **NEW — surfaced by this consolidation** `(LAPTOP-LOCAL: olympus/data/arm_*_portfolio.json)` |
| Q-07 | **Score Apollo against its own theme calls, misses included.** Named as priority 6 of 7 and as flaw 7 — *"the most important original question has the least progress."* No evidence it was ever done. | `(LAPTOP-LOCAL: olympus_system_review.md)` |
| Q-08 | **Phaethon v1.1 aperture verification is overdue.** The 2026-06-24 deploy carried an explicit obligation: re-run the concentration/factor decomposition at **40–60 days** (≈2026-08-03 to 2026-08-23) to confirm effective independent bets rose above ~1.5 — *"the scan output isn't the proof; lower realised book correlation is."* No such re-run appears anywhere in the corpus. | `(LAPTOP-LOCAL: NEXT_STEPS.md)` |
| Q-09 | **The laptop is an active publisher to `main`**, via `com.ats.live-refresh`, against the standing D-08 principle that continuously-running things belong on an always-on host. Intended, or a leftover to decommission like the 2026-06-08 batch? | **NEW — surfaced by this consolidation** (Mac launchd + the two `ATS Live Refresh` commits ahead of the droplet) |
| Q-10 | **The live-refresh job is degraded.** `logs/live_dashboard.log` shows repeated `Skipped scai_live.json / hermes_live.json (new n_priced=0, keeping last good data)` and `portfolio=None% SPY=None% alpha=None%`. It fails safe (keeps last good data) but two panels are being served stale and the summary computes nothing. | **NEW — surfaced by this consolidation** |
| Q-11 | **Cohort-1's inception date is undefined in practice** — is it the lock-registration date (2026-07-05) or the first-position date? No `cohort_1` position exists, so the 52-week clock has no unambiguous start. | `OLYMPUS_SYSTEM_STATE §6(b)` — flagged, never decided |
| Q-12 | **Cohort-1 is armed but empty and nobody has decided what to do about it.** Lock registered, exit rules active, sleeve S1, registry 003 TESTING — governing **zero positions**, unchanged since 2026-07-06. | `OLYMPUS_SYSTEM_STATE §6(c)1` — surfaced prominently, still open |
| Q-13 | **BUG-003 remains OPEN** — LMT/MA price targets floored to $0. The proper fix (per-sector multiple calibration, "Path B") is a calibration-class change and therefore **queued for Cohort-2, not applicable mid-window**. | `KNOWN_BUGS.md`; `OBSERVATION_PROTOCOL §6` |
| Q-14 | **6 pre-existing test failures** in `tests/test_dashboard_live.py` (position-id assertions against a newer `docs/index.html`). Long-standing, unrelated to recent work, never fixed. | `OLYMPUS_SYSTEM_STATE §6(c)4`; `BATCH_AUDIT_2026-07-05 §1` (747 passed / 6 failed then; 861 / 6 at the July snapshot) |
| Q-15 | **A second sleeve has never been written.** The framework supports many; only the `oracle_v1` retrofit exists. | `OLYMPUS_SYSTEM_STATE §6(a)` |
| Q-16 | **The programme-level kill switch was never written.** Flaw 4: individual kill switches exist, but there is no written answer to *"what result ends the whole project"* — named as priority 3 of 7. | `(LAPTOP-LOCAL: olympus_system_review.md)` |
| Q-17 | **Live-vs-backtest reconciliation was never built** — named the *"single biggest missing safeguard"* and the cheapest, highest-value system-wide fix (priority 2 of 7). | `(LAPTOP-LOCAL: olympus_system_review.md)` |
| Q-18 | **Is point-in-time (CRSP-style) data worth paying for?** Named priority 4 — *"it gates the honesty of every backtest."* The survivorship caveat in the momentum memo is the live cost of not having it. | `(LAPTOP-LOCAL: olympus_system_review.md)`; `MEMO_momentum.md` |
| Q-19 | **`Olympus_System_Overview.docx` has never been reconciled against the code.** A binary overview document sitting untracked next to a corpus with a documented document/reality divergence problem. | **NEW — surfaced by this consolidation** |

## Document disagreements — both states, and which is current

| Subject | State A | State B | Current |
|---|---|---|---|
| Observation protocol lock | The document's own header says **"DRAFT — pending approval & hash-lock"** and its LOCK BLOCK says `locked: false` | `config/protocol_lock.yaml` says `locked: true, registered: 2026-07-05`, and `tests/test_protocol_lock.py` passes against it | **B is current.** The doc's trailing lock block was never updated after registration — a stale artifact, not a live contradiction |
| Arm B restatement date | Memo + `OLYMPUS_SYSTEM_STATE §3`: **"restated 2026-07-05"** | Live JSON, read directly: **"restated 2026-08-31"** | **B is current** — the string is re-stamped by each governed publish |
| Arm B conformance | `OLYMPUS_SYSTEM_STATE §3` + `phaethon_design_note.md` + `src/phaethon/governance.py` docstring: **NONCONFORMING** (138% gross / top weight 13.7%) | Live JSON: **CONFORMING**, 86.9% gross, zero violations | **B is current.** The July snapshot and the two docstrings predate both the restatement and the 2026-08-07 trim |
| Arm A position count | `OLYMPUS_SYSTEM_STATE §3`: **18 positions, 62.0% cash, 38.0% gross** | Live JSON: **14 positions, 66.5% cash, 33.5% gross** | **B is current** |
| Universe size | `SYSTEM_AUDIT_2026-05-25.md:323` says **61**; `KNOWN_BUGS.md:42` says **"now 60 names"** | `config/universe.yaml` header and count: **147** | **B is current**; `MEMO_momentum.md` already flags the staleness |
| `exit_rules_v2` | `config/settings.yaml` comment: *"DEFAULT OFF — must stay false"* | Value is **`true`**; `tests/test_cohort1_exit_rules_active.py` asserts it must be True | **B is current**; the comment is stale |
| `data/paper_trades.jsonl` | `README.md:59` and `src/paper_trading.py` describe it as the immutable trades log | File **does not exist** — zero closed trades, never written | **B is reality** |
| Pre-framework review docs | `olympus_system_review.md`, `SYSTEM_AUDIT_2026-05-25.md`, `OLYMPUS_STATUS_BRIEFING_2026-06-16.md`, `NEXT_STEPS.md` mention **zero** sleeves/registry/exit_rules_v2 | The whole framework layer landed **2026-07-05**, after all of them | **The framework is current**; those docs remain valid on strategy verdicts, stale on architecture |
| `STATUS.txt` | *"6 tickers screened … SB=17 B=3 H=12 S=8 SS=20"* — a distribution summing to **60** from 6 tickers, dated 2026-05-25 | Internally impossible and never refreshed | **Stale and self-inconsistent** — do not cite |

---

# 9. Known gaps — what THIS location's run cannot cover

**This spec runs twice because neither location can see the other.** A consolidation that read only
committed history would miss both the laptop's uncommitted design corpus (§B above) and the droplet's
runtime reality (below). This is the laptop half; the droplet half is
`docs/OLYMPUS_KNOWLEDGE_BASE_DROPLET.md`. **Do not treat this file as complete on its own.**

## What this laptop run cannot see

1. **All droplet runtime state.** No cron status, no systemd/journal entries, no tmux sessions, no
   execution history for the Phaethon publisher (`45 22 * * *
   /root/phaethon-panel-repo/scripts/phaethon/publish.sh`) or the weekly pipeline. Whether the
   governed publish is still firing nightly, and whether it has ever written a NONCONFORMING banner
   since 2026-08-07, is **unknown from here**. (`OLYMPUS_SYSTEM_STATE §3` states the same limitation:
   *"Not verifiable from the repo alone: droplet-side state, cron status, live tmux sessions."*)
2. **The Olympus council code itself.** `INFRA_INVENTORY.md:47,112,121` records the live governed
   paper-decision loop as `agent/olympus/scripts/run_olympus_loop.sh` on `ats-trading`, and states
   plainly that if that host dies *"the live Olympus loop stops (it exists nowhere else)."* On this
   laptop `olympus/` contains **data and reports but zero `.py` files**. **The single most important
   artifact for a council/agent redesign — the running implementation — is visible only from the
   droplet.**
3. **`docs/OLYMPUS_KNOWLEDGE_BASE.md` and `docs/OLYMPUS_KNOWLEDGE_BASE_INDEX.md`.** Prior-session
   records place these on the droplet at `/root/phaethon-panel-repo/docs/` from 2026-08-07. They are
   **in no commit** (`git log --all -- '*KNOWLEDGE_BASE*'` is empty) and not on this disk. The droplet
   run must read them — and their existence means the droplet has documentation this location has
   never seen.
4. **Phaethon's trader state and strategy.** `trader{,_b}/state/book.json` and
   `scorecard_public.json` live under `/home/phaethon/phaethon/` on the droplet. Everything in §5
   about the arms is derived from the **published render** (`docs/data/phaethon_*.json`), not from the
   source book. A divergence between the trader's book and the published render would be invisible
   here.
5. **Whether the Legacy Cohort sunset (Q-01) actually fired.** This location shows it overdue, but the
   authoritative `data/paper_positions.yaml` for any droplet-side run is not visible from here. The
   droplet run must check this specifically.
6. **Live-pilot activation state on the droplet.** `data/live/` is empty here and
   `MAX_LIVE_CAPITAL_GBP` is 0 in the committed config, but a droplet-local override, a `KILL` file, or
   a differently-valued `live_limits.yaml` outside git would not be visible.
7. **Any droplet-local override file referenced by `run_weekly.sh` or the live guard scripts but not
   in git**, plus `.env` files, tokens, and the `pm2` dump — all droplet-side by design.
8. **The two `ATS Live Refresh` commits' effect on the droplet.** The droplet is 2 commits behind; its
   next `git reset --hard origin/main` (which `publish.sh` performs) will pull them. Harmless here,
   but it means the droplet's on-disk `docs/data/` differs from this location's right now.

## What the droplet run will not be able to see (stated so it isn't lost)

- The entire **uncommitted design corpus** in §B: `council_architecture_note.md`,
  `lessons_learned.md`, `olympus_system_review.md`, `Olympus_Build_Prompt_v1.2.md`, the four design
  notes (Hades, Caerus, Mercury, Metis), `NEXT_STEPS.md`, `INFRA_INVENTORY.md`, `NAME_MAP.md`,
  `WORKING_STYLE.md`, the two public summaries, `Olympus_System_Overview.docx`, and the
  `OLYMPUS_STATUS_BRIEFING`. **Most of the project's falsification history and every council-design
  rule lives only here.**
- The **`olympus/` data tier** — the ledgers, the one worked Zeus decision, the three arm portfolios —
  unless an identical copy exists on the droplet.
- The parent-directory infrastructure notes and `~/trading/ecosystem_architecture.md`, the cited
  source for several §4B verdicts.
- The Mac launchd/cron topology and the degraded live-refresh log (Q-09, Q-10).
- The sibling `labs/`, `epimetheus/`, `phaethon_shadow/`, `phaethon_trader_stage/` repos.

## Structural gaps that neither location will close

- **`~/trading/ecosystem_architecture.md` is cited as the source of record** for the RP/QRE 19.86% vs
  66.17% discrepancy and the Nike/Iris verdicts, and it is **outside the ATS repo entirely**. Those
  verdicts are therefore traceable to a file that no run of this spec covers.
- **Zero closed trades exist anywhere in the primary evidence path.** `data/paper_trades.jsonl` has
  never been written. Registry entry 003 — the only open hypothesis — has no data on either side.
- **`OLYMPUS_SYSTEM_STATE.md` is ~8 weeks stale** (2026-07-06) and its own rule is *regenerate after
  every subsystem-touching merge, otherwise monthly*. The 2026-08-07 trim was a subsystem-touching
  merge and no regeneration followed. Its §3 numbers are superseded (see the disagreement table).

---

*Compiled 2026-09-01 on the laptop from `main` @ `c97c9ff`, read-only. Refresh commands:
`python scripts/registry.py stats` · `python scripts/verify_protocol_lock.py` ·
`python3 -c "import json;print(json.load(open('docs/data/phaethon_b_live.json'))['status'])"` ·
`ls runs/_screen/` · count `data/paper_positions.yaml` by cohort · `git status --porcelain --ignored`.
Where this document and the code disagree, the code wins — regenerate.*
