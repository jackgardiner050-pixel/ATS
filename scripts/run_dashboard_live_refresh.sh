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

# 1. Fetch prices and write JSON files
$PYTHON "$AGENT/scripts/fetch_live_prices.py"

# 2. Stage changed data files
cd "$AGENT"
git add docs/data/ats_live.json docs/data/scai_live.json \
        docs/data/hermes_live.json docs/data/system_summary_live.json 2>/dev/null || true

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
