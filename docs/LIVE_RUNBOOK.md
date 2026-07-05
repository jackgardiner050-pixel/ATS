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
