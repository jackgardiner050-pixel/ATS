#!/bin/bash
# Phaethon dashboard panel publisher — THIN CRON WRAPPER.
#
# The render + governance + cohort tagging now live in the repo
# (src/phaethon/publish.py). This wrapper only does the git dance. The STRATEGY
# (trader state under /home/phaethon/…) is frozen and untouched. See
# docs/LIVE_RUNBOOK.md for the cron change and the push-key requirement.
#
# fetch = origin (may be HTTPS, read-only); push = explicit SSH URL with the write
# key, so the two are decoupled (origin was switched to HTTPS for read-only pulls).
set -uo pipefail
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ); LOG=/root/phaethon-panel.log
REPO=/root/phaethon-panel-repo
PUSH_URL="git@github.com:jackgardiner050-pixel/ATS.git"
export GIT_SSH_COMMAND="ssh -i /root/.ssh/phaethon_panel_push_key -o StrictHostKeyChecking=accept-new"

cd "$REPO" || { echo "[$TS] no repo" >> "$LOG"; exit 1; }
for a in 1 2; do
  git fetch --depth 1 origin main -q 2>>"$LOG" || true
  git reset --hard origin/main -q 2>>"$LOG"
  # Repo-owned render + governance: writes docs/data/phaethon_live.json + _b_live.json,
  # surfaces NONCONFORMING as a status banner, enforces the sanitize gate, and fires a
  # Telegram alert on any violation. Non-zero exit = sanitize/gate abort → do NOT publish.
  if ! python3 -m src.phaethon.publish >> "$LOG" 2>&1; then
    echo "[$TS] publish aborted (sanitize gate or error) — NOT publishing" >> "$LOG"; exit 1; fi
  git add docs/data/phaethon_live.json docs/data/phaethon_b_live.json 2>>"$LOG"
  git diff --cached --quiet && { echo "[$TS] no change" >> "$LOG"; exit 0; }
  git commit -q -m "phaethon panel refresh — both arms — $TS" 2>>"$LOG"
  git push -q "$PUSH_URL" HEAD:main 2>>"$LOG" && { echo "[$TS] published BOTH arms" >> "$LOG"; exit 0; }
  echo "[$TS] push race retry $a" >> "$LOG"
done
echo "[$TS] FAILED" >> "$LOG"; exit 1
