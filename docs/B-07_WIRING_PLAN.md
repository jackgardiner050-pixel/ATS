# B-07 — Positive heartbeats & dead-man's switch for all scheduled jobs

**Status:** REVIEW ONLY. Nothing in this plan has been applied. No crontab, no
`run_*.sh`, and nothing on the droplet's live trees was modified while producing
it. The droplet was accessed read-only.

**Branch:** `b-07-heartbeats` in worktree `/Users/jackgardiner/agent-b07` (ATS repo). Not committed.

---

## 1. What B-07 adds

| Piece | Repo path (this branch) | Deployed to droplet as |
|---|---|---|
| Heartbeat CLI (`write` + `check`) | `scripts/heartbeat.py` | `/root/ops/heartbeat.py` |
| Cron wrapper helper | `scripts/heartbeat-wrap.sh` | `/root/ops/heartbeat-wrap` |
| Expected-jobs registry | `config/expected_jobs.yaml` | `/root/ops/expected_jobs.yaml` |
| Tests | `tests/test_heartbeat_jobs.py` | (repo only) |
| This plan | `docs/B-07_WIRING_PLAN.md` | (repo only) |

Runtime state the checker owns (created once, see §6):

| Path | Contents | Perms |
|---|---|---|
| `/root/ops/heartbeat/<slug>.json` | last-run record per job (atomic write; `heartbeat.py` chmods 0644 after `os.replace`) | `root:root` 0644 |
| `/root/ops/alerts/ALERT_<slug>_heartbeat.flag` | one flag file per unhealthy job; auto-cleared on recovery | `root:root` 0644 |
| `/root/ops/jobs_health.txt` / `jobs_health.json` | rendered jobs-health table + machine blob for the dashboard | `root:root` 0644 |
| `/root/ops/logs/heartbeat_check.log` | stdout/stderr of the daily `check` run | `root:root` 0644 |

All four are written via `mkstemp` (mode 0600) + atomic `os.replace`; `heartbeat.py`
then `os.chmod`s each to **0644** after the replace — nothing in a heartbeat,
flag or health file is secret, and §11.11 wants the dashboard (a non-root reader)
to be able to read `jobs_health.json` and `<slug>.json`. The flag files are
written with a plain `open(..., "w")` so they already land at 0644 under root's
umask. No further `chmod` step is needed in §6.

---

## 2. Heartbeat home + rationale

**Chosen home: a standalone `/root/ops/` tree — NOT inside any repo.**

`scripts/heartbeat.py` is the source of record in the ATS repo; it is **copied**
(not symlinked — the repo is not checked out at a stable path usable by every
tree) to `/root/ops/heartbeat.py` and invoked as
`/usr/bin/python3 /root/ops/heartbeat.py`.

Why this and not "put it in one repo on `PYTHONPATH`":

* **The investigation showed every one of the live cron lines runs as `root`.**
  `crontab -u phaethon -l` → *"no crontab for phaethon"*; `/etc/crontab` and
  `/etc/cron.d/*` contain nothing for these jobs. The `phaethon` user only exists
  as the `docker run --user 1000:1000` UID *inside* the Phaethon containers and as
  the owner of two wrapper files (mode 0755 — root executes them fine). So there
  is exactly **one writer: root**, and one write target: `/root/ops/heartbeat/`.
  No shared-group / per-user-subdir gymnastics are needed. (If the Phaethon lines
  are ever moved to a real `phaethon` crontab, see §10 for the group-perms
  variant — a 4-command change.)
* `heartbeat.py write` (the hot path — it runs on all 21 lines) is **pure
  stdlib**. It never imports `yaml`, never needs `PYTHONPATH`, never needs a repo.
  `heartbeat.py check` (one line, 06:00) uses `PyYAML` (present in the droplet's
  system `python3` — 6.0.1) with a small built-in fallback parser so it still
  works if that ever breaks.
* The seven job trees (`/root/epe`, `/root/trading/hermes_v3_lab`,
  `/root/agent/olympus`, `/root/agent/ats-live`, `/root/phaethon-panel-repo`,
  `/home/phaethon/phaethon/*`, `/root/labs/oracle`, `/root/backup`) have no common
  parent repo and four of them are not git repos at all. A neutral `/root/ops/`
  is the only location that is equally reachable from all of them with a single
  absolute path.
* This does **not** collide with the pre-existing, unrelated
  `docs/data/heartbeat.json` + `_heartbeat_state()` in
  `scripts/generate_dashboard.py` (that is a narrow Hermes-v3 dashboard-staleness
  badge). Different name, different files, different directory.

---

## 3. The wrapper pattern — a helper, not inline `$?`

**Recommended: `/root/ops/heartbeat-wrap`.** Every job line becomes:

```
<schedule>  /root/ops/heartbeat-wrap <slug> -- <original command> [args]   [original redirect]
```

`heartbeat-wrap` runs the real command, captures its **exact** exit code, calls
`heartbeat.py write <slug> --rc <that code>`, then `exit`s the same code. A
heartbeat failure prints a warning and never changes the job's exit status.

### Why not the inline form `<cmd>; /usr/bin/python3 /root/ops/heartbeat.py write <slug> --rc $?`

* **Line 5** (`cd /root/epe && venv/bin/python scripts/universe_check.py`): `$?`
  after a `&&` chain is the chain's last step — usually fine, but the redirect and
  the `cd` semantics make it easy to get wrong on edit.
* **Lines with a trailing `# comment`** (the `backup` and `mnemosyne_resolve`
  lines today): cron passes the whole line to `/bin/sh -c`, and a `#` mid-line
  starts a shell comment — an inline `; … --rc $?` appended *after* the comment is
  silently swallowed. The helper sidesteps this entirely.
* The helper records a consistent `entrypoint` and best-effort `git_sha` (the
  directory of the first path-like argument) with zero per-line reasoning.

The pure-inline form is still available for an operator who refuses a new shell
artifact — but then lines 5, 16 and 17 must be hand-checked and the trailing
comments on 16/17 must move to their own line first.

---

## 4. The exact new crontab (full file)

Save as `~/crontab.b07.new` and apply with `crontab ~/crontab.b07.new` (see §6).
`<OPERATOR_EMAIL>` is the only placeholder to fill.

```cron
# ============================================================================
#  ATS droplet crontab — B-07 heartbeat wiring applied.  All times UTC.
#  Every job line is wrapped by /root/ops/heartbeat-wrap <slug> -- <cmd>, which
#  records /root/ops/heartbeat/<slug>.json {ran_at,rc,git_sha,entrypoint,host,user}
#  and RE-EXITS the job's real exit code (heartbeat-wrap never changes it).
#  Slugs are defined in /root/ops/expected_jobs.yaml.  Rollback: crontab ~/crontab.pre-b07.bak
# ============================================================================
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=<OPERATOR_EMAIL>
HEARTBEAT_CONFIG=/root/ops/expected_jobs.yaml
HEARTBEAT_DMS_URL_FILE=/root/.secrets/heartbeat.env

# === EPE (Experimental Pot Engine) — migrated from Mac 2026-05-12 ===
# Mac LaunchAgents are paused (plists in disabled/).

# price panel update: weekdays at 22:00 UTC (23:00 BST, post US market close)
0 22 * * 1-5 /root/ops/heartbeat-wrap epe_price_updater -- /root/epe/scripts/price_updater.sh >> /root/epe/logs/price_updater.log 2>&1

# kill flags check: weekdays at 17:00 UTC (18:00 BST)
0 17 * * 1-5 /root/ops/heartbeat-wrap epe_kill_flags -- /root/epe/scripts/kill_flags.sh >> /root/epe/logs/kill_flags.log 2>&1

# quarterly rebalance: PARKED-2026-06-15 (MOM_TOP5 parked; data ceiling) — unchanged:
# 0 19 31 3 * /root/epe/scripts/quarterly_rebalance.sh >> /root/epe/logs/quarterly_rebalance.log 2>&1
# 0 19 30 6 * /root/epe/scripts/quarterly_rebalance.sh >> /root/epe/logs/quarterly_rebalance.log 2>&1
# 0 19 30 9 * /root/epe/scripts/quarterly_rebalance.sh >> /root/epe/logs/quarterly_rebalance.log 2>&1
# 0 19 31 12 * /root/epe/scripts/quarterly_rebalance.sh >> /root/epe/logs/quarterly_rebalance.log 2>&1

# weekly status: Monday at 07:00 UTC (08:00 BST)
0 7 * * 1 /root/ops/heartbeat-wrap epe_weekly_status -- /root/epe/scripts/weekly_status.sh >> /root/epe/logs/weekly_status.log 2>&1

# morning check: daily at 07:05 UTC — silent on non-rebalance days (still runs, still exits 0)
5 7 * * * /root/ops/heartbeat-wrap epe_morning_check -- /root/epe/scripts/morning_check.sh >> /root/epe/logs/morning_check.log 2>&1

# universe drift check: Sunday at 08:00 UTC  (redirect path made absolute — heartbeat-wrap does not inherit the cd)
0 8 * * 0 /root/ops/heartbeat-wrap epe_universe_check -- /bin/sh -c 'cd /root/epe && exec venv/bin/python scripts/universe_check.py' >> /root/epe/logs/universe_check.log 2>&1

# === Hermes v3 shadow simulation (paper) — weekdays 21:30 UTC ===
30 21 * * 1-5 /root/ops/heartbeat-wrap hermes_v3_daily -- /root/trading/hermes_v3_lab/scripts/run_droplet_daily.sh

# === Olympus autonomous paper loop (PAPER/SIMULATED) — weekdays 21:45 UTC ===
45 21 * * 1-5 /root/ops/heartbeat-wrap olympus_loop -- /root/agent/olympus/scripts/run_olympus_loop.sh

0 22 * * 1 /root/ops/heartbeat-wrap phaethon_a_propose -- /home/phaethon/phaethon/trader/run_phaethon.sh propose
30 22 * * 1-5 /root/ops/heartbeat-wrap phaethon_a_mark -- /home/phaethon/phaethon/trader/run_phaethon.sh mark
45 22 * * * /root/ops/heartbeat-wrap phaethon_panel_publish -- bash /root/phaethon-panel-repo/scripts/phaethon/publish.sh
0 23 * * 1 /root/ops/heartbeat-wrap phaethon_b_propose -- /home/phaethon/phaethon/trader_b/run_phaethon_b.sh propose
30 23 * * 1-5 /root/ops/heartbeat-wrap phaethon_b_mark -- /home/phaethon/phaethon/trader_b/run_phaethon_b.sh mark

# === Oracle weekly MARK (paper/advisory) — Monday 23:50 UTC ===
50 23 * * 1 /root/ops/heartbeat-wrap oracle_mark -- /root/labs/oracle/run_oracle_mark.sh

# === Phaethon SHADOW LEDGER (observation-only) — Monday, staggered after each propose ===
20 22 * * 1 /root/ops/heartbeat-wrap phaethon_shadow_a -- /home/phaethon/phaethon/shadow_ledger/run_shadow.sh /home/phaethon/phaethon/trader/state
20 23 * * 1 /root/ops/heartbeat-wrap phaethon_shadow_b -- /home/phaethon/phaethon/shadow_ledger/run_shadow.sh /home/phaethon/phaethon/trader_b/state

# === EPE weekly FULL price-panel refresh — PARKED-2026-06-15 (Tiingo quota) — unchanged:
# 0 6 * * 6 /root/epe/scripts/weekly_full_refresh.sh >> /root/epe/logs/weekly_full_refresh.log 2>&1

# daily encrypted off-box backup -> B2
30 3 * * * /root/ops/heartbeat-wrap backup -- /root/backup/run_backup.sh

# Mnemosyne v1.1 resolver (daily)
30 4 * * * /root/ops/heartbeat-wrap mnemosyne_resolve -- /root/agent/olympus/scripts/run_mnemosyne_resolve.sh

# === Phaethon CONTROL arm C (mechanical equal-weight; NO LLM) — staggered, OUTSIDE 22:00-23:45 UTC ===
0 21 * * 1 /root/ops/heartbeat-wrap phaethon_c_rebalance -- /home/phaethon/phaethon/trader_c/run_phaethon_c.sh rebalance
15 21 * * 1-5 /root/ops/heartbeat-wrap phaethon_c_mark -- /home/phaethon/phaethon/trader_c/run_phaethon_c.sh mark

# === Cohort-1 weekly screen (locked-ruleset ATS pipeline) — Sunday 09:00 UTC ===
0 9 * * 0 /root/ops/heartbeat-wrap ats_screen -- /root/agent/run_ats_screen.sh

# === B-07 dead-man's switch / heartbeat evaluator — daily 06:00 UTC ===
# Reads all heartbeats vs expected_jobs.yaml, writes ALERT_*.flag on miss/stale/rc!=0,
# renders /root/ops/jobs_health.{txt,json}, and pings HEARTBEAT_DMS_URL only when ALL green.
0 6 * * * /root/ops/heartbeat-wrap heartbeat_check -- /usr/bin/python3 /root/ops/heartbeat.py check >> /root/ops/logs/heartbeat_check.log 2>&1
```

### Diff against the current crontab (semantic)

| # | Current | New |
|---|---|---|
| — | *(no env lines)* | **+ `SHELL`, `PATH`, `MAILTO=<OPERATOR_EMAIL>`, `HEARTBEAT_CONFIG`, `HEARTBEAT_DMS_URL_FILE`** |
| 1 | `0 22 * * 1-5 /root/epe/scripts/price_updater.sh >> …` | `… /root/ops/heartbeat-wrap epe_price_updater -- /root/epe/scripts/price_updater.sh >> …` |
| 2 | `0 17 * * 1-5 /root/epe/scripts/kill_flags.sh >> …` | `… heartbeat-wrap epe_kill_flags -- …` |
| 3 | `0 7 * * 1 /root/epe/scripts/weekly_status.sh >> …` | `… heartbeat-wrap epe_weekly_status -- …` |
| 4 | `5 7 * * * /root/epe/scripts/morning_check.sh >> …` | `… heartbeat-wrap epe_morning_check -- …` |
| 5 | `0 8 * * 0 cd /root/epe && venv/bin/python scripts/universe_check.py >> logs/universe_check.log 2>&1` | `0 8 * * 0 /root/ops/heartbeat-wrap epe_universe_check -- /bin/sh -c 'cd /root/epe && exec venv/bin/python scripts/universe_check.py' >> /root/epe/logs/universe_check.log 2>&1` **(log path spelled out — a no-op: the original `>> logs/…` already attached to the python step, which runs only after `cd /root/epe`, so it already resolved there)** |
| 6 | `30 21 * * 1-5 …/run_droplet_daily.sh` | `… heartbeat-wrap hermes_v3_daily -- …` |
| 7 | `45 21 * * 1-5 …/run_olympus_loop.sh` | `… heartbeat-wrap olympus_loop -- …` |
| 8–9 | `…/trader/run_phaethon.sh propose` / `mark` | `… heartbeat-wrap phaethon_a_propose -- …` / `phaethon_a_mark` |
| 10 | `45 22 * * * bash …/publish.sh` | `… heartbeat-wrap phaethon_panel_publish -- bash …/publish.sh` |
| 11–12 | `…/trader_b/run_phaethon_b.sh propose` / `mark` | `phaethon_b_propose` / `phaethon_b_mark` |
| 13 | `50 23 * * 1 …/run_oracle_mark.sh` | `… heartbeat-wrap oracle_mark -- …` |
| 14–15 | `…/shadow_ledger/run_shadow.sh …/trader{,_b}/state` | `phaethon_shadow_a` / `phaethon_shadow_b` |
| 16 | `30 3 * * * /root/backup/run_backup.sh   # comment` | `30 3 * * * /root/ops/heartbeat-wrap backup -- /root/backup/run_backup.sh` **(trailing inline comment moved to its own line)** |
| 17 | `30 4 * * * …/run_mnemosyne_resolve.sh   # comment` | `… heartbeat-wrap mnemosyne_resolve -- …` **(inline comment moved)** |
| 18–19 | `…/trader_c/run_phaethon_c.sh rebalance` / `mark` | `phaethon_c_rebalance` / `phaethon_c_mark` |
| 20 | `0 9 * * 0 /root/agent/run_ats_screen.sh` | `… heartbeat-wrap ats_screen -- …` |
| — | *(none)* | **+ `0 6 * * * … heartbeat.py check` (the evaluator + DMS ping)** |

Schedules, days-of-week, redirects (except #5's absolutisation) and the parked
comment blocks are **unchanged**.

---

## 5. Do the Phaethon `run_*.sh` wrappers also need an internal heartbeat call?

**No — and B-07 modifies zero `run_*.sh` files.**

* Each of `run_phaethon.sh`, `run_phaethon_b.sh`, `run_phaethon_c.sh`,
  `run_shadow.sh`, and `publish.sh` is invoked *directly* by a crontab line that
  B-07 now wraps. `heartbeat-wrap` captures the wrapper's real exit code.
* `propose` vs `mark` vs `rebalance` are already **separate crontab lines**, so
  they get **separate slugs** (`phaethon_a_propose`, `phaethon_a_mark`,
  `phaethon_b_propose`, `phaethon_b_mark`, `phaethon_c_rebalance`,
  `phaethon_c_mark`) and separate `<slug>.json` files automatically. No internal
  call is needed to distinguish them.
* `run_phaethon.sh` / `_b` / `_c` each end with `exit $RC` where `$RC` is the
  `docker run` exit code — verified by reading the scripts. `heartbeat-wrap`
  records it faithfully.

**Caveat (real gap, out of scope for this round):** `run_shadow.sh` and
`run_mnemosyne_resolve.sh` do **not** `exit $RC` — they end on a logging `echo`,
so they exit 0 even when the inner Python fails. Heartbeat rc for
`phaethon_shadow_a`, `phaethon_shadow_b` and `mnemosyne_resolve` will therefore
read 0 on an *internal* failure. Missed-run / box-down detection still works for
them. A one-line `exit "$rc"` / `exit "$RC"` fix to those two scripts is
recommended in a later, script-touching workstream.

---

## 6. One-time deploy (operator, after review)

`<repo>` below = the checked-out `b-11-hygiene`/`main` ATS tree on the box (or `scp` the four files up).
All schedule maths in `heartbeat.py` interprets cron in **UTC** — step 0 verifies the box is UTC.

```sh
# ---- 0. preconditions ----
timedatectl | grep -i 'time zone'          # MUST be UTC (Etc/UTC). If not, STOP — schedule maths assumes UTC.
ls /usr/local/bin /usr/local/sbin 2>/dev/null || true
#   The new crontab prepends /usr/local/{s,}bin to PATH. If a python3/git/docker/restic
#   lives there it would shadow /usr/bin/*. If the listing is empty/harmless, proceed;
#   otherwise pin absolute paths in the job lines or drop the PATH line.
crontab -l > ~/crontab.pre-b07.bak         # rollback anchor

# ---- 1. lay down /root/ops (all root-owned) ----
mkdir -p /root/ops /root/ops/heartbeat /root/ops/alerts /root/ops/logs /root/.secrets
install -m 0755 <repo>/scripts/heartbeat.py      /root/ops/heartbeat.py
install -m 0755 <repo>/scripts/heartbeat-wrap.sh /root/ops/heartbeat-wrap
install -m 0644 <repo>/config/expected_jobs.yaml /root/ops/expected_jobs.yaml
chown -R root:root /root/ops
chmod 0755 /root/ops /root/ops/heartbeat /root/ops/alerts /root/ops/logs
#   heartbeat.py reads HEARTBEAT_CONFIG, defaulting to /root/ops/expected_jobs.yaml —
#   the manual invocations below need no --config.

# ---- 2. dead-man's-switch secret (operator supplies the real URL) ----
#   healthchecks.io / Better Stack / cron-job.org / UptimeRobot "heartbeat" URL.
#   Hit ONLY when every job is green; an outage => no hit => external alarm.
umask 077
printf 'HEARTBEAT_DMS_URL=%s\n' 'https://REPLACE-ME/ping/xxxxxxxx' > /root/.secrets/heartbeat.env
chmod 600 /root/.secrets/heartbeat.env

# ---- 3. smoke-test BEFORE touching cron ----
/root/ops/heartbeat-wrap selftest -- /bin/true ; echo "wrap rc=$?"        # expect rc=0
cat /root/ops/heartbeat/selftest.json                                     # expect a valid record
rm -f /root/ops/heartbeat/selftest.json /root/ops/alerts/ALERT_selftest_heartbeat.flag

# ---- 4. SEED so day-1 is green (avoids a week of false DMS alarms) ----
#   7 jobs are Monday-only + 2 Sunday-only, so a live board cannot go green for up to
#   a week. `seed` writes one synthetic rc-0 heartbeat per job dated to its LAST
#   expected fire ("seeded": true). Real heartbeats replace the seeds as jobs fire;
#   a job that genuinely never runs ages past its grace and flags on the next check.
/usr/bin/python3 /root/ops/heartbeat.py seed
/usr/bin/python3 /root/ops/heartbeat.py check        # expect: table all OK, 0 alerts, DMS pinged (if URL set)

# ---- 5. (optional) make MAILTO deliver ----
#   No MTA installed; MAILTO is inert until one exists:
#   apt-get install -y msmtp-mta  &&  configure /etc/msmtprc with a smarthost.
#   Not depended on — flags + DMS are the primary alarm.

# ---- 6. apply the new crontab ----
#   Edit ~/crontab.b07.new: set MAILTO=<OPERATOR_EMAIL>.
crontab ~/crontab.b07.new
crontab -l | diff -u ~/crontab.pre-b07.bak -         # eyeball the diff

# ---- 7. re-check after ~24h, then tune grace_minutes from observed run times ----
cat /root/ops/jobs_health.txt
ls -l /root/ops/alerts/
```

---

## 7. Dead-man's switch — what the operator must create

| Item | Value |
|---|---|
| Secret file | `/root/.secrets/heartbeat.env` (mode 0600, `root:root`) |
| Contents | `HEARTBEAT_DMS_URL=https://<your-heartbeat-endpoint>` (or a bare URL line) |
| Referenced by | `HEARTBEAT_DMS_URL_FILE=/root/.secrets/heartbeat.env` (global env line in the new crontab) |
| Semantics | `heartbeat.py check` GETs the URL **only when zero jobs are unhealthy**. If any job is MISSING/STALE/FAILED, or if `check` itself doesn't run (box down, cron dead), the URL is **not** hit and the external monitor fires after its own grace period. |
| If unset | `check` prints `HEARTBEAT_DMS_URL unset … skipping` and exits 0 — no crash, no ping. |

`heartbeat.py` never hardcodes or invents a URL.

---

## 8. Simulated silent-failure test (run on the droplet AFTER apply)

```sh
# Snapshot (if not already done)
crontab -l > ~/crontab.pre-b07.bak

# --- A. missed run (heartbeat disappears) ---
ls -l /root/ops/heartbeat/                                  # pick a job with a fresh file, e.g. olympus_loop
mv /root/ops/heartbeat/olympus_loop.json /tmp/olympus_loop.json.bak
/usr/bin/python3 /root/ops/heartbeat.py check
test -e /root/ops/alerts/ALERT_olympus_loop_heartbeat.flag && echo "PASS: flag raised"
cat /root/ops/alerts/ALERT_olympus_loop_heartbeat.flag       # -> "... MISSING: no heartbeat file ..."
tail -n 5 /root/ops/logs/heartbeat_check.log | grep -q "NOT pinging dead-man" && echo "PASS: all-clear ping withheld"

# --- B. failed run (rc != 0) ---
/usr/bin/python3 /root/ops/heartbeat.py write olympus_loop --rc 1
/usr/bin/python3 /root/ops/heartbeat.py check
grep -q "rc=1" /root/ops/alerts/ALERT_olympus_loop_heartbeat.flag && echo "PASS: rc!=0 flagged"

# --- C. recovery clears the flag ---
mv /tmp/olympus_loop.json.bak /root/ops/heartbeat/olympus_loop.json    # restore the good record
/usr/bin/python3 /root/ops/heartbeat.py check
test ! -e /root/ops/alerts/ALERT_olympus_loop_heartbeat.flag && echo "PASS: flag auto-cleared on recovery"

# --- D. DMS is hit on a fully-green board (only if HEARTBEAT_DMS_URL is set) ---
#   With every job healthy, the last line of the check log reads:
#   "heartbeat: dead-man's-switch ping ok (HTTP 200)"
```

Expected: A raises `ALERT_olympus_loop_heartbeat.flag` and withholds the ping; B
replaces it with an `rc=1` reason; C deletes it; D pings once.

---

## 9. Rollback (single command)

```sh
crontab ~/crontab.pre-b07.bak      # restores the exact pre-B-07 crontab
```

`/root/ops/` and `/root/.secrets/heartbeat.env` can be left in place — they are
inert once the wrapped crontab is gone. To remove entirely:
`rm -rf /root/ops /root/.secrets/heartbeat.env`.

No `run_*.sh` or repo file was changed, so there is nothing else to revert.

---

## 10. Contingency — only if the Phaethon lines ever move to a `phaethon` crontab

Today every line is root's, so this is **not** needed. If a future change runs the
Phaethon wrappers as `phaethon`:

```sh
groupadd -f opsheartbeat
usermod -aG opsheartbeat phaethon
chgrp -R opsheartbeat /root/ops/heartbeat /root/ops/alerts
chmod 2775 /root/ops/heartbeat /root/ops/alerts        # setgid: new files inherit the group
```

and add an `os.chmod(path, 0o664)` after the atomic write in `heartbeat.py`
(`_atomic_write_json` currently produces 0600 via `mkstemp`). Flagged here so the
future change is a known, bounded edit.

---

## 11. Things about the 21 jobs that complicate the plan

1. **It is 20 live jobs, not 21.** The live `crontab -l` has exactly 20 active
   (non-comment) command lines. The four `quarterly_rebalance` lines and one
   `weekly_full_refresh` line are `PARKED-2026-06-15` (commented). B-07 registers
   the 20 live jobs **plus `heartbeat_check` itself** = 21 entries in
   `expected_jobs.yaml`. If EPE un-parks the quarterly/weekly-refresh lines, add
   them to the registry then.
2. **Every line runs as `root`.** No `phaethon` crontab, nothing in
   `/etc/crontab` or `/etc/cron.d`. The "phaethon vs root split" from the backlog
   is not reflected in cron — it only exists as `docker run --user 1000` *inside*
   the Phaethon containers. One writer, one dir. (Contingency in §10.)
3. **No MTA on the box.** `sendmail`/`mail`/`mailx` absent; no
   postfix/exim/msmtp package. `MAILTO=` is added per the backlog but is **inert**
   until the operator installs an MTA (§6 step 4). The real alarm path is the
   `ALERT_*.flag` files + the external dead-man's switch — the plan does not
   depend on mail.
4. **`cd /root/epe && venv/bin/python …` (line 5).** Rewritten as
   `heartbeat-wrap epe_universe_check -- /bin/sh -c 'cd /root/epe && exec …'`.
   Consequences: the log redirect is absolutised to
   `/root/epe/logs/universe_check.log`, and `git_sha` for this job is empty
   (argv[0] is `/bin/sh`, and `/root/epe` is not a git repo anyway). Both fine.
5. **Two scripts mask their exit code.** `run_shadow.sh` and
   `run_mnemosyne_resolve.sh` end on a logging `echo` with no `exit $RC`, so they
   exit 0 even on an internal failure. `phaethon_shadow_a/b` and
   `mnemosyne_resolve` heartbeats will read rc 0 on internal errors; missed-run
   detection still works. One-line fix recommended later (§5 caveat).
6. **Jobs that legitimately don't run every day.** Sundays only:
   `epe_universe_check`, `ats_screen`. Mondays only: `epe_weekly_status`,
   `phaethon_a_propose`, `phaethon_b_propose`, `phaethon_c_rebalance`,
   `oracle_mark`, `phaethon_shadow_a`, `phaethon_shadow_b`. Weekdays only:
   `epe_price_updater`, `epe_kill_flags`, `hermes_v3_daily`, `olympus_loop`,
   `phaethon_a_mark`, `phaethon_b_mark`, `phaethon_c_mark`. `heartbeat.py check`
   evaluates each job's own cron expression (DOW/DOM aware, cron's dom-OR-dow
   rule) to find the last expected fire, so it will not false-alarm a Monday-only
   job on a Thursday. Covered by `tests/test_heartbeat_jobs.py`.
7. **`epe_morning_check` is "silent on non-rebalance days"** but still executes
   daily and exits 0 → a normal daily rc-0 heartbeat, no special handling.
8. **Scripts that already exit non-zero as a normal signal:** none found.
   `run_oracle_mark.sh` and `publish.sh` exit 1 only on a genuine failure/abort;
   `publish.sh` exits 0 on "no change". All others propagate their child's code.
9. **`backup` and `ats_screen` are long.** `grace_minutes` set to 240 and 180.
   The backup is `restic` of the whole box to Backblaze B2; `ats_screen` runs the
   full weekly pipeline + a rebase-guarded git push. Tune after a week of
   `/root/ops/jobs_health.txt` observations.
10. **`git_sha` is best-effort and empty for four trees.** Only
    `/root/trading/hermes_v3_lab`, `/root/agent/olympus`,
    `/root/phaethon-panel-repo` and `/root/agent/ats-live` are git repos;
    `/root/epe`, `/root/labs/oracle`, `/root/backup`, `/home/phaethon/phaethon`
    are not → `git_sha: ""` for those jobs, by design (spec says best-effort).
11. **Pre-existing unrelated `heartbeat`.** `scripts/generate_dashboard.py` has
    `_heartbeat_state()` reading `docs/data/heartbeat.json` — a Hermes-v3
    dashboard-staleness badge, unrelated to B-07. Kept fully separate: different
    script, different files, `/root/ops/…`, and `tests/test_heartbeat_jobs.py`
    (not `test_heartbeat.py`). A future dashboard panel can read
    `/root/ops/jobs_health.json`.
12. **`run_ats_screen.sh` lives in `/root/agent` but `cd`s into
    `/root/agent/ats-live`** (same repo as this worktree). Registered with slug
    `ats_screen`, tree `/root/agent/ats-live`.
