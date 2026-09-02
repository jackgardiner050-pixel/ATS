# Olympus / ATS — Consolidated Knowledge Base

## LOCATION: **DROPLET** — `ats-trading` (DigitalOcean, lon1, Ubuntu 6.8.0, up 81 days)

**Compiled:** 2026-09-01 · **Method:** read-only walk of the droplet over SSH. No file on the droplet
was written, no process started, stopped, or modified.

> ### PROVENANCE CAVEAT — READ THIS FIRST
> The spec assumes the session runs **on** the droplet. It did not: the session ran on the operator's
> **laptop**, and every droplet fact below was gathered by **read-only SSH** to the droplet.
> Consequences the reader must hold: (a) **nothing was written to the droplet** — the output file lives
> on the laptop at `docs/OLYMPUS_KNOWLEDGE_BASE_DROPLET.md` in the same repo as the laptop half, which is
> where the operator can diff them; (b) commands ran as `root` in a non-interactive shell, so anything
> visible only inside a container, a tmux session, or another user's environment could be missed and is
> declared in §9; (c) no droplet-side shell history, editor state, or interactive session was inspected.
> Everything asserted below is from a command whose output is quoted or counted here.

**Companion:** the laptop half is `docs/OLYMPUS_KNOWLEDGE_BASE_LAPTOP.md` (875 lines, compiled
2026-09-01, committed by the operator as `38416bf`). **Neither file is complete alone.** This one adds
runtime reality and the council implementation; the laptop one holds the design corpus and the
falsification history, none of which exists here (§9).

---

## ESCALATION-CLAUSE CHECK — result: **NO FORK, proceed** (but three trees at three different commits)

This host holds **three separate git working trees** of, or around, the ATS repo — a fact not visible
from the laptop and material to everything below.

| # | Path | Repo | Branch | HEAD | Role |
|---|---|---|---|---|---|
| 1 | `/root/phaethon-panel-repo` | `jackgardiner050-pixel/ATS` | `main` | **`7ef5fcd`** (2026-08-31 22:45) | The Phaethon panel publisher — the only tree the nightly `publish.sh` touches |
| 2 | `/root/agent/ats-live` | `jackgardiner050-pixel/ATS` | `main` | **`fcd9198`** (2026-07-06 13:44) | The **Cohort-1 weekly screen** host — the authoritative paper book |
| 3 | `/root/agent/olympus` | **local-only repo, NO REMOTE** | `master` | **`1bca7a1`** (2026-08-18) | **The Olympus council implementation** (§1A) |

Plus three non-git support trees under `/root/agent`: `src/` (the ATS `src` tree the council imports at
runtime), `config/`, `data/`, and a bare backup at `ats-live-backup.git`.

**Ancestry, verified against the laptop clone's full history** (the droplet clones have separate object
stores, so the check had to run where all objects exist):

- `7ef5fcd` → **ancestor** of laptop HEAD. Panel tree is behind by automated dashboard commits only.
- `fcd9198` → **ancestor** of laptop HEAD, **behind by 37 commits**. Both `git cat-file -t` and
  `merge-base --is-ancestor` confirm it. **No fork.**

**But note what that 37-commit gap contains:** `fcd9198` predates **`c9d53c6`** (2026-08-07 — the Arm B
trim and the wiring of the governed publish pipeline). So **the tree that runs the Cohort-1 screen does
not contain the governance infrastructure at all.** That is drift, not divergence, and it is recorded
as finding **DR-03** (§7).

The laptop HEAD has since advanced to `bdcf4bc`; the operator committed the laptop knowledge base as
`38416bf` at 20:16 UTC+1 today. Neither droplet tree has pulled it yet.

---

# LOCAL-ONLY MATERIAL FOUND AT THIS LOCATION

Everything here exists **on the droplet only** and is **not** shared repo history. Not folded into
§1–§8 as if committed; where one is the sole source for a fact, the citation is tagged `(DROPLET-LOCAL)`.

## A. The entire `/root/agent/olympus` repository — **no remote, never pushed**

`git remote -v` returns **empty**. The working tree is clean on `master`. This is the single most
important local-only artifact on either machine: **the council implementation exists in exactly one
place, in a git repo that has never been pushed anywhere.** Its own operating doc states the position
plainly — *"The working tree at `/root/agent/olympus` IS the running system: the 21:45 UTC weekday cron
runs `olympus.cli loop run` directly from it. No build/deploy step exists, so any broken intermediate
state is a broken deploy."* (`docs/atomic_deploy.md`). Backed up only via the nightly encrypted
off-box `restic` job (`/root/backup/run_backup.sh` → B2), not by any code host.

## B. Droplet-only documents (inside that unpushed repo — so still droplet-only)

| File | Date | Content | Relevance |
|---|---|---|---|
| `docs/OLYMPUS_KNOWLEDGE_BASE.md` | header says compiled **2026-08-07**, file mtime **2026-08-18** | A 9-section prior consolidation of the same corpus. **Read in full for this run.** | **HIGHLY RELEVANT** — prior-art; reconciled in §8's disagreement table rather than silently re-derived. Note the laptop doc placed these at `/root/phaethon-panel-repo/docs/` on 2026-08-07; **both the path and the date were wrong** — they are in the olympus repo, committed 2026-08-18 as `1bca7a1` *"docs: add Olympus knowledge base + index (private tree)"*. |
| `docs/OLYMPUS_KNOWLEDGE_BASE_INDEX.md` | 2026-08-18 | Navigation index, one paragraph per section. | RELEVANT — consistent with the above. |
| `docs/atomic_deploy.md` | 2026-06-16 | **A standing governance rule** (§2.10) — the worktree/suite-green/atomic-swap procedure for editing the live tree. | **HIGHLY RELEVANT** — a hard operational rule that exists nowhere in the ATS repo. |
| `docs/ops_incidents.md` | 2026-06-16 | Operational incident log. One entry (2026-06-15). *"Paper observations are never backfilled; a missed run is recorded honestly as a gap."* | **HIGHLY RELEVANT** — the honesty rule and the only recorded incident (§7 D-D2). |
| `docs/director_decisions_2026-06-10.md` | 2026-06-10 | The **Option A integrity fix** record: T212 demo disabled, telemetry, kill-criterion codified, Q1–Q3/Q5 closed, Q4/Q6 left open. | **HIGHLY RELEVANT** — three standing decisions and two still-open questions found nowhere else (§7, §8). |
| `docs/constitution.md` | 2026-06-04 | The olympus MVP's own constitution doc. | RELEVANT. |
| `README.md` | 2026-06-04 | Repo readme. | Incidental. |

## C. Hash-locked pre-registrations (droplet-only, `olympus/preregistration/`)

Three specs, each with a `.sha256` sidecar so editing **fails closed**:
`actionable_bar_v1.yaml` (2026-06-04) · `growth_mandate_v1.yaml` (2026-06-04) ·
`kill_criterion_v1.yaml` (2026-06-10). **This is a second, independent hash-lock regime** running
alongside the ATS repo's `protocol_lock.yaml`, and it is invisible from the laptop.

## D. Runtime artifacts outside any git tree

| Path | Content | Relevance |
|---|---|---|
| `/root/agent/olympus/data/ledgers/` | `olympus_decisions.jsonl` (**546 records**, hash-chained), `olympus_counterfactual.jsonl` (546), `olympus_screener_picks.jsonl` (59), `olympus_paper_fills.jsonl` (**14, last written 2026-06-04**) | **The council's entire evidence record.** §1B. |
| `/root/agent/olympus/data/cron.log` (+ `.log.1`) | Loop + Mnemosyne output, rotated at ~1 MB. Live to 2026-09-01 04:32. | **RELEVANT** — the proof of execution. |
| `/root/agent/olympus/data/cron.err` + `ALERT_20260615T214501Z_cron.flag` | **Exactly one alert, ever**: 2026-06-15 rc=1. | RELEVANT (§7 D-D2). |
| `/root/agent/olympus/data/oracle_health.json` | `{"consecutive_unavailable": 0, "last_run_available": true, "stamp": "20260831T214538Z"}` | RELEVANT — Oracle reachable on the last run. |
| `/root/agent/ats-live/logs/` | **16 weekly logs**, `olympus_screen_YYYYMMDD.log` + `weekly_*.log`, 2026-07-12 → 2026-08-30. | **DECISIVE for Q-01** (§3). |
| `/root/agent/ats-live/runs/audits/` | `extraction_audit_2026-08-30.md` etc. | RELEVANT — the only screen output that exists. |
| `/home/phaethon/phaethon/trader{,_b,_c}/state/` | `book.json`, `scorecard_public.json`, `cron.log`, `memory.jsonl`, `shadow_ledger.jsonl`, `version_log.jsonl` | **DECISIVE for §5** — the Phaethon source of truth, seen here for the first time. |
| `/home/phaethon/phaethon/_backup_pre_v1.1_*`, `_backup_pre_v1.2_*` | Pre-version-bump snapshots (2026-06-24). | RELEVANT — v1.1/v1.2 deploy discipline, evidenced. |
| `/home/phaethon/phaethon/gateway-data/`, `gateway-run.sh` | The Hermes/Telegram gateway. | Noted; not inspected (out of scope, and `gateway-data` is another user's private tree). |
| `/root/phaethon-panel-repo` untracked | `research/revisions_pt_validation/full_run.log`, `pt_calibration_results.csv`, `venv/` | **RELEVANT** — `pt_calibration_results.csv` is the raw data behind `FINDINGS_pt_calibration.md`; it exists **only here**, uncommitted. |

## E. Secrets — existence noted, **contents never read or reproduced**

Five credential stores exist under `/root` — covering the off-box backup, trading and SimFin
environments, the LLM key sourced by the loop runner, and SSH (including the panel's write key), plus
a pm2 dump. **None was opened, and no path, filename, or value from any of them appears in this
document.**
Per `director_decisions_2026-06-10.md`, the Trading-212 demo key was **archived out of the adapter's
search path** to `/root/olympus_audit/archived_secrets/` (chmod 600) on 2026-06-10.

---

# 1. System identity — as it actually runs on this host

Same system as the laptop document describes, with one correction that only this host can make: the
laptop half says *"only Oracle and Phaethon have backing implementations"* and that most pantheon names
are labels. **On this host that is false.** A real, ~4,500-line, git-versioned, test-covered council
implementation runs here on a weekday cron and has done so since 2026-06-04. It is absent from the ATS
repo because it lives in a separate, never-pushed repo (§A).

What actually executes on `ats-trading`, on a schedule:

| Time (UTC) | Job | What it is |
|---|---|---|
| 21:15 Mon–Fri | `trader_c/run_phaethon_c.sh mark` | Phaethon **control arm C** — mechanical equal-weight, no LLM |
| 21:00 Mon | `trader_c … rebalance` | Arm C weekly rebalance |
| 21:30 Mon–Fri | `hermes_v3_lab/scripts/run_droplet_daily.sh` | Hermes v3 shadow simulation |
| **21:45 Mon–Fri** | **`/root/agent/olympus/scripts/run_olympus_loop.sh`** | **The Olympus council loop** + Mnemosyne observe |
| 22:00 Mon / 22:30 Mon–Fri | `trader/run_phaethon.sh propose` / `mark` | Phaethon **Arm A** |
| 22:20 Mon / 23:20 Mon | `shadow_ledger/run_shadow.sh` ×2 | Phaethon shadow ledger (observation-only gate calibration) |
| **22:45 daily** | **`/root/phaethon-panel-repo/scripts/phaethon/publish.sh`** | Governed panel publish + git push |
| 23:00 Mon / 23:30 Mon–Fri | `trader_b/run_phaethon_b.sh propose` / `mark` | Phaethon **Arm B** |
| 23:50 Mon | `labs/oracle/run_oracle_mark.sh` | Oracle weekly MARK (no new ratings) |
| 03:30 daily | `/root/backup/run_backup.sh` | Encrypted off-box backup → B2 |
| 04:30 daily | `olympus/scripts/run_mnemosyne_resolve.sh` | Mnemosyne v1.1 resolver |
| **09:00 Sun** | **`/root/agent/run_ats_screen.sh`** | **Cohort-1 weekly screen** (deployed 2026-07-06) |
| various | EPE jobs (price panel, kill flags, weekly/morning status, universe drift) | Experimental Pot Engine; quarterly rebalance + weekly full refresh **PARKED 2026-06-15** |

No systemd timers serve any Olympus function — the OS timers are stock Ubuntu housekeeping only.

## 1A. THE COUNCIL CODE — full inventory with real / CLI-only / dormant / disabled classification

**Location:** `/root/agent/olympus` (repo `master` @ `1bca7a1`, clean, **no remote**).
**Entrypoint traced end-to-end:** root crontab `45 21 * * 1-5` → `scripts/run_olympus_loop.sh` →
`/root/olympus_venv/bin/python -m olympus.cli loop run` → `cli.cmd_loop_run` → `loop.run(broker_mode=venue)`.
Classification below is by **import reachability from that entrypoint**, verified by reading
`loop.py`'s import block and `cli.py`'s dispatch — not by file presence. `run_mnemosyne_resolve.sh`
(04:30 daily) is the second scheduled entrypoint.

**`loop.py` imports verbatim:** `olympus.core.{config, storage, paper_portfolio, kill, alerting}` ·
`olympus.adapters.execution.{make_broker, PaperBroker, Order, PAPER_MODE}` ·
`olympus.adapters.{oracle_adapter, athena_nemesis_adapter, hecate_adapter}` ·
`olympus.adapters.themis_mnemosyne_adapter` · `olympus.reports.zeus_report` ·
`olympus.members.{tyche, zeus, mandate}` · `olympus.reports.forward_scorecard` ·
**`from src.governance import concentration_governor as CG   # REAL blocking limits (every action)`**.

### LIVE — on the nightly executed path

| File | Lines | Modified | Role |
|---|---:|---|---|
| `olympus/loop.py` | 275 | 2026-06-15 | The decision loop: Oracle → critique → exposure → sizing → Zeus → PaperBroker → record → feedback |
| `olympus/cli.py` | 314 | 2026-06-17 | Entrypoint dispatch |
| `olympus/core/config.py` | 75 | 2026-06-10 | **Puts the member repos on `sys.path`** so adapters import the real engines — the cross-repo bridge |
| `olympus/core/storage.py` | 124 | 2026-06-17 | Hash-chained ledger append + `verify()` |
| `olympus/core/paper_portfolio.py` | 76 | 2026-06-04 | The paper book |
| `olympus/core/kill.py` | 103 | 2026-06-10 | Kill-criterion evaluator; `pause_status()` is called **before any new position** |
| `olympus/core/alerting.py` | 69 | 2026-06-10 | Flag-file alerting (no outbound sender) |
| `olympus/core/constants.py` | 63 | 2026-06-10 | Incl. `T212_DEMO_DISABLED = True` (verified) |
| `olympus/adapters/execution.py` | 130 | 2026-06-04 | `make_broker`, `PaperBroker`, `PAPER_MODE` |
| `olympus/adapters/oracle_adapter.py` | 230 | 2026-06-04 | Bridges to the **real** Oracle: `from oracle import forward_test as FT` |
| `olympus/adapters/oracle_llm.py` | 214 | 2026-06-04 | LLM call path (cache at `data/oracle_llm_cache.json`, 214 KB, live to 2026-08-28) |
| `olympus/adapters/athena_nemesis_adapter.py` | 41 | 2026-06-04 | Critique / red-team member |
| `olympus/adapters/hecate_adapter.py` | 76 | 2026-06-04 | Exposure & overlap member |
| `olympus/adapters/themis_mnemosyne_adapter.py` | 70 | 2026-06-04 | Governance / ledger / lineage |
| `olympus/members/zeus.py` | 70 | 2026-06-04 | **Decision synthesis** |
| `olympus/members/tyche.py` | 67 | 2026-06-04 | Sizing & allocation |
| `olympus/members/mandate.py` | 188 | 2026-06-04 | Mandate trim |
| `olympus/models/records.py` | 178 | 2026-06-16 | `Candidate` and record types |
| `olympus/reports/zeus_report.py` | 76 | 2026-06-15 | Per-decision report (e.g. `zeus_oracle_20260602_ORCL.md`) |
| `olympus/reports/forward_scorecard.py` | 186 | 2026-06-10 | Regenerated **every run** (Option A fix) |
| `olympus/observers/mnemosyne.py` | 198 | 2026-06-17 | Counterfactual observer + resolver — **second scheduled entrypoint** |
| `olympus/preregistration/spec.py` | 34 | 2026-06-04 | Hash-locked spec loader (fails closed) |
| **cross-repo:** `/root/agent/src/governance/concentration_governor.py` | — | — | **The ATS repo's real blocking limits, imported into the council on every action** |

### CLI-ONLY — real implementations, human-invocable, **not on any schedule**

`olympus/growth_loop.py` (218) · `olympus/arms.py` (30) · `olympus/core/arm_portfolio.py` (44) ·
`olympus/reports/growth_scorecard.py` (52) · `olympus/journal.py` (71) · `olympus/postmortem.py` (46) ·
`olympus/benchmark/screener.py` (83) · `olympus/reports/{exposure_report (44), monthly_rollup (71),
override_audit (50), quarterly_review (72), success_audit (40)}`.
Reachable via `olympus.cli growth run` / `report` / `journal` / `screener run`, but **no cron calls
them.** Evidence they are dormant in practice: `data/arm_{A,B,C}_portfolio.json` and
`data/growth_run.json` have not been written since **2026-06-04**.

### DORMANT — built and imported only by the CLI-only growth path

`olympus/discovery/artemis.py` (182) · `chronos.py` (47) · `hephaestus.py` (105) ·
`catalyst_feed.py` (101) · `growth_discovery.py` (63) · `observational_feed.py` (65).
These are the discovery members. **Nothing on a schedule reaches them.**

### DISABLED BY CONSTITUTIONAL DECISION

`olympus/adapters/t212_demo.py` (234, modified 2026-06-10) — a **Trading 212 demo broker adapter**.
Disabled in depth on 2026-06-10: `T212_DEMO_DISABLED = True` (verified `True` today);
`T212DemoBroker.__init__` raises `DemoDisabled` **before the secret is read**; `t212_demo` removed from
the CLI `--venue` choices; the key archived out of the adapter's search path. Because `DemoDisabled`
subclasses `T212Unavailable`, any programmatic `--venue t212_demo` **fails over to the internal sim**.
See §7 D-D1 — this is the closest the programme has come to the broker bright line.

### TESTS

18 test files, ~1,700 lines (`tests/test_phase2…phase8`, `test_loop`, `test_thin_slice`,
`test_constitution_constraints`, `test_deploy_target`, `test_integrity_optionA`,
`test_mnemosyne_{ledger,observer,resolver}`, `test_sleeve_attribution`, `test_growth_v2`).
Per `atomic_deploy.md` the suite *"imports every entrypoint (loop, growth_loop, cli), so a broken import
fails loudly."* **The suite was not run for this consolidation** — running it is a write-adjacent action
on a production tree and outside a read-only remit.

## 1B. What the council has actually decided — the evidence record

From `data/ledgers/olympus_decisions.jsonl`, hash-chained, `record_class: LIVE_OOS`, `engine: olympus_mvp`:

- **546 records**, spanning **2026-06-04 → 2026-08-31**, across **62 distinct decision days**, 8 per day.
- Kinds: **1 GENESIS · 534 HOLD · 11 BUY**.
- **Every one of the 11 BUYs is dated 2026-06-04.** Every one of the 14 records in
  `olympus_paper_fills.jsonl` is dated **2026-06-04** (tickers TSM, ETN, GEV, VRT, ONTO, ANET).
- **Since 2026-06-05 the council has issued nothing but HOLD — 534 consecutive HOLDs over ~3 months.**
- `data/paper_portfolio.json` is `{"as_of": "2026-06-04", "core_value": 10000.0, "cash": 0.0,
  "satellite": {}}` — **an empty book.**
- `olympus_counterfactual.jsonl` has 546 entries; the daily resolver reports
  **`resolved 0 matured arm-set(s), 425 failed`** with `SELFCHECK chain_ok=True resolutions=0` —
  Mnemosyne has run daily since 2026-06-17 and produced **zero resolutions**, with 425 failures on the
  last run (§8 Q-D4).

**Reading this honestly:** abstain-by-default is the designed behaviour (`council_architecture_note.md`,
laptop-side: *"Default output = abstain / do nothing"*), and 534 HOLDs is that design working. But the
loop has also opened nothing for three months while its counterfactual observer has resolved nothing,
so **there is currently no mechanism by which the council can accumulate the resolved-decision evidence
its own kill criterion requires** (`N_RESOLVED_MIN = 30`). The pre-registered promotion gate is
unreachable on present behaviour. That is a finding, not an inference: `n_resolved = 0` is exactly the
state `director_decisions_2026-06-10.md` calls *"the honest state today"* — 12 weeks later it is unchanged.

---

# 2. Governance constitution — droplet deltas only

The ATS-repo rules (constitution booleans, concentration caps, protocol lock, isolation tests, sleeve
admission, registry F5/F7a/F7b/F7d, change policy, reporting rule) are documented in full in the laptop
half and are **byte-identical here** — `research/registry.yaml` has the same md5 (`950bf80d…`) in both
droplet clones. Only the additions and confirmations unique to this host are recorded below.

## 2.9 The second hash-lock regime — `olympus/preregistration/` — **CURRENT** `(DROPLET-LOCAL)`

Three pre-registrations, each with a `.sha256` sidecar; editing the yaml without re-registering the
sidecar **fails closed** (`preregistration/spec.py`).

- **`kill_criterion_v1.yaml`** (2026-06-10) — thresholds, verbatim from the director record:
  `N_RESOLVED_MIN = 30`, `MIN_HIT_RATE_PCT = 50`, `MIN_VS_ACWI_BPS_NET = 0` (net of realised cost),
  plus **auto-pause after 3 consecutive resolved decisions each worse than −10% relative**.
  Evaluator `core/kill.py`; the loop calls `kill.pause_status()` **before opening any new position**,
  and de-risking SELLs still run when paused.
- **`actionable_bar_v1.yaml`** (2026-06-04) — the actionability bar.
- **`growth_mandate_v1.yaml`** (2026-06-04) — the growth-arm mandate.

## 2.10 Atomic-deploy discipline — **CURRENT** `(DROPLET-LOCAL: docs/atomic_deploy.md)`

Because the live tree *is* the running system, any runtime edit must: (1) be made in a separate
**git worktree**, never the live tree; (2) be **suite-green** there; (3) be swapped in via
`scripts/safe_deploy.sh`, which **refuses inside 21:30–22:15 UTC Mon–Fri**, re-runs the suite,
fast-forward-only merges, and verifies the live entrypoints import post-swap; (4) clean up the worktree.
Standing rules: never delete/rename a symbol without grepping all consumers; never leave the tree
non-importable even briefly; **a missed run is recorded honestly in `ops_incidents.md`, never backfilled**;
test-only changes may skip the worktree but must still be suite-green.

> This settles a laptop-side divergence: `OLYMPUS_SYSTEM_STATE.md §7 #10` flags the status briefing as
> citing an absent `safe_deploy.sh`. **It is not absent — it is at
> `/root/agent/olympus/scripts/safe_deploy.sh` (1,680 bytes, 2026-06-16), in the unpushed repo.**

## 2.11 Self-contained alerting — **CURRENT** `(DROPLET-LOCAL)`

The droplet's Telegram sender was **disabled 2026-06-09** ("ATS_Botbot leftover sender"), so the loop's
failure signal is deliberately **flag-file based**: a non-zero exit writes `data/cron.err` **and**
`data/ALERT_<utc>_cron.flag`, which the regenerated scorecard surfaces as a banner — *"nothing that can
be silently switched off."* Also alerted: `paper_fills_chain_ok == false`, and Oracle UNAVAILABLE for 2
consecutive runs (state in `data/oracle_health.json`).
**Consequence observed this run:** the weekly screen's `run_weekly.sh` logs
`Telegram send_message failed: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment` on
every run — the ATS-side alerting path is **unconfigured in the cron environment**, so ATS-side failures
have no outbound channel either (§8 Q-D3).

## 2.12 Constitutional confirmations made directly on this host

| Check | Result |
|---|---|
| `T212_DEMO_DISABLED` | **`True`** (`olympus/core/constants.py:33`) — verified today |
| Any live broker reachable from the council | **No** — `t212_demo` is the only broker adapter and it is disabled in depth; `execution.py` provides `PaperBroker` / `PAPER_MODE` |
| `config/live_limits.yaml` on the screen host vs committed | **Identical, no local override** — `execution_stage: "E1"`, `MAX_LIVE_CAPITAL_GBP: 0`, all three breakers `null`, `POST_MORTEM_PATH: null` |
| `data/live/` on the screen host | **Does not exist** — no `KILL`, no `HALT_*`, no `RECONCILE_BLOCK`, no intents/cards/fills |
| `research/registry.yaml` parity across both ATS clones | **Identical** (md5 `950bf80d4550cd4a53f7a2764ad5c252`) |

---

# 3. Cohort / sleeve history — and the direct answer to Q-01

## Q-01 — Legacy Cohort forced sunset (2026-08-23): **DID NOT FIRE. Answered from this host's own data.**

**Direct read of the authoritative book**, `/root/agent/ats-live/data/paper_positions.yaml`:

```
n positions: 12   cohorts: {'legacy_pre_fix': 12}   opened: ['2026-05-25']
tickers: ACM, AMAT, DY, EMR, GD, GNRC, HUBB, J, KMI, LDOS, SPGI, TRGP
data/paper_trades.jsonl: ABSENT
```

Twelve `legacy_pre_fix` positions remain open, nine days past the mandated close. **The laptop's finding
transfers — but the cause is worse than the laptop could see, and it is not inaction.**

**The screen cron fires reliably and has done so every week.** Sixteen log files exist, one pair per
Sunday, `2026-07-12` through `2026-08-30`. **All eight runs failed identically at Step 1:**

```
[09:22:04] Step 1: run_universe.py
Traceback (most recent call last):
  File "scripts/run_universe.py", line 22, in <module>   from src.orchestrator import run_pipeline
  File "src/orchestrator.py", line 17, in <module>       from .agents.model import build_model
  File "src/agents/model.py", line 12, in <module>       from openpyxl import Workbook
ModuleNotFoundError: No module named 'openpyxl'
=== Cohort-1 weekly screen end (rc=1) ===
```

`grep -l openpyxl logs/*.log` matches **all 16 logs**; every run ends `rc=1`. The **first** deployed run
(2026-07-12) failed the same way. **The Cohort-1 weekly screen has never once succeeded.**

**Consequences, stated plainly:**
1. `process_screener_results` — which contains **both** the forced-sunset pass and all entry/exit logic —
   **has never executed.** The sunset mechanism is present in code and correct; it is simply never reached.
2. `runs/_screen/` contains **only** an `audits/` subdirectory — **no screen output has ever been written**.
3. `data/paper_positions.yaml` and `screen_state.yaml` are untouched since **2026-07-06 08:29** (deploy day).
4. **Cohort-1 has produced zero evidence in the 8 weeks since deployment, and registry entry 003's
   52-week clock has been running against a pipeline that crashes before it can open a position.**
5. The failure is a **missing Python dependency in `ats-live/venv`** — `openpyxl` is imported by
   `src/agents/model.py` to write the Excel model. It is in `requirements.txt`; the venv predates or
   missed it.
6. **Nothing alerted.** `run_ats_screen.sh` captures `rc` into the log and exits with it, but cron has no
   MAILTO configured and the ATS Telegram credentials are absent from the cron environment (§2.11), so
   eight consecutive total failures produced **no signal whatsoever**. This is the 2026-08-07
   "committed but not wired" failure mode in a new place (§7 DR-01).

**What did keep working** in the same script, and is worth protecting: Step 0 universe-liveness
(283 tickers checked, 269 live, 14 suspects flagged as likely delisted — AIRP, ALXN, DNKN, GIVN, HEES,
HOLX, HYATT, JNPR, NEFF, SGEN, SKX, SRCL, SYNNX, WBA); Step 0b extraction audit (**35 violations,
15 SEV_HIGH** on 2026-08-30, non-blocking by design, written to `runs/audits/`); Step 0c
`log_eps_trend.py` — **147 rows logged every week into `data/eps_trend_history.jsonl` (195 KB, live to
2026-08-30)**. Study A's forward-observation clock (§4C of the laptop half) **is genuinely accruing** and
is the one Cohort-1-adjacent thing that is healthy.

> **Note on the 283-vs-147 discrepancy:** Step 0 checks liveness of **283** tickers while Steps 0b/0c
> operate on **147**. The laptop half records a doc/reality divergence on universe size (61 → 147);
> this is a third number, from a different input list, and is unexplained (§8 Q-D6).

## Cohort table — droplet-authoritative

| Cohort / arm | State on this host | Delta vs laptop half |
|---|---|---|
| **Legacy Cohort** | 12 `legacy_pre_fix`, opened 2026-05-25, **still open, sunset missed** | Same positions; **cause now known** (screen crash, not "no screen was run") |
| **Cohort-1 / `oracle_v1`** | **0 positions, 0 trades, 0 successful screens.** Lock registered 2026-07-05; screen deployed 2026-07-06; 8/8 runs failed | Laptop said "armed but empty"; it is **armed, empty, and actively broken** |
| **Phaethon Arm A** | 14 positions, source scorecard live to 2026-08-31 22:30, mark `rc=0` | Matches published render exactly (§5) |
| **Phaethon Arm B** | 10 positions, **source scorecard frozen at 2026-08-06 23:30**, mark failing daily | **Published render is stale — major finding (§5)** |
| **Phaethon Arm C (control)** | 37 positions, equal-weight, **no LLM**, live to 2026-08-31 21:15, `active_return −8.64%`, `vs_qqq −8.63pp`, `vs_smh +1.51pp`, 60 marks | **Entirely absent from the laptop half and from the public dashboard** |
| **Olympus council book** | Empty (`satellite: {}`), 14 fills all on 2026-06-04 | Laptop's copy showed 28 fills / 11 decisions — a **stale divergent copy** (§7 DR-02) |
| **Olympus growth arms A/B/C** | `arm_{A,B,C}_portfolio.json` unchanged since 2026-06-04; not on any cron | Laptop copy identical in kind; confirms dormancy |

---

# 4. Research registry — unchanged, with one droplet-only artifact

`research/registry.yaml` is **byte-identical** on both droplet clones and matches the laptop half:
**001 FAILED** (momentum, NW t = 0.09), **002 FAILED** (PEAD), **003 TESTING** (Oracle/Cohort-1
STRONG_BUY vs SPY TR), plus the 2026-07-06 `backfill_interpretation_contract` migration. Full verbatim
entries, mechanisms, thresholds, hashes and interpretation contracts are in the laptop half §4A and are
**not duplicated here**.

**Droplet-only artifact:** `research/revisions_pt_validation/pt_calibration_results.csv` and
`full_run.log` are **present but untracked** on the panel repo. These are the raw 1,029-ticker-year
outputs behind `FINDINGS_pt_calibration.md` (rank IC +0.136 all / +0.097 ex-flagged, both below the
≥0.30 bar). **The memo is committed; its underlying data exists only here, uncommitted.** If this
droplet is lost, the finding survives but the data behind it does not (§8 Q-D5).

**Status of 003 on this host, stated precisely:** still `TESTING`, and — per §3 — with **no possibility
of accruing evidence** while the screen crashes. The registry is honest; the pipeline feeding it is not
running.

---

# 5. Phaethon — source book vs published render (first direct comparison)

The laptop half derived everything from `docs/data/phaethon_*.json` (the render). This is the first
look at the source. **They do not agree for Arm B.**

## 5.1 Arm A — source and render agree exactly

`trader/state/scorecard_public.json` (written 2026-08-31 22:30): 14 positions
(CEG, ANET, GEV, AMZN, AVGO, VST, LLY, MSFT, FSLR, VRTX, REGN, V, PANW, ZS), `active_return_pct 8.35`,
`vs_qqq_pp 9.32`, `trend "DEGRADING vs QQQ"`, `n_marks 75`. **Identical to the published render.**
Arm A's mark ran `rc=0` on 2026-08-31. **Arm A is healthy.**

## 5.2 Arm B — **FROZEN SINCE 2026-08-07; THE DASHBOARD HAS BEEN PUBLISHING STALE DATA WITH A FRESH DATE STAMP**

This is the most serious operational finding of either run.

**Evidence chain:**

1. `trader_b/state/scorecard_public.json` — last written **2026-08-06 23:30**. Contents:
   `active_return_pct 12.48`, `vs_qqq_pp 11.12`, `n_marks 50`, `drawdown_pct −2.8`, `halted false`.
2. `docs/data/phaethon_b_live.json` — published **`as_of: 2026-08-31`**, and carries **exactly those
   same numbers**: 12.48 / 11.12 / 50 marks / −2.8. The publisher stamped a current date onto a
   scorecard that stopped updating 25 days earlier.
3. `trader_b/state/cron.log`, last entries:
   ```
   File "/app/phaethon_trader/book.py", line 30, in save   STATE.write_text(...)
   PermissionError: [Errno 13] Permission denied: '/app/phaethon_trader/data/book.json'
   [2026-08-31T23:30:01Z] phaethon_b mark rc=1
   [2026-08-31T23:30:01Z] phaethon_b mark FAILED — fail loud
   ```
4. **Root cause, confirmed by file ownership:**
   ```
   -rw-r--r-- 1 phaethon phaethon  /home/phaethon/phaethon/trader/state/book.json    (Aug 31 22:30)
   -rw-r--r-- 1 root     root      /home/phaethon/phaethon/trader_b/state/book.json  (Aug  7 14:39)
   -rw-r--r-- 1 phaethon phaethon  /home/phaethon/phaethon/trader_c/state/book.json  (Aug 31 21:15)
   ```
   **The 2026-08-07 constitutional trim was run as `root` and rewrote `book.json` root-owned.** The
   containerised trader runs as `phaethon` and has been unable to write its own book ever since.
   Arms A and C, untouched by the trim, are still `phaethon`-owned and still marking normally.
   The mtime `Aug 7 14:39` matches commit `c9d53c6` (2026-08-07 14:42) to the minute.

**So the 2026-08-07 trim — which correctly fixed a real constitutional breach — simultaneously froze the
arm it was fixing, and the freeze went unnoticed for 25 days because the publisher kept emitting a
current-dated panel from the last good scorecard.** The trim itself was sound; the permission side-effect
was not. This is the *inverse* of the failure the same commit fixed: there, governance existed but did
not run; here, governance ran and broke the thing it governed.

**What the published render is therefore NOT telling the reader:** `status: CONFORMING`,
`governance.conforming: true`, `violations: []`, `gross_exposure_pct: 86.9` are all evaluated against a
book that has not moved since 2026-08-07. The conformance statement is true of the frozen book and says
nothing about today. `restated: "restated 2026-08-31, cash-accounting bug fixed"` is likewise a
publish-time stamp, not a fresh restatement — which resolves the laptop half's open item on why the
memo said 2026-07-05 and the JSON said 2026-08-31.

## 5.3 Both LLM arms — idea generation is dead: OpenRouter **402 Payment Required**

`trader/state/cron.log` and `trader_b/state/cron.log`, both on 2026-08-31:

```
requests.exceptions.HTTPError: 402 Client Error: Payment Required for url:
https://openrouter.ai/api/v1/chat/completions
[2026-08-31T22:00:01Z] phaethon propose rc=1 — FAILED — fail loud, NO fallback (OpenRouter capped/unreachable?)
[2026-08-31T23:00:01Z] phaethon_b propose rc=1 — FAILED — fail loud
```

**Neither LLM arm has been able to generate a proposal.** The design does exactly what it should — *"fail
loud, NO fallback"*, never substituting a data-only fake for the model (the same principle as the
council loop's *"it never falls back to a data-only fake"*). But the practical state is that **Phaethon's
generator has been off**, while Arm A continues to mark its existing book and Arm B cannot even do that.

## 5.4 Arm C — the control arm nobody can see

`trader_c` is a **mechanical equal-weight control: 37 positions, `no_llm: true`, zero Zeus, zero
judgment**, `control_version 1.0`, `phaethon_version 1.2.0`, rebalanced Mondays 21:00, marked weekdays
21:15, live to 2026-08-31. Its own note states the purpose exactly: *"The honest yardstick: the LLM arms
must beat THIS net of costs to add value."*

| Arm | active_return | vs QQQ | vs SMH | marks | book_total_rf |
|---|---:|---:|---:|---:|---:|
| A (disciplined, LLM) | +8.35% | +9.32pp | +18.41pp | 75 | 10,170.60 |
| B (aggressive, LLM) — **frozen 2026-08-06** | +12.48% | +11.12pp | +20.14pp | 50 | 10,408.34 |
| **C (control, no LLM)** | **−8.64%** | **−8.63pp** | +1.51pp | 60 | 9,382.49 |

**Arm C is not published anywhere.** `docs/data/` has `phaethon_live.json` and `phaethon_b_live.json`
and no arm-C equivalent; the panel commit message says *"both arms"*. So the one comparison the
experiment was built to make — LLM arms vs the mechanical control — **is computed nightly on this host
and shown to nobody** (§8 Q-D1).

**Also visible only in the source scorecards** (the render drops them): `vs_smh_pp`, `benchmark_factor:
"SMH"`, `book_total_rf`, `cash_interest_accrued`, `rf_annual_pct: 4.0`. The v1.2 measurement upgrade
(SMH factor benchmark + cash at the risk-free rate) is **live in the trader and absent from the panel**.

## 5.5 Version/backup discipline — confirmed working

`_backup_pre_v1.1_20260624T142438Z/` and `_backup_pre_v1.2_20260624T150916Z/`, with
`_LAST_PRE_V11_BACKUP` / `_LAST_PRE_V12_BACKUP` pointers, plus per-arm `version_log.jsonl`. The
v1.1 aperture and v1.2 exits/measurement deploys of 2026-06-24 were snapshotted before the change,
exactly as `NEXT_STEPS.md` (laptop-side) describes. Book `as_of` fields — A `2026-06-05`, B `2026-06-07`,
C `2026-06-24` — record each arm's inception.

## 5.6 Learning mechanism — still never run, and now a shadow ledger appears

`data/phaethon/` artifacts (journal, lessons ledger, `LEARNING_SUSPENDED`) remain absent, consistent
with the laptop half. But a **shadow ledger** runs that the laptop half never saw:
`shadow_ledger/run_shadow.sh` writes `trader{,_b}/state/shadow_ledger.jsonl` (15.6 KB / 11.9 KB, both
live to 2026-08-31), described in cron as *"observation-only gate calibration … Does NOT touch
book/Zeus/trading."* Memory of prior sessions notes a "resume when shadow ≥50 closed" condition; that
ledger is accruing here.

---

# 6. Live pilot — E1: inert, and confirmed inert on the host that would run it

| Check on `/root/agent/ats-live` | Result |
|---|---|
| `config/live_limits.yaml` vs committed | **No local override.** `execution_stage: "E1"`, `MAX_LIVE_CAPITAL_GBP: 0`, `DAILY_LOSS_HALT_PCT: null`, `WEEKLY_LOSS_HALT_PCT: null`, `CUMULATIVE_KILL_PCT: null`, `POST_MORTEM_PATH: null` |
| `data/live/` | **Directory does not exist** — no `KILL`, no `HALT_DAILY`/`HALT_WEEKLY`, no `RECONCILE_BLOCK`, no intents, cards, or fills |
| Any live-pilot cron | **None.** No cron entry references `live_kill.py`, `live_drill.py`, or any card generation |

With capital at 0 and all three breakers `null`, the guard layer's fail-safe **blocks card generation**
rather than skipping the check. **The pilot has never been armed on this host.** The November-2026 start
and the capital authorization remain the operator's gate, exactly as the laptop half records.

One caveat this run can add: the tree that would run the pilot is `ats-live` @ `fcd9198`, which **does
have** the full `src/live/` layer (it was committed 2026-07-06, `2c54632` + `d9aee40`, both in its
history) — so the E1 machinery is present here, just unarmed and 37 commits behind on everything else.

---

# 7. Major standing decisions — droplet-only additions and droplet-confirmed findings

The 39 decisions D-01…D-39 in the laptop half stand unchanged. Added here are decisions and findings
that exist **only** on this host.

| # | Date | Decision / finding | Reasoning | Status |
|---|---|---|---|---|
| **D-D1** | 2026-06-10 | **Trading 212 demo adapter disabled and its key archived** — flag + constructor raise + CLI removal + secret moved out of the search path | A live demo-broker path *"was not meant to sit live on the droplet."* It becomes available again only as a Paper-substage venue smoke test, after a strategy earns Paper (`n_resolved ≥ N_RESOLVED_MIN`, positive vs-ACWI net of realised cost) **and** a typed Director approval `(DROPLET-LOCAL)` | **CURRENT — verified `True` today** |
| **D-D2** | 2026-06-15 → 2026-06-16 | **Atomic-deploy discipline adopted after a real incident**: the 21:45 cron caught a non-atomic Hermes-adapter refactor mid-edit; the run failed (`ImportError`) | *"A missed run is recorded honestly as a gap"* — 0 entries in all sacred ledgers, no corruption, **no backfill**. Fixed in `01af678`; discipline written up in `atomic_deploy.md` `(DROPLET-LOCAL)` | **CURRENT** |
| **D-D3** | 2026-06-10 | **Kill criterion hash-locked as a pre-registration** — `N_RESOLVED_MIN=30`, `MIN_HIT_RATE_PCT=50`, `MIN_VS_ACWI_BPS_NET=0`, auto-pause on 3 consecutive resolved decisions worse than −10% | Codify the stopping rule before there is any result to argue about; the loop checks it **before opening any position** `(DROPLET-LOCAL)` | **CURRENT — unreachable in practice, `n_resolved = 0`** |
| **D-D4** | 2026-06-10 | **`portfolio_policy.real.yaml` intentionally absent on the droplet** — the Director must hand-provide it; while absent, Hecate's core-overlap check reports *"CORE NOT SUPPLIED … INCOMPLETE"* | The file would contain real holdings — *"not Claude-Code's job"* `(DROPLET-LOCAL)`. **Note:** the laptop's `olympus/` copy **does** contain a `portfolio_policy.real.yaml`, so the two copies differ in exactly the way this decision cares about | **CURRENT on droplet; divergent on laptop** |
| **D-D5** | 2026-06-09 | **Droplet Telegram sender disabled**; alerting made self-contained (flag file + scorecard banner) | *"Nothing that can be silently switched off"* `(DROPLET-LOCAL)` | **CURRENT — with an unintended consequence, see DR-01** |
| **D-D6** | 2026-06-15 | **EPE quarterly rebalance and weekly full refresh PARKED** (commented in crontab with reasons: MOM_TOP5 parked-but-resolving, data ceiling; Tiingo quota — accepted datapoint loss) | Park with the reason written into the crontab itself rather than deleting the line `(DROPLET-LOCAL)` | **CURRENT** |
| **D-D7** | 2026-07-06 | **`run_ats_screen.sh` deployed to replace the "disconnected `/root/agent/olympus` loop as Cohort-1 evidence"** — with a rebase-guarded public push that *"aborts LOUD, never force-pushes"* | The council loop was not producing Cohort-1 evidence, so the locked ATS pipeline was scheduled directly `(DROPLET-LOCAL: the script's own header)` | **CURRENT in schedule, FAILED in execution (§3)** |
| **DR-01** | 2026-07-12 → today | **FINDING: eight consecutive total failures of the Cohort-1 screen produced no alert.** `rc=1` is captured and returned, but cron has no MAILTO and the ATS Telegram vars are absent from the cron environment | The 2026-08-07 lesson ("governance committed but not wired") recurring in the alerting layer | **OPEN — §8 Q-D3** |
| **DR-02** | — | **FINDING: the laptop's `olympus/` directory is a stale, divergent copy** — laptop shows 11 decisions / 28 fills / `arm_*` with negative cash; droplet shows **546 decisions / 14 fills** and an empty book. This is Director **Q4** (two-copy drift), explicitly left open in Option A scope | Two copies of an unversioned-until-June system | **OPEN — the droplet copy is authoritative** |
| **DR-03** | 2026-07-06 → today | **FINDING: the Cohort-1 screen host is 37 commits behind and predates `c9d53c6`** — it has none of the 2026-08-07 governance/trim infrastructure | Deployed once, never updated | **OPEN — §8 Q-D7** |
| **DR-04** | 2026-08-07 → today | **FINDING: the constitutional trim froze Arm B** by leaving `book.json` root-owned (§5.2) | A root-run maintenance script on a tree owned by a service user | **OPEN — highest-severity item in this document** |

---

# 8. Open questions awaiting operator decision — droplet additions

The laptop half's Q-01…Q-19 stand. **Q-01 is now ANSWERED** (§3: the sunset did not fire; the screen has
never succeeded; the fix is a missing `openpyxl` in `ats-live/venv`, and it is the operator's call
whether to install it, given that doing so would start a real Cohort-1 screen for the first time and
immediately force-close the legacy book). The following are new.

| # | Question | Evidence |
|---|---|---|
| **Q-D1** | **Should Arm C be published?** The control arm — the one comparison that decides whether the LLM arms add value — runs nightly and appears on no dashboard. Its own note calls itself *"the honest yardstick."* Arm C is at −8.64% vs QQQ while the LLM arms are positive; publishing it changes what the panel claims. | `trader_c/state/scorecard_public.json`; `docs/data/` has no arm-C file |
| **Q-D2** | **Arm B: restore, or freeze deliberately?** It has been unable to mark for 25 days. Fixing the ownership restarts it mid-window; leaving it frozen makes the published series a snapshot. Either way the panel must stop showing a current date on 2026-08-06 data. This also re-opens laptop Q-03 (live candidate vs falsification control) on new facts. | §5.2 |
| **Q-D3** | **Nothing alerts on ATS-side failure.** Eight silent total failures. Does the operator want cron MAILTO, the Telegram vars in the cron environment, or the olympus-style flag-file pattern extended to `ats-live`? | §3, §2.11 |
| **Q-D4** | **Mnemosyne has resolved nothing in 11 weeks** — `resolved 0, failed 425` on the latest run, `resolutions=0` across the whole ledger, while the chain verifies clean. Is the resolver broken, or is nothing genuinely maturing? Either way `n_resolved = 0` keeps the pre-registered promotion gate (D-D3) permanently unreachable. | `data/cron.log`, `run_mnemosyne_resolve.sh` self-check |
| **Q-D5** | **`pt_calibration_results.csv` (1,029 ticker-years) exists only here, uncommitted.** Commit it, archive it, or accept that the memo's numbers become unreproducible if the droplet is lost? | Panel repo `git status` |
| **Q-D6** | **Three different universe counts** — Step 0 checks 283 tickers, Steps 0b/0c use 147, older docs say 60/61. What is the 283-name list and should it be reconciled? | `logs/olympus_screen_20260830.log` |
| **Q-D7** | **Should `ats-live` be updated?** It is 37 commits behind and lacks all 2026-08-07 governance code. Updating it changes the tree that runs the locked ruleset — which is itself a protocol-relevant act. | §ESCALATION, DR-03 |
| **Q-D8** | **Director Q4 (two-copy drift) and Q6 (Hermes adapter/import) remain open**, explicitly deferred out of Option A scope on 2026-06-10, along with `git init` of `agent/olympus` (now done locally, 2026-08-18) and cross-copy report publication. | `director_decisions_2026-06-10.md` §"Explicitly NOT in this change" |
| **Q-D9** | **The council has held for 534 consecutive decisions.** Is three months of unbroken abstention the design working, or evidence that the actionable bar is set where nothing can clear it? The system cannot distinguish these two states from the inside. | §1B |
| **Q-D10** | **The council code has no remote.** One unpushed local repo, backed up only by an encrypted restic job. Should it be pushed to a private remote? | §A |
| **Q-D11** | **Both LLM arms' propose has been failing on OpenRouter 402.** Fund the account, switch provider, or accept the generator being off? | §5.3 |

## Document disagreements settled or added by this run

| Subject | Laptop / prior state | Droplet reality | Current |
|---|---|---|---|
| *"Only Oracle and Phaethon have backing code"* | `OLYMPUS_SYSTEM_STATE §1.3`, echoed in the laptop half §1 | **False for this host** — a ~4,500-line council with Zeus, Tyche, Hecate, Athena-Nemesis, Themis-Mnemosyne, Artemis, Chronos, Hephaestus, and Mnemosyne runs nightly | **Droplet is authoritative.** The ATS-repo statement is true *of the ATS repo* and misleading as a system claim |
| `safe_deploy.sh` absent | `OLYMPUS_SYSTEM_STATE §7 #10` | Present at `/root/agent/olympus/scripts/safe_deploy.sh` | **Divergence resolved — it exists, in the unpushed repo** |
| Prior KB location/date | Laptop half: *"on the droplet at `/root/phaethon-panel-repo/docs/` from 2026-08-07"* | Actually `/root/agent/olympus/docs/`, committed **2026-08-18** (`1bca7a1`); the file's own header says 2026-08-07 | **Both corrected here** |
| Prior KB: Arm A *"14 positions, 66% cash, 38% gross"* | `OLYMPUS_KNOWLEDGE_BASE.md §3` | Internally impossible (66 + 38 = 104). Render says 66.5% cash / 33.5% gross | **Render is current; the prior KB carried an arithmetic error** |
| Prior KB §9: *"CANNOT cover droplet/cron/tmux state"* | Its own stated limitation | It was **written on the droplet** and still declined to look at cron state | Noted — the gap this run closes |
| Arm B `restated: 2026-08-31` | Laptop half concluded the string is re-stamped each publish | **Confirmed** — and now known to be re-stamped onto data frozen 2026-08-06 | **Confirmed, with the staleness caveat** |
| Arm B `CONFORMING` | Laptop half: current as of 2026-08-31 | True of the frozen book; **not** a statement about today | **Amended by §5.2** |
| Cohort-1 *"armed but empty"* | `OLYMPUS_SYSTEM_STATE §6(c)1`, laptop half §3 | Armed, empty, **and crashing weekly since deployment** | **Amended — the cause is a broken dependency, not inaction** |
| Registry parity | — | Identical md5 across both droplet clones and the laptop | **No drift** |

**One new decision surfaced from the prior droplet KB** that appears nowhere else in either corpus and
should not be lost: **"29–30% CAGR ceiling? — CURRENT: YES. SPY + 1–4pp baseline, +5–7pp conditional.
Margin of error → 1–4pp defensible, >7pp never cleared."** (`OLYMPUS_KNOWLEDGE_BASE.md §7`). No
supporting document for it exists on either machine; recorded here verbatim and flagged as
**unsourced** (`DROPLET-LOCAL`, prior-KB assertion only).

---

# 9. Known gaps — what THIS run cannot cover

**This spec ran twice because neither location can see the other.** This is the droplet half; the laptop
half is `docs/OLYMPUS_KNOWLEDGE_BASE_LAPTOP.md`. **Do not treat this file as complete on its own** — it
deliberately does not re-derive what the laptop already holds.

## What this droplet run cannot see (and does not attempt to reconstruct)

1. **The entire laptop-only design corpus** — `council_architecture_note.md` (the precondition gate and
   the three traps), `lessons_learned.md` (the 13-strategy falsification table and the cost-access
   pattern), `olympus_system_review.md` (9/10 architecture vs 1/10 evidence), `Olympus_Build_Prompt_v1.2.md`
   (§2 constraints, §6 Aeolus trap, §7 correlated-council, §8 ETF-alternative, §9 core+satellite), the
   Hades/Caerus/Mercury/Metis design notes, `NEXT_STEPS.md`, `INFRA_INVENTORY.md`, `NAME_MAP.md`,
   `WORKING_STYLE.md`, the EPE/ESE public summaries, `Olympus_System_Overview.docx`, and the status
   briefing. **None of it exists on this host.** Every council-design rule and almost the whole
   falsification record is laptop-only. For §4B-equivalent content, read the laptop half.
2. **`~/trading/ecosystem_architecture.md`** — the cited source for the RP/QRE 19.86%-vs-66.17%
   discrepancy and several Nike/Iris verdicts. Not on this host, not in any repo.
3. **The Mac-side publisher and its degraded log** — `com.ats.live-refresh`, the `ATS Live Refresh`
   commits, and the `n_priced=0` staleness in `logs/live_dashboard.log` (laptop Q-09, Q-10).
4. **Anything inside a container, tmux session, or another user's environment.** The Phaethon traders run
   containerised (`/app/...` paths in their tracebacks); this run saw their **state directory and logs
   from the host side only**. `gateway-data/` is owned by uid 10000 and was not entered.
5. **Interactive/session state** — no shell history, editor buffers, or tmux panes were inspected, per
   the read-only remit.
6. **Whether the olympus test suite passes today.** Running pytest on a live production tree is
   write-adjacent (it creates caches, and `atomic_deploy.md` treats the tree as the running system), so
   it was not run. Suite health is **asserted by the deploy discipline, not verified by this run.**
7. **The contents of any secret** — by instruction. The five credential stores and the pm2 dump were
   noted as existing and never opened. A prior session's
   note that the pm2 dump contains plaintext credentials is therefore **neither confirmed nor refuted
   here**.
8. **`~/labs/oracle` internals** — the council imports the real Oracle (`from oracle import forward_test`)
   via a `sys.path` bridge. The bridge was traced; the Oracle repo itself was not walked.
9. **The 2026-06-15 incident's code fix (`01af678`)** was read about, not read.

## What the laptop run could not see, now closed by this one

The council implementation and its execution reality (§1A/§1B); the Cohort-1 screen's true state and the
Q-01 answer (§3); Phaethon's source book, the Arm B freeze, the OpenRouter outage, and Arm C (§5); the
droplet-only governance layer — atomic deploy, the second hash-lock regime, the kill criterion, the T212
disablement, the incident log (§2, §7); the prior knowledge base's real location, date, and content (§B).

## Structural gaps neither location closes

- **Zero closed trades exist anywhere in the primary evidence path.** `data/paper_trades.jsonl` is absent
  on both hosts. Registry 003 has no data on either side, and now cannot get any until the screen is fixed.
- **The council's 546 decisions are not in any registry entry.** They are `LIVE_OOS` records in an
  unpushed local ledger, governed by a hash-locked kill criterion that lives in the same unpushed repo.
  The ATS-side registry (001–003) and the council's evidence stream **do not reference each other**.
- **`OLYMPUS_SYSTEM_STATE.md` is ~8 weeks stale** on both hosts and predates every finding in §3 and §5.
- **Two knowledge bases now describe the same system with different scopes** (the 2026-08-18 droplet one
  and this two-part 2026-09-01 pair). The older one should be superseded explicitly, not left to be found.

---

*Compiled 2026-09-01 from `ats-trading` over read-only SSH; written to the laptop repo so both halves sit
side by side for diffing. No droplet file was modified. Refresh commands (run on the droplet):
`crontab -l` · `tail /root/agent/olympus/data/cron.log` · `ls /root/agent/ats-live/logs/` ·
`grep -c openpyxl /root/agent/ats-live/logs/*.log` · `ls -l /home/phaethon/phaethon/trader*/state/book.json` ·
`cat /home/phaethon/phaethon/trader_c/state/scorecard_public.json` ·
`git -C /root/agent/olympus log --oneline -5`. Where this document and the running system disagree, the
system wins — re-walk it.*
