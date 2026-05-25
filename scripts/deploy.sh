#!/bin/bash
# Deploy the agent to the ats-research-simfin droplet.
#
# Prerequisites:
#   - SSH key authentication to the droplet
#   - DROPLET_HOST env var set (e.g. export DROPLET_HOST=user@ats-research.example.com)
#   - DROPLET_PATH env var set (e.g. export DROPLET_PATH=/opt/agent)
#
# Usage:
#   ./scripts/deploy.sh
#
# Hard constraint: this deploys ONLY to the research droplet. Never to ats-trading.

set -euo pipefail

if [[ -z "${DROPLET_HOST:-}" ]]; then
  echo "ERROR: set DROPLET_HOST env var (e.g. user@ats-research.example.com)"
  exit 1
fi

if [[ -z "${DROPLET_PATH:-}" ]]; then
  echo "ERROR: set DROPLET_PATH env var (e.g. /opt/agent)"
  exit 1
fi

if [[ "${DROPLET_HOST}" == *"trading"* ]]; then
  echo "ERROR: refusing to deploy to anything matching 'trading' — this is the research agent only"
  exit 1
fi

# Also verify the remote machine's actual hostname doesn't contain "trading".
REMOTE_HOSTNAME=$(ssh "${DROPLET_HOST}" "hostname" 2>/dev/null || true)
if [[ "${REMOTE_HOSTNAME}" == *"trading"* ]]; then
  echo "ERROR: remote hostname '${REMOTE_HOSTNAME}' contains 'trading' — refusing to deploy"
  exit 1
fi
echo "Remote hostname verified: ${REMOTE_HOSTNAME}"

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Deploying agent from ${AGENT_DIR} → ${DROPLET_HOST}:${DROPLET_PATH}"
echo "  Excluding: runs/, data/ live state files, __pycache__/, *.pyc"

rsync -avz --delete \
  --exclude 'runs/' \
  --exclude '.cache/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'data/paper_positions.yaml' \
  --exclude 'data/paper_trades.jsonl' \
  --exclude 'data/screen_state.yaml' \
  --exclude 'data/signal_log.jsonl' \
  "${AGENT_DIR}/" "${DROPLET_HOST}:${DROPLET_PATH}/"

echo
echo "Now on the droplet:"
echo "  ssh ${DROPLET_HOST}"
echo "  cd ${DROPLET_PATH}"
echo "  pip install -r requirements.txt"
echo "  export EDGAR_IDENTITY='Your Name your@email.com'"
echo "  python scripts/run_pipeline.py AGX"
echo
echo "Done."
