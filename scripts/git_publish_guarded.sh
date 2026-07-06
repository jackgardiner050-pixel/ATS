#!/usr/bin/env bash
# Rebase-guarded publish for the weekly pipeline.
#
# The commit is already made by the caller. This fetches the remote branch and rebases our
# commit ON TOP of whatever a concurrent publisher (e.g. the Phaethon panel cron) already
# pushed that day, then pushes. It NEVER force-pushes and NEVER drops data:
#   - clean rebase  -> push; on push failure, alert + exit 1 (data safe in the local backup)
#   - rebase CONFLICT -> abort the rebase, alert LOUD, exit 1 (manual merge required)
# The optional local 'backup' remote is pushed first as an additive safety net.
#
# Overridable via env (used by tests): PUBLISH_REMOTE, PUBLISH_BRANCH, PUBLISH_BACKUP_REMOTE,
# ALERT_CMD (a command receiving the alert text; default = Telegram send_message).
set -uo pipefail

REMOTE="${PUBLISH_REMOTE:-origin}"
BRANCH="${PUBLISH_BRANCH:-main}"
BACKUP_REMOTE="${PUBLISH_BACKUP_REMOTE:-backup}"

_alert() {
  echo "ALERT: $1" >&2
  if [ -n "${ALERT_CMD:-}" ]; then
    "${ALERT_CMD}" "$1" || true
  else
    python3 -c "import sys; sys.path.insert(0, '.'); from src.telegram.client import send_message; send_message('🚨 ATS weekly publish: ' + sys.argv[1])" "$1" 2>/dev/null || true
  fi
}

# 1. Local backup — additive safety net; never blocks the public push.
if git remote get-url "${BACKUP_REMOTE}" >/dev/null 2>&1; then
  if git push "${BACKUP_REMOTE}" "HEAD:${BRANCH}"; then
    echo "backup: pushed to '${BACKUP_REMOTE}'"
  else
    echo "backup: WARNING push to '${BACKUP_REMOTE}' failed — continuing" >&2
  fi
fi

# 2. Rebase-guarded public push.
if ! git fetch "${REMOTE}" "${BRANCH}"; then
  _alert "git fetch ${REMOTE} ${BRANCH} failed — cannot rebase safely; NOT pushing. Data is in the local backup."
  exit 1
fi

if git rebase "${REMOTE}/${BRANCH}"; then
  if git push "${REMOTE}" "${BRANCH}"; then
    echo "published to ${REMOTE}/${BRANCH} (rebased on latest)"
    exit 0
  fi
  _alert "git push to ${REMOTE}/${BRANCH} FAILED after a clean rebase. NOT force-pushed; data is safe in the local backup."
  exit 1
fi

# rebase failed → conflict with a concurrent publisher's overlapping change
git rebase --abort 2>/dev/null || true
_alert "git REBASE CONFLICT with ${REMOTE}/${BRANCH} — a concurrent publisher touched an overlapping file. Pipeline ABORTED, NOT force-pushed; data is safe in the local backup. Manual merge required."
exit 1
