#!/usr/bin/env bash
# Weekly ATS research pipeline — runs on the droplet every Sunday 09:00 UTC.
#
# Pipeline:
#   1. run_universe.py   — screen all tickers
#   2. paper_run.py      — update paper positions
#   3. write_status.py   — write STATUS.txt
#   4. run_governance.py — anti-delusion governance layer (no adversarial by default)
#   5. generate_dashboard.py — build static HTML dashboard
#   6. git commit + push — backup data/ + publish docs/ to GitHub Pages
#
# Pass --adversarial to enable Haiku critique (requires ANTHROPIC_API_KEY, ~$0.001).
#
# Usage (from repo root, inside venv):
#   bash scripts/run_weekly.sh
#   bash scripts/run_weekly.sh --adversarial

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ADVERSARIAL_FLAG=""

for arg in "$@"; do
  case "$arg" in
    --adversarial) ADVERSARIAL_FLAG="--adversarial" ;;
  esac
done

LOG_DATE=$(date +%Y%m%d)
LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOGFILE="${LOG_DIR}/weekly_${LOG_DATE}.log"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${LOGFILE}"; }

log "=== ATS Weekly Pipeline starting ==="
log "Repo: ${REPO_ROOT}"
log "Log: ${LOGFILE}"
cd "${REPO_ROOT}"

# ── 0. Universe liveness check (warn-only, never blocks) ──────────────────────
log "Step 0: check_universe_liveness.py"
python3 scripts/check_universe_liveness.py 2>&1 | tee -a "${LOGFILE}" || \
  log "WARNING: liveness check exited non-zero — continuing (warn-only)"

# ── 1. Universe screener ──────────────────────────────────────────────────────
log "Step 1: run_universe.py"
python3 scripts/run_universe.py 2>&1 | tee -a "${LOGFILE}"

# ── 2. Paper run ──────────────────────────────────────────────────────────────
log "Step 2: paper_run.py"
python3 scripts/paper_run.py 2>&1 | tee -a "${LOGFILE}"

# ── 3. Write STATUS.txt ───────────────────────────────────────────────────────
log "Step 3: write_status.py"
python3 scripts/write_status.py 2>&1 | tee -a "${LOGFILE}"

# ── 4. Governance pipeline ────────────────────────────────────────────────────
log "Step 4: run_governance.py ${ADVERSARIAL_FLAG:-}"
EXIT_CODE=0
python3 scripts/run_governance.py --no-correlations ${ADVERSARIAL_FLAG} 2>&1 | tee -a "${LOGFILE}" || EXIT_CODE=$?
if [ "${EXIT_CODE}" -eq 2 ]; then
  log "WARNING: Constitutional violations detected (exit 2) — proceeding with dashboard build"
elif [ "${EXIT_CODE}" -ne 0 ]; then
  log "ERROR: Governance pipeline failed with exit ${EXIT_CODE}"
  exit "${EXIT_CODE}"
fi

# ── 5. Generate dashboard ─────────────────────────────────────────────────────
log "Step 5: generate_dashboard.py"
python3 scripts/generate_dashboard.py 2>&1 | tee -a "${LOGFILE}"

# ── 6. Git commit + push ──────────────────────────────────────────────────────
log "Step 6: git commit + push"
cd "${REPO_ROOT}"

git add data/ STATUS.txt docs/ 2>&1 | tee -a "${LOGFILE}"

if git diff --cached --quiet; then
  log "Nothing to commit — all data up to date."
else
  COMMIT_MSG="Weekly run ${LOG_DATE}: screener + paper + governance + dashboard"
  git commit -m "${COMMIT_MSG}" 2>&1 | tee -a "${LOGFILE}"
  git push origin main 2>&1 | tee -a "${LOGFILE}"
  log "Pushed to origin/main"
fi

log "=== ATS Weekly Pipeline complete ==="
