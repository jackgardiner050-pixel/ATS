# Equity Research Agent

A **research analyst agent**, not a trading agent. Given a ticker, produces a Buy/Sell/Hold rating, price target, financial model, valuation analysis, and one-page executive summary. **Never places orders.** Human reviews every output.

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
#   - research.md       (qualitative analysis)
#   - model.xlsx        (financial model + valuation)
#   - charts.zip        (PNG charts at 300 DPI)
#   - summary.md        (one-page exec)
#   - recommendation.json (machine-readable rating + PT)
```

### Universe screen
```bash
python scripts/run_screen.py --universe config/universe.yaml
# Output: runs/screen/YYYYMMDD/
#   - flags.csv         (tickers >25% deviation from peer median)
#   - briefing.md       (morning note with top 5 flagged names)
```

## Architecture

```
agent/
├── src/
│   ├── data/           # edgartools wrapper, price feeds
│   ├── agents/         # research, model, valuation, charts, summary
│   ├── engine/         # deterministic calculator, evidence, validator
│   ├── orchestrator.py # pipeline runner
│   ├── screener.py     # nightly universe screen
│   └── corpus.py       # thesis persistence
├── scripts/            # CLI entry points
├── config/             # universe.yaml, settings.yaml
└── runs/               # output artifacts (one folder per ticker per run)
```

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

# On droplet, schedule nightly screen
crontab -e
# Add: 0 2 * * * cd /opt/agent && python scripts/run_screen.py >> logs/screen.log 2>&1
```

## Status

- [x] Folder structure
- [x] Data layer (edgartools wrapper)
- [x] Financial model agent (port from build_agx_model.py)
- [x] Valuation agent (port from build_agx_valuation.py)
- [x] Recommendation calculator
- [x] Pipeline orchestrator
- [x] CLI entry point
- [ ] Research agent (qualitative — Task 1 port)
- [ ] Charts agent (Task 4 port)
- [ ] Summary agent (one-page exec)
- [ ] Validator (citation check)
- [ ] Screener (nightly universe)
- [ ] Corpus persistence

The MVP runs end-to-end on financial data + DCF + comps + rating. Research/charts/summary stages can be added incrementally — the existing `build_agx_*.py` scripts in the parent folder are the templates.
