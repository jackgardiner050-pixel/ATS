# ATS Environment Snapshot

Recorded: 2026-05-26  
Purpose: Reproducibility baseline — deterministic installs depend on this snapshot.

---

## Runtime

| Component | Version |
|-----------|---------|
| Python | 3.14.5 |
| Platform | macOS-26.4.1-arm64 (Darwin 25.4.0) |
| ATS | 3.0.0 |
| Governance layer | 2.1.0 |
| Universe taxonomy | 1.1.0 (147 tickers, 25 archetypes) |

---

## Pinned dependencies

| Package | Version | Rationale |
|---------|---------|-----------|
| edgartools | 5.31.5 | **Hard-pinned.** Upstream has had silent behavioral changes between minor releases (EDGAR XML schema, filing parser internals). Do not loosen without running full test suite. |
| anthropic | 0.104.1 | LLM calls (Haiku adversarial review). |
| matplotlib | 3.10.9 | Dashboard chart rendering. |
| numpy | 2.4.6 | Numerical core. |
| pandas | 3.0.3 | Data manipulation. |
| requests | 2.34.2 | HTTP fetches (yfinance, EDGAR). |
| yfinance | 1.4.0 | Live market prices for paper position marks. |
| openpyxl | 3.1.5 | Excel output (EDGAR filing extraction). |
| python-dateutil | 2.9.0.post0 | Date parsing. |
| PyYAML | 6.0.3 | Config file loading. |

To reinstall deterministically:

```bash
pip install edgartools==5.31.5 anthropic==0.104.1 matplotlib==3.10.9 \
  numpy==2.4.6 pandas==3.0.3 requests==2.34.2 yfinance==1.4.0 \
  openpyxl==3.1.5 python-dateutil==2.9.0.post0 PyYAML==6.0.3
```

---

## Environment variables expected

| Variable | Purpose | Required |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Claude Haiku adversarial review (`--adversarial` flag) | Optional — only for `--adversarial` runs |

No keys are hardcoded anywhere. All sensitive values are loaded via `os.environ.get()`. The pipeline runs in observation-only mode without `ANTHROPIC_API_KEY` set.

---

## Cron / scheduling assumptions

The weekly pipeline (`scripts/run_weekly.sh`) assumes:
- Called from repo root on macOS (launchd) or Linux (cron).
- Git remote is reachable for the final `git push` step.
- No broker integration — paper trading only, HUMAN approval required for live trades.

Weekly pipeline steps (in order):
1. `run_universe.py` — screen all 147 universe tickers via DCF + signals
2. `paper_run.py` — update paper positions (NO autonomous execution)
3. `write_status.py` — write status JSON to docs/
4. `run_governance.py` — Phase II + III anti-delusion dashboard
5. `generate_dashboard.py` — regenerate HTML dashboard
6. `git commit && git push` — publish to GitHub Pages

---

## Operational log persistence policy

The following files are **local operational records only** — they are intentionally excluded from git (see `.gitignore`) to avoid repository bloat:

| Path | Purpose | Git-tracked? |
|------|---------|-------------|
| `data/governance_journal/governance_*.json` | Per-run governance snapshot for longitudinal debugging | No |
| `data/attribution_log.jsonl` | Append-only screening decision log for future calibration validation | No |
| `data/last_digest_state.json` | Telegram digest state (rating change detection) | No |
| `data/governance/*.jsonl` | Per-component governance time-series logs | No |

These files accumulate locally on the machine running the weekly pipeline. They are not replicated to git. If the machine fails, the local records are lost. The paper positions and signal log (`data/paper_positions.yaml`, `data/signal_log.jsonl`, `data/screen_state.yaml`) **are** committed weekly and serve as the durable audit trail for the November 25 decision checkpoint.

If you need to back up operational logs, copy `data/` to a separate location manually before any destructive operations.

---

## Decision checkpoint

**Paper test start:** 2026-05-26  
**Decision checkpoint:** 2026-11-25 (6 months)  
**Decision criteria:** Survivability > Explainability > Governance > Calibration > Alpha  
**Autonomous execution:** NEVER — HUMAN approval required for all live trades
