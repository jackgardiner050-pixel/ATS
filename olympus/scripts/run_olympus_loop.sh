#!/usr/bin/env bash
# Olympus autonomous paper-execution loop — DROPLET runner (paper/simulated only).
#
# Self-fires the full pipeline (Oracle→…→Zeus→PaperBroker→record→feedback) + mandate trim, with
# NO human in each paper trade and NO broker reachable. Intended for a post-close weekday cron on
# the always-on droplet, e.g.:
#   45 21 * * 1-5 /root/.../olympus/scripts/run_olympus_loop.sh   (15 min after the Hermes v3 step)
#
# NOTE: full droplet deployment requires Olympus's deps (~/agent/src governance + ~/labs/oracle,
# awareness, experimental_pot_engine, ~/trading/hermes_v3_lab friction) to be present on the
# droplet, mirroring the Hermes v3 pattern. Until deployed, run locally. PAPER ONLY.
set -uo pipefail
OLY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$OLY/data/cron.log"
mkdir -p "$OLY/data"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Source the gitignored ANTHROPIC_API_KEY (cron has no interactive env). If absent, the loop
# FAILS LOUD (Oracle UNAVAILABLE) — it never falls back to a data-only fake. The key is never printed.
SECRETS="$HOME/labs/.secrets/anthropic.env"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi
{
  echo "[$TS] === Olympus paper loop start (PAPER/SIMULATED) ==="
  PY=python3; [ -x "$HOME/olympus_venv/bin/python" ] && PY="$HOME/olympus_venv/bin/python"  # venv has anthropic
  cd "$OLY" && "$PY" -m olympus.cli loop run
  echo "[$TS] === Olympus paper loop end (rc=$?) ==="
} >> "$LOG" 2>&1
