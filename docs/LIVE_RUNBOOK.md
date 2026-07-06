# Live Runbook

Operational notes for the always-on droplet(s). Paper/research only — no broker.

## Phaethon panel publisher — cron migration (2026-07-05)

The Phaethon dashboard publisher moved **from off-repo → under governance in the repo**.

- **Old (retire):** root cron ran `/root/phaethon-panel-publish.sh` (off-repo; render +
  git push inline). Committed verbatim for audit at
  `scripts/phaethon/publish_original_reference.sh` — **not run**.
- **New:** render + governance + cohort tagging live in `src/phaethon/` (`publish.py`);
  the thin cron wrapper is `scripts/phaethon/publish.sh` (git fetch/reset → `python3 -m
  src.phaethon.publish` → add/commit/push).

### Cron change on the droplet
Replace the crontab entry that called the old script with the repo wrapper (it
self-updates via `git reset --hard origin/main` before rendering):

```cron
# was: 45 22 * * *  /root/phaethon-panel-publish.sh
45 22 * * *  /root/phaethon-panel-repo/scripts/phaethon/publish.sh
```

### Requirements / gotchas
- **Push credential:** the wrapper pushes with the existing write key
  `/root/.ssh/phaethon_panel_push_key` to the explicit SSH URL
  `git@github.com:jackgardiner050-pixel/ATS.git`. This is **decoupled from `origin`**,
  which was switched to **HTTPS** (read-only) for the pt-calibration pull — so `git fetch`
  (origin, HTTPS) and `git push` (explicit SSH URL, write key) both work.
- **Governance:** every publish runs leverage / micro-cap / MAX_SINGLE_POSITION checks;
  a violation writes `"status": "NONCONFORMING — …"` into the arm JSON (red banner) and
  fires a Telegram alert. It does **not** clamp or fix — Arm B currently flags (138%
  gross); that is expected (its cash accounting is the separate item-10 bug).
- **Sanitize gate:** publish aborts (non-zero exit, no push) if any personal/account
  term appears in the rendered JSON.
- **Trader state (frozen):** the strategy still writes `scorecard_public.json` / `book.json`
  under `/home/phaethon/phaethon/trader{,_b}/state`; the render reads those. Unchanged.

## Hermes E1 (advisory-live) — pre-go-live drill: run and check all boxes

Before `MAX_LIVE_CAPITAL_GBP` is set above 0, the operator MUST run the drill and hand-verify
every observable outcome. This proves the halt/kill/reconcile machinery works before any real
order card is issued.

```
python3 scripts/live_drill.py        # dry-run, throwaway sandbox — touches no real state
```

The drill exercises three failure paths; check each box against what you actually observe:

- **(a) Kill mid-pending-cards** — card generation refuses (`kill_block`), all PENDING cards
  → KILLED, alert sent; resume needs **/confirm_resume with a reason AND manual KILL-file
  deletion** (two steps). A cumulative-breach kill is **terminal** — resume is impossible
  until a completed post-mortem exists at `POST_MORTEM_PATH` in `config/live_limits.yaml`.
- **(b) Daily loss breach** — `data/live/HALT_DAILY` (date-stamped) written, generation
  blocked for the day; **auto-clears next session**. Weekly breach → `HALT_WEEKLY`
  (two-step reset like the kill).
- **(c) Reconcile mismatch** — `data/live/RECONCILE_BLOCK` written, alert sent, generation
  refuses until the mismatch is resolved and the sentinel cleared (with a reason).

**Fail-safe:** the breaker thresholds in `live_limits.yaml` are `null` until deliberately
set by re-registration. While any of `DAILY_LOSS_HALT_PCT`/`WEEKLY_LOSS_HALT_PCT`/
`CUMULATIVE_KILL_PCT` is null, breaker evaluation **blocks card generation** rather than
silently skipping the check. Do not fund the pilot until the drill passes AND the thresholds
are set.
