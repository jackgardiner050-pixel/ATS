#!/bin/bash
# Near-live dashboard refresh — updates docs/data/*.json every 15 min during US market hours.
# Cron (Mac launchd handles scheduling; server cron below for reference):
#   */15 14-21 * * 1-5 /bin/bash ~/agent/scripts/run_dashboard_live_refresh.sh >> ~/agent/logs/live_dashboard.log 2>&1
#
# Hard rules: no trading, no broker, no position mutations, data/dashboard only.

AGENT="$HOME/agent"
LOG_DIR="$AGENT/logs"
mkdir -p "$LOG_DIR"

# Only run during extended US market hours: 13:30–21:30 UTC (9:30am–5:30pm ET)
HOUR_UTC=$(date -u +%H)
MIN_UTC=$(date -u +%M)
DOW=$(date -u +%u)  # 1=Mon, 7=Sun
TIME_INT=$((HOUR_UTC * 60 + MIN_UTC))

if [ "$DOW" -ge 6 ] || [ "$TIME_INT" -lt 810 ] || [ "$TIME_INT" -gt 1290 ]; then
    # Outside market hours — skip silently
    exit 0
fi

set -e

# Resolve Python
if [ -f "$AGENT/.venv/bin/python3" ]; then
    PYTHON="$AGENT/.venv/bin/python3"
elif [ -f "$HOME/trading/venv/bin/python3" ]; then
    PYTHON="$HOME/trading/venv/bin/python3"
else
    PYTHON="python3"
fi

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "[$TS] live-refresh start"

# 0. Pull Hermes v3's authoritative variant state from the always-on droplet.
#    Hermes v3 now COMPUTES on the droplet (daily 21:30 UTC cron); the Mac is a read-replica
#    for publishing — the same compute-on-droplet / publish-from-Mac pattern as EPE. Non-fatal:
#    a droplet/SSH hiccup must never break the dashboard refresh; we just publish the last pull.
HV3_LOCAL="$HOME/trading/hermes_v3_lab/data/variants/"
if rsync -az --timeout=20 -e "ssh -i $HOME/.ssh/id_ed25519 -o ConnectTimeout=15 -o BatchMode=yes -p 8022" \
        root@161.35.166.77:/root/trading/hermes_v3_lab/data/variants/ "$HV3_LOCAL" 2>/dev/null; then
    echo "[$TS] pulled Hermes v3 variant state from droplet"
else
    echo "[$TS] WARN: droplet pull failed — publishing last-known Hermes v3 state"
fi

# 0b. Pull the Olympus v2 growth-arm paper ledgers (A/B/C) from the droplet where the loop runs.
#     Non-fatal — a hiccup just re-marks the last-known ledgers.
mkdir -p "$AGENT/olympus/olympus/data"
rsync -az --timeout=20 -e "ssh -i $HOME/.ssh/id_ed25519 -o ConnectTimeout=15 -o BatchMode=yes -p 8022" \
    root@161.35.166.77:/root/agent/olympus/data/arm_A_portfolio.json \
    root@161.35.166.77:/root/agent/olympus/data/arm_B_portfolio.json \
    root@161.35.166.77:/root/agent/olympus/data/arm_C_portfolio.json \
    "$AGENT/olympus/olympus/data/" 2>/dev/null \
    && echo "[$TS] pulled growth-arm ledgers" || echo "[$TS] WARN: arm-ledger pull failed — re-marking last-known"

# 1. Fetch prices and write JSON files
$PYTHON "$AGENT/scripts/fetch_live_prices.py"

# 1b. Regenerate the sanitized Olympus track card (Iris + Nike) from the
#     immutable point-in-time ledgers. Display/read-only — no trading.
( cd "$HOME/labs" && "$PYTHON" -m experimental_pot_engine.track.publish_card ) || true

# 1c. Re-mark the growth arms (A/B/C) vs QQQ + SPY from their paper ledgers → growth_arms_live.json.
$PYTHON "$AGENT/scripts/publish_growth_arms.py" || true

# 1d. Gaia — mark the 3 diversified cores vs the all-world benchmark (public). The current-allocation
#     comparison arm is written only to the gitignored gaia/data/gaia_private.json, never published.
$PYTHON "$AGENT/scripts/publish_gaia.py" || true

# 1e. Phaethon panel — NO LONGER published from the Mac. The always-on ats-research droplet now builds
#     and pushes docs/data/phaethon_live.json itself (daily root cron /root/phaethon-panel-publish.sh),
#     so the panel refreshes independently of the Mac. The Mac must NOT touch phaethon_live.json (avoid
#     fighting the droplet over the same file).

# 2. Stage changed data files (phaethon_live.json deliberately excluded — owned by the droplet)
cd "$AGENT"

# Clear a stale git index.lock left by a crashed run — ONLY when no git process is active (safe).
if [ -f "$AGENT/.git/index.lock" ] && ! pgrep -x git >/dev/null 2>&1; then
    echo "[$TS] clearing stale .git/index.lock (no git process running)"
    rm -f "$AGENT/.git/index.lock"
fi

git add docs/data/ats_live.json docs/data/scai_live.json \
        docs/data/hermes_live.json docs/data/hermes_v3_live.json \
        docs/data/system_summary_live.json docs/data/growth_arms_live.json \
        docs/data/gaia_cores_live.json \
        docs/olympus_track.html 2>/dev/null || true

# 3. Commit only if something changed
if git diff --cached --quiet; then
    echo "[$TS] no data change — skipping commit"
else
    COMMIT_TS=$(date -u +%Y-%m-%d\ %H:%M\ UTC)
    git commit -m "live dashboard refresh — $COMMIT_TS" \
               --author="ATS Live Refresh <noreply@ats>" \
               -q
    # The droplet's Phaethon panel publisher pushes to this same branch (daily 22:45 UTC), so integrate
    # its commits BEFORE pushing or our push is rejected non-fast-forward (the 06-09 stall). Our files are
    # disjoint from the droplet's (we never touch phaethon_live.json), so this rebase is conflict-free;
    # --autostash protects any untracked-ledger churn, and we abort+log if a conflict ever appears.
    if git pull --rebase --autostash -q origin main; then
        if git push -q; then
            echo "[$TS] committed, rebased on origin/main, and pushed"
        else
            echo "[$TS] WARN: push failed after rebase (network/remote?) — commit stays local, retry next run"
        fi
    else
        echo "[$TS] WARN: could not rebase on origin/main — aborting, commit stays local for next run"
        git rebase --abort 2>/dev/null || true
    fi
fi

echo "[$TS] live-refresh done"
