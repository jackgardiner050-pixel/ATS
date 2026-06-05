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

# 2. Stage changed data files
cd "$AGENT"
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
    git push -q
    echo "[$TS] committed and pushed"
fi

echo "[$TS] live-refresh done"
