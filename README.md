# Equity Research Agent

A **research analyst agent**, not a trading agent. Given a ticker, produces a Buy/Sell/Hold rating, price target, financial model, and valuation analysis. **Never places orders.** Human reviews every output.

## Hard constraints (architectural)

1. **No order placement.** Ever. No broker integration.
2. **No learning from live P&L.** Knowledge base grows; decision-making weights do not auto-tune from outcomes.
3. **Frozen validator gates outputs.** Standard 6-gate harness from prior research project.
4. **Corpus persistence.** Every analysis logged so dead ideas can't return.
5. **The LLM never invents numbers.** Three-layer recommendation engine: deterministic calculator → evidence-bound narrative → numeric validator.

## Install (local dev or droplet)

```bash
# Clone or rsync this folder
cd agent

# Python 3.11+
pip install -r requirements.txt

# SEC requires an identity for EDGAR access
export EDGAR_IDENTITY="Your Name your.email@example.com"

# Optional: Anthropic API key for LLM-generated narrative sections
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Usage

### Deep-dive on one ticker
```bash
python scripts/run_pipeline.py AGX
# Output: runs/AGX/YYYYMMDD_HHMMSS/
#   - model.xlsx          (financial model + valuation)
#   - recommendation.json (machine-readable rating + PT)
```

### Universe screen
```bash
python scripts/run_universe.py --universe config/universe.yaml
# Screens every ticker in universe.yaml (adaptive cadence — only names that
# are "due" are re-run; see src/cadence.py). Output:
#   runs/_screen/YYYYMMDD_HHMMSS/summary.json   (full screen result + stats)
#   data/screen_state.yaml                       (per-ticker cadence state)
#   data/signal_log.jsonl                        (append-only signal-escalation log)
#
# Useful flags:
#   --tickers ACM,EMR      screen an explicit list (overrides --universe)
#   --limit 10             first N tickers only
#   --force TICKER         force re-screen one name (may repeat)
#   --force-all            force re-screen the whole universe
#   --include-skipped      print rows for names not due this run
```

### Paper trading (simulated calibration — no broker)
```bash
python scripts/paper_run.py     # applies entry/exit gates to the latest screen
# Output: data/paper_positions.yaml, data/paper_trades.jsonl
```

### Weekly pipeline (droplet cron)
```bash
bash scripts/run_weekly.sh                 # screen → paper → status → governance → dashboard → push
bash scripts/run_weekly.sh --adversarial   # + Haiku critique (needs ANTHROPIC_API_KEY)
```

## Architecture

```
agent/
├── src/
│   ├── data/            # edgar_client (EDGAR/XBRL), peer_multiples, price feeds
│   ├── agents/          # model.py (financial model), valuation.py (DCF + comps)
│   ├── engine/          # calculator.py — deterministic FixedNumbers
│   ├── signals/         # momentum, revisions, confidence escalation
│   ├── governance/      # anti-delusion layer: constitution, calibration, regime,
│   │                    #   exposure, dcf_skeptic, adversarial, attribution, dashboard
│   ├── portfolio/       # exposure / factor / stress / survivability engines
│   ├── universe/        # classifier, governor, behavior + diversifier engines, audit
│   ├── telegram/        # send-only digest + alerts
│   ├── cadence.py       # adaptive re-screen scheduling (screen_state.yaml)
│   ├── paper_trading.py # simulated positions (no broker), entry/exit gates
│   ├── orchestrator.py  # single-ticker pipeline runner
│   └── version.py       # ATS / governance / universe version lineage
├── scripts/             # CLI entry points (run_pipeline, run_universe, paper_run, ...)
├── config/              # universe.yaml, peer_groups.yaml, settings.yaml, themes.yaml, ...
├── data/                # screen_state.yaml, paper_positions.yaml, *.jsonl logs
├── docs/                # static dashboard (GitHub Pages)
├── tests/               # pytest suite
└── runs/                # output artifacts — runs/{ticker}/{ts}/ and runs/_screen/{ts}/
```

> **Note:** there is no `src/screener.py` or `src/corpus.py` module. Screening lives in
> `scripts/run_universe.py` + `src/cadence.py` + `src/universe/`. Thesis/idea persistence is
> currently de-facto (per-run artifacts under `runs/` plus the append-only `data/*.jsonl` logs);
> a dedicated corpus module is **planned**, not built.

## Recommendation engine (VYNN AI pattern)

```
Layer 1: RecommendationCalculator (deterministic Python)
  → expected return, price targets, valuation gap
  → Output: FixedNumbers (immutable)

Layer 2: EvidenceExtractor → LLM Narrative
  → evidence pack (E1, E2, ...) with source scoring
  → LLM writes prose constrained to provided data

Layer 3: RecommendationValidator
  → regex-verifies every number in LLM output
  → ≥95% citation coverage required
  → auto-corrects deviations
```

Rating bands: STRONG BUY (>20%) / BUY (10-20%) / HOLD (-5% to +10%) / SELL (-20% to -5%) / STRONG SELL (<-20%)

## Deploy to ats-research-simfin droplet

```bash
# From local machine
./scripts/deploy.sh

# On droplet, schedule the weekly pipeline
crontab -e
# Add: 0 9 * * 0 cd /opt/agent && bash scripts/run_weekly.sh >> logs/weekly.log 2>&1
```

## Status

Implemented:
- [x] Folder structure
- [x] Data layer (edgar_client — EDGAR/XBRL wrapper, peer_multiples)
- [x] Financial model agent (`src/agents/model.py`)
- [x] Valuation agent — DCF + comps (`src/agents/valuation.py`)
- [x] Recommendation calculator (`src/engine/calculator.py`)
- [x] Pipeline orchestrator (`src/orchestrator.py`)
- [x] CLI entry points (`scripts/run_pipeline.py`, `scripts/run_universe.py`)
- [x] Screener — universe screen with adaptive cadence (`run_universe.py` + `src/cadence.py`)
- [x] Signals layer — momentum, revisions, confidence escalation (`src/signals/`)
- [x] Governance layer — constitution, calibration, regime, exposure, adversarial (`src/governance/`)
- [x] Paper-trading calibration (simulated, no broker — `src/paper_trading.py`)
- [x] Static dashboard (`docs/`, GitHub Pages)

Planned / not built:
- [ ] Research agent (qualitative narrative — Task 1 port)
- [ ] Charts agent (Task 4 port)
- [ ] Summary agent (one-page exec)
- [ ] Numeric validator (citation-coverage check)
- [ ] Dedicated corpus-persistence module (`src/corpus.py`)

The MVP runs end-to-end on financial data + DCF + comps + rating. Research/charts/summary/validator
stages are still templates in the parent `build_agx_*.py` scripts and are not yet ported.
</content>
</invoke>
