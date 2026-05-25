# System Audit — ATS Agent + Swing Bot v1
**Date:** 2026-05-25  
**Auditor:** Claude Code (read-only audit — no code changes made)  
**Scope:** Long-term agent (`agent/`) and Swing Bot v1 (`agent/swing-bot/`)

---

## 1. Hard Rules Compliance

### 1.1 Agent never places real orders

| System | Function | Location | Enforcement |
|--------|----------|----------|-------------|
| Long-term agent | No order function exists | `src/paper_trading.py` | Module docstring: `no_real_orders: True — this module NEVER interacts with a broker`. No broker import anywhere in `src/`. |
| Long-term agent | `process_screener_results()` | `src/paper_trading.py` | Opens/closes paper records in YAML only. No API calls. |
| Swing bot | `place_real_order()` | `src/paper_executor.py:35` | **Exists and raises:** `RuntimeError("Order placement permanently disabled.")` ✓ |
| Swing bot | All position functions | `src/paper_executor.py` | `_CONSTRAINTS = {"no_real_orders": True, ...}` tagged on every record ✓ |

Grep for broker API libraries (`trading212`, `alpaca`, `ibkr`, `schwab`) across both codebases: **zero matches**. ✓

### 1.2 Human gates every action (long-term agent)

The orchestrator's opening comment: *"Hard constraint: this orchestrator NEVER places orders. It produces a recommendation and writes it to disk. The human gate (you) acts on it."* (`src/orchestrator.py:4`). The pipeline produces `runs/_screen/{ts}/summary.json`; no automated execution path exists from that output. ✓

### 1.3 Swing bot autonomous within paper sandbox only

No broker API code anywhere in `swing-bot/`. The only autonomous action the bot takes is writing to `data/swing_paper_positions.yaml` and `data/swing_paper_trades.jsonl`. Currently running with `alert_mode_only: true`, so even those writes are disabled. ✓

### 1.4 No learning from realised P&L (long-term agent)

`src/paper_trading.py` is tagged `no_live_pnl_learning: True`. Signal log entries (`data/signal_log.jsonl`) record ratings/confidence/momentum — they are never read back into the screener or model. Closed trade records are JSONL-appended only; `scripts/paper_run.py` reads them to compute stats for display but does not feed anything back to `src/engine/calculator.py` or any model. ✓

### 1.5 LLM never invents numbers

`src/engine/calculator.py` has zero LLM calls. Its comment: *"This file contains ZERO LLM calls. All math is deterministic and reproducible."* It produces a `FixedNumbers` frozen dataclass; downstream layers (model, valuation) can only narrate around those numbers.

`swing-bot/src/classifier.py` emits exactly: `{"category": str, "material": bool, "confidence": float}` — a structured JSON schema, never numbers that feed into trade sizing or thresholds. Phase A (`llm.enabled: false`) means this is not called at all currently. ✓

### 1.6 No deploy code targets `ats-trading` droplet

`scripts/deploy.sh` contains two independent guards:
- Line 26: `if [[ "${DROPLET_HOST}" == *"trading"* ]]` — rejects by env var
- Line 33: `if [[ "${REMOTE_HOSTNAME}" == *"trading"* ]]` — SSH into remote and checks actual hostname

Both exit with error. ✓

### 1.7 Swing bot ringfenced — zero cross-imports

Grep for `from agent` / `import agent` / `from ..` in `swing-bot/src/` and `swing-bot/scripts/`: **zero matches**. Swing bot uses only its own `sys.path.insert(0, str(_ROOT))` to reference its own `src/`.

Grep for `swing.bot` / `swing_bot` / `swing-bot` in `agent/src/` and `agent/scripts/`: **zero matches**. Neither codebase imports the other. ✓

### 1.8 Kill switches armed

| System | Trigger | Action | Status |
|--------|---------|--------|--------|
| Long-term agent | None | N/A — human reviews weekly output | Not applicable (human is the gate) |
| Swing bot soft alert | Cumulative P&L ≤ −10% | Telegram warning, bot continues | Armed — `_SOFT_ALERT_PCT = -10.0` in `kill_switch.py` |
| Swing bot hard kill | Cumulative P&L ≤ −20% | `disabled: True` in state, requires manual re-enable | Armed — `_HARD_KILL_PCT = -20.0` in `kill_switch.py` |
| Swing bot time box | Date ≥ `disable_date` | Hard kill same as above | Armed — `disable_date: 2026-11-25` |

Kill switch state as of audit: `disabled: false`, `cumulative_pnl_gbp: 0.0`, `soft_alert_sent: false`. ✓

### 1.9 6-month auto-disable timer set

`swing-bot/config/settings.yaml`: `disable_date: "2026-11-25"`. Start date `2026-05-25` → exactly 6 months. ✓

---

## 2. Code Architecture Review

### 2.1 Long-term agent — `agent/src/`

| Module | Purpose |
|--------|---------|
| `engine/calculator.py` | Deterministic DCF + comps math. Produces `FixedNumbers` frozen dataclass. Zero LLM calls. |
| `agents/model.py` | Builds financial model from EDGAR data. Calls Claude for narrative only, never for numbers. |
| `agents/valuation.py` | Blends DCF and comps price targets, applies cohort outlier detection, sets confidence. |
| `data/edgar_client.py` | Fetches and parses SEC EDGAR XBRL filings for revenue, EBITDA, debt, shares. |
| `data/peer_multiples.py` | Resolves peer EV/EBITDA multiples from yfinance for comps valuation. |
| `signals/momentum.py` | Ranks tickers into quintiles by 12-month price return. Pure math. |
| `signals/revisions.py` | Detects FY+1 EPS revision direction (POSITIVE / FLAT / NEGATIVE). |
| `signals/escalation.py` | Bumps confidence up/down based on momentum + revision alignment. |
| `orchestrator.py` | Pipeline entry point: wires data → model → valuation → output. Never places orders. |
| `paper_trading.py` | Paper position lifecycle (open/close), YAML + JSONL I/O. No broker connection. |
| `cadence.py` | Determines when each ticker is due for re-screening (weekly cadence). |
| `telegram/client.py` | Sends messages to long-term agent Telegram channel. Read env for token. |
| `telegram/digest.py` | Formats the weekly Sunday digest message. |
| `telegram/alerts.py` | Detects rating changes between runs, formats change alerts. |

### 2.2 Swing Bot v1 — `agent/swing-bot/src/`

| Module | Purpose |
|--------|---------|
| `catalysts/edgar_8k.py` | Polls EDGAR EFTS for 8-K filings on watchlist tickers. Returns catalyst dicts. |
| `catalysts/earnings_monitor.py` | Detects EPS beats ≥5% + revenue beats via yfinance earnings history. |
| `catalysts/fda_calendar.py` | Scrapes FDA drug approvals RSS feed, matches tickers by regex. |
| `catalysts/volume_anomaly.py` | Flags tickers where today's volume > 3× 30-day average. |
| `rules/entry.py` | Evaluates all four entry conditions; builds entry signal with fixed sizing. |
| `rules/exit.py` | Evaluates profit target (+10%), stop loss (−5%), time exit (10 days), signal reversal. |
| `rules/filters.py` | Materiality filters per catalyst type. Phase A: rule-based. Phase B: Haiku confidence ≥0.6. |
| `classifier.py` | Haiku API call for 8-K classification. Phase A disabled. Hard cost cap at £5/month. |
| `paper_executor.py` | Paper position I/O. `place_real_order()` exists and always raises RuntimeError. |
| `kill_switch.py` | Two-tier drawdown: soft alert −10%, hard kill −20%. Persists state to YAML. |
| `finnhub_client.py` | Finnhub `/quote` wrapper with 1 req/sec rate limiting (57/min, free tier = 60). |
| `active_watchlist.py` | Manages Tier 0 list: tickers with recent catalysts (48h TTL) or open positions. |
| `telegram_client.py` | Swing bot Telegram client. Reads SWING_BOT_TOKEN from `swing-bot/.env`. |

### 2.3 Scripts

| Script | System | Purpose |
|--------|--------|---------|
| `scripts/run_universe.py` | Long-term | Screens all tickers, writes `runs/_screen/` output |
| `scripts/paper_run.py` | Long-term | Reads screener output, opens/closes paper positions |
| `scripts/send_digest.py` | Long-term | Sends weekly Telegram digest |
| `scripts/write_status.py` | Long-term | Writes `STATUS.txt` one-line summary |
| `scripts/paper_report.py` | Long-term | On-demand paper book report |
| `scripts/calibration_audit.py` | Long-term | Audits model calibration |
| `swing-bot/scripts/run_catalyst_poll.py` | Swing bot | Tier 0 + EDGAR poll, every 15 min market hours |
| `swing-bot/scripts/run_broad_scan.py` | Swing bot | Tier 1 yfinance full-watchlist scan, daily 22:00 UTC |
| `swing-bot/scripts/run_eod_mark.py` | Swing bot | EOD mark-to-market + kill switch check, daily 22:30 UTC |
| `swing-bot/scripts/swing_telegram_digest.py` | Swing bot | Weekly Sunday digest to swing channel |
| `swing-bot/scripts/swing_report.py` | Swing bot | On-demand report with Telegram flag |

### 2.4 Shared code candidates

There are two modules that serve similar purposes in both systems — `telegram/client.py` and `swing-bot/src/telegram_client.py`. Both send messages via the Telegram Bot API using `requests`. The implementations are structurally identical (chunk at 4096 chars, return bool, never raise).

**Should they share code?** No. Sharing would require one module to read from both `.env` files and route to different tokens — or a common module imported by both systems. Either approach creates a cross-import dependency that breaks ringfencing. The 50-line duplication is the correct trade-off.

---

## 3. Test Coverage Audit

### 3.1 Long-term agent

| Test file | Module(s) covered | Test count |
|-----------|------------------|-----------|
| `tests/test_calculator.py` | `engine/calculator.py` | 11 |
| `tests/test_paper_trading.py` | `paper_trading.py` | 27 |
| `tests/test_signals.py` | `signals/momentum.py`, `signals/revisions.py`, `signals/escalation.py` | 31 |
| `tests/test_telegram.py` | `telegram/digest.py`, `telegram/alerts.py`, `telegram/client.py` | 26 |
| `tests/test_cadence.py` | `cadence.py` | ~5 |
| **Total** | | **141 passing** |

**Modules without dedicated tests:** `data/edgar_client.py`, `data/peer_multiples.py`, `agents/model.py`, `agents/valuation.py`, `orchestrator.py`. These are the deeper data-fetch and LLM-orchestration layers — integration-tested only through manual runs, not unit tests. This is the main test coverage gap.

### 3.2 Swing Bot v1

| Test class | Coverage | Test count |
|------------|----------|-----------|
| `TestHardRuleNoRealOrders` | `place_real_order()` always raises | 3 |
| `TestConstraintTags` | `paper_only`, `no_real_orders`, `ringfenced`, `no_live_pnl_learning` on all records | 5 |
| `TestRingfencedPaths` | Data paths under `swing-bot/data/`, not `agent/data/` | 4 |
| `TestKillSwitchSoftAlert` | −10% soft alert, once-per-period, no disable | 8 |
| `TestKillSwitchHardKill` | −20% hard kill, £400 floor, disable flag | 8 |
| `TestKillSwitchTimeExpiry` | Time box trigger at/past/before disable_date | 3 |
| `TestKillSwitchPersistence` | Already-disabled state blocks further checks | 3 |
| `TestKillSwitchAlertFormatting` | Hard kill and soft alert message format | 5 |
| `TestEntryRules` | All 4 conditions block independently, signal computation | 11 |
| `TestExitRules` | All 4 exit conditions, signal reversal priority, return_pct | 10 |
| `TestCountTradingDays` | Mon-Fri counting, weekend skip, reverse dates | 4 |
| `TestFilters` | Phase A/B 8-K, FDA, earnings, volume, negative 8-K | 13 |
| `TestPaperExecutorIO` | Position/trade round-trips, alpha/P&L math | 8 |
| `TestLLMCostCap` | Monthly cap enforcement, disabled when no key | 6 |
| `TestTelegramClient` | Graceful failure on all error types | 4 |
| `TestFinnhubClient` | Rate limit, 429 handling, zero price, batch | 8 |
| `TestActiveWatchlist` | Add/prune/get, cap at 50, dedup, sort, TTL | 10 |
| **Total** | | **112 passing** |

**Critical path coverage:** Hard rule enforcement (`place_real_order` raises, kill switch triggers, LLM disabled) is explicitly tested. ✓

**Missing:** No unit tests for `catalysts/edgar_8k.py`, `catalysts/earnings_monitor.py`, `catalysts/fda_calendar.py`, `catalysts/volume_anomaly.py`, or the scripts themselves. These are the data-fetch layers — tested through integration runs only.

### 3.3 Integration tests

Neither system has formal integration tests. The closest equivalent is the Phase C smoke test run manually on the droplet (confirmed working). The long-term agent's manual test run (`logs/test_run_manual.log`) serves this purpose for the screener pipeline.

---

## 4. Data Integrity Check

### 4.1 Long-term agent data files

| File | Purpose | Gitignored |
|------|---------|-----------|
| `data/paper_positions.yaml` | Open paper positions (12 current) | ✓ (in `.gitignore`) |
| `data/paper_trades.jsonl` | Immutable closed trade log | ✓ |
| `data/screen_state.yaml` | Per-ticker last rating/date/next-due | ✓ |
| `data/signal_log.jsonl` | Rating + confidence history per run | ✓ |
| `data/last_digest_state.json` | Previous ratings for change detection | ✓ |

### 4.2 Swing bot data files

| File | Purpose | Gitignored |
|------|---------|-----------|
| `swing-bot/data/swing_paper_positions.yaml` | Open swing paper positions (0 current) | ✓ (`swing-bot/.gitignore`) |
| `swing-bot/data/swing_paper_trades.jsonl` | Immutable swing closed trade log | ✓ |
| `swing-bot/data/kill_switch_state.yaml` | Kill switch state + cumulative P&L | ✓ |
| `swing-bot/data/active_watchlist.json` | Tier 0 active tickers with timestamps | ✓ |
| `swing-bot/data/seen_accessions.json` | EDGAR accession numbers already processed | ✓ |
| `swing-bot/data/cik_map_cache.json` | Cached EDGAR CIK → ticker map (7-day TTL) | ✓ |

### 4.3 Overlap check

Zero filename overlap. Long-term agent uses `paper_positions.yaml` / `paper_trades.jsonl`; swing bot uses `swing_paper_positions.yaml` / `swing_paper_trades.jsonl`. They live in different directories. ✓

### 4.4 Schema documentation

Schemas are documented in the module docstrings (`paper_executor.py`, `kill_switch.py`) and in the spec (`SWING_BOT_V1_BUILD_SPEC.md`). No standalone schema `.json` files exist — this is an acceptable gap for a system of this scale, but worth noting.

---

## 5. Deployment Health

### 5.1 Cron entries (droplet: `ats-research-simfin`, 209.97.184.179)

| Schedule | Command | Purpose |
|----------|---------|---------|
| `0 9 * * 0` (Sun 09:00 UTC) | `run_universe.py → paper_run.py → write_status.py → send_digest.py → git push` | Long-term agent weekly run |
| `*/15 14-20 * * 1-5` | `swing-bot/scripts/run_catalyst_poll.py` | Swing bot Tier 0 + EDGAR poll |
| `0 22 * * 1-5` | `swing-bot/scripts/run_broad_scan.py` | Swing bot Tier 1 daily broad scan |
| `30 22 * * 1-5` | `swing-bot/scripts/run_eod_mark.py` | Swing bot EOD mark-to-market |
| `15 9 * * 0` (Sun 09:15 UTC) | `swing-bot/scripts/swing_telegram_digest.py` | Swing bot weekly digest |

### 5.2 Last successful runs

| Job | Last Run | Status |
|-----|---------|--------|
| Long-term agent weekly | 2026-05-25 13:06 UTC (manual test run) | ✓ Completed — 6 tickers screened, 12 positions opened |
| Swing bot Tier 0 poll | 2026-05-25 18:45 UTC | ✓ Running — 9 polls completed (Memorial Day, no US market catalysts) |
| Swing bot Tier 1 broad scan | Not yet run (first run tonight 22:00 UTC) | Pending |
| Swing bot EOD mark | Not yet run (first run tonight 22:30 UTC) | Pending |

*Note: Today is Memorial Day (US market holiday). Zero EDGAR 8-Ks were filed and Finnhub quotes were stale. All polls ran correctly and cleanly returned zero catalysts — expected behaviour.*

### 5.3 Errors in last 7 days

Grep for `ERROR`, `Traceback`, `FAIL` across all log files: **zero matches**. Logs are clean. ✓

### 5.4 Disk usage

| Directory | Size |
|-----------|------|
| `~/agent/data/` | 60 KB |
| `~/agent/swing-bot/data/` | 188 KB (includes 174 KB CIK map cache) |

Both well within limits. The CIK map (`cik_map_cache.json`) dominates swing bot data; it refreshes every 7 days.

### 5.5 Python environment

**Version:** Python 3.12.3 (droplet venv at `~/agent/.venv`)

Notable packages:

| Package | Version | Notes |
|---------|---------|-------|
| `anthropic` | 0.104.1 | Current |
| `edgartools` | 5.31.5 | Deprecation warning on `edgar.files.htmltools` — will be removed in v6.0 |
| `yfinance` | 1.4.0 | Current |
| `python-telegram-bot` | 22.7 | Current |
| `requests` | 2.34.2 | Current |

**Flag:** `edgartools` shows a `DeprecationWarning` for `ChunkedDocument` / `HTMLParser` migration in v6.0. The swing bot's `edgar_8k.py` will need updating before edgartools v6. Not urgent but worth tracking.

---

## 6. Cost Discipline

### 6.1 Anthropic API

The long-term agent calls Claude Sonnet for narrative generation once per ticker per week. At 60 tickers/week × ~1 call/ticker, this is ~60 API calls/week. Cost depends on token usage — approximately £0.50–£2/week at current Sonnet pricing, well within the weekly Claude Code budget.

The swing bot's Haiku classifier is **disabled** (`llm.enabled: false`) — zero API cost. Hard cap of £5/month is armed in `classifier.py`. ✓

### 6.2 Finnhub call rate

From 9 poll runs on 2026-05-25 (Memorial Day, no active tickers): **1 call/poll** (SPY quote only). Today's total: **9 Finnhub calls**. On a normal trading day with 20 Tier 0 tickers, expect ~21 calls/poll × 26 polls = ~546 calls/day — well within the free tier's practical limit. Peak observed rate: 54 calls/min in benchmarking (limit: 60). ✓

### 6.3 Cost caps armed

| Cap | Threshold | Mechanism | Status |
|-----|-----------|-----------|--------|
| Haiku monthly spend | £5.00 | `_monthly_cost_exceeded()` in `classifier.py` — reads `data/llm_cost_log.jsonl`, returns `None` if exceeded | Armed ✓ |
| Finnhub rate | 57 calls/min | `_CALL_INTERVAL = 1.05s` in `finnhub_client.py` | Armed ✓ |

---

## 7. Credentials Hygiene

### 7.1 `.env` files on droplet

| File | Permissions | Contents |
|------|------------|---------|
| `~/agent/.env` | Not checked | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EDGAR_IDENTITY`, `ANTHROPIC_API_KEY` |
| `~/agent/swing-bot/.env` | 600 | `SWING_BOT_TOKEN`, `SWING_BOT_CHAT_ID`, `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY` |

### 7.2 Git tracking

`git ls-files | grep .env`: **zero results** — no `.env` files in the git index. ✓

`git check-ignore .env swing-bot/.env`: both are gitignored. ✓

### 7.3 Hardcoded secrets

Grep for `sk-ant-`, `bot_token`, `SWING_BOT_TOKEN` literal values in all `.py` files: **zero hardcoded credential values** found. All files reference environment variables or read from `.env` at runtime. ✓

The grep did surface these references (not secrets — just variable names/comments):

- `finnhub_client.py:31-54` — reads `FINNHUB_API_KEY` from env or `.env` file
- `telegram_client.py:40-43` — reads `SWING_BOT_TOKEN` / `SWING_BOT_CHAT_ID` from env

These are correct patterns. ✓

---

## 8. Current State Snapshot

### 8.1 Long-term agent

**Last run:** 2026-05-25 13:06 UTC (manual test run)  
**Tickers screened today:** 6 (EME, KLAC, MTZ, DY, A, MOD — force-rescreen / due)  
**Universe:** 61 tickers (60 active + 1 BROKEN)

**Rating distribution (full universe):**

| Rating | Count |
|--------|-------|
| STRONG_BUY | 17 |
| BUY | 3 |
| HOLD | 12 |
| SELL | 8 |
| STRONG_SELL | 20 |
| BROKEN | 1 |
| **Total** | **61** |

**Confidence distribution:**

| Confidence | Count | Example tickers |
|------------|-------|----------------|
| HIGH | 6 | ABBV, MCO, MSCI, MTD, OKE, RTX |
| MED | 34 | Majority of universe |
| LOW | 21 | AGX, AVAV, CAT, ENTG, KLAC, LLY, LRCX, VRT… (cohort outliers + thin cohorts) |

**Paper book — 12 open positions (all STRONG_BUY / MED, opened 2026-05-25):**

| Ticker | Entry | Price Target | Implied Upside |
|--------|-------|-------------|---------------|
| ACM | $72.04 | $188.02 | +161.0% |
| AMAT | $432.16 | $578.96 | +34.0% |
| DY | $411.20 | $765.63 | +86.2% |
| EMR | $136.42 | $234.40 | +71.8% |
| GD | $342.89 | $650.07 | +89.6% |
| GNRC | $270.14 | $598.93 | +121.7% |
| HUBB | $475.01 | $590.07 | +24.2% |
| J | $114.69 | $138.93 | +21.1% |
| KMI | $33.79 | $69.18 | +104.7% |
| LDOS | $126.01 | $250.07 | +98.5% |
| SPGI | $417.60 | $523.95 | +25.5% |
| TRGP | $276.75 | $359.29 | +29.8% |

SPY at entry: $745.64. All 12 positions opened 2026-05-25.  
Paper book is day 1 — no alpha to report yet. Benchmark tracking begins now.

**Kill switch:** Not applicable to long-term agent (human is the gate).  
**Decision date:** 2026-11-25 (paper performance vs SPY reviewed).

### 8.2 Swing Bot v1

**Status:** Live on droplet, `alert_mode_only: true` (smoke test phase)  
**First poll:** 2026-05-25 16:45 UTC  
**Last poll:** 2026-05-25 18:45 UTC  
**Polls completed today:** 9 (all clean, zero catalysts — expected on market holiday)  
**Active watchlist (Tier 0):** 0 tickers  
**Open positions:** 0  
**Closed trades:** 0  
**[ALERT] entries logged:** 0  

Kill switch: `disabled: false` | `soft_alert_sent: false` | cumulative P&L: £0.00  
Hard kill floor: £400 (−20% on £500 start)  
Auto-disable: 2026-11-25 (184 days from today)

**Next expected events:**
- Tonight 22:00 UTC: first Tier 1 broad scan (Tue 26 May post-US-close data)
- Tomorrow 14:00 UTC: first full trading-day catalyst polls

---

## 9. Known Issues / Open Bugs

Source: `KNOWN_BUGS.md` (last updated 2026-05-25)

| Bug | Status | Impact |
|-----|--------|--------|
| BUG-001: SUM delisted | **FIXED** | Removed from universe |
| BUG-002: AVAV astronomical PT | **FIXED** | Unit-conversion threshold corrected |
| BUG-003: LMT, MA — BROKEN confidence (net debt model) | **OPEN** | Both show BROKEN, suppressed from actionable ratings. Workaround in place. Proper fix requires per-sector multiple calibration (Path B). |
| BUG-004: HON-class gross_profit=None for conglomerates | **FIXED** | EDGAR label map expanded + computed fallback |
| BUG-005: LLY-class cohort outlier | **FIXED** | Cohort outlier caps confidence at LOW |

**No additional errors in logs.** The `edgartools` `DeprecationWarning` for `ChunkedDocument` in v5.x is a pre-warning for v6.0 removal — not a current error.

**Open items not in KNOWN_BUGS.md:**
- 21 LOW-confidence tickers in the universe include legitimate cohort outliers (KLAC, LLY, VRT, LRCX) whose sector multiples aren't well-represented by the industrial peer groups. These are correctly flagged LOW but the root cause (peer group assignment) is deferred to Path B.
- Swing bot Tier 1 broad scan and EOD mark-to-market have never executed (today is day 1 on a holiday). First live execution is tomorrow evening.

---

## 10. Validation Milestones

### 10.1 Long-term agent paper trade

| Metric | Value |
|--------|-------|
| Paper start date | 2026-05-25 |
| Initial positions | 12 (all STRONG_BUY / MED) |
| Entry benchmark | SPY $745.64 |
| Paper book value | £600 notional (12 × £50) |
| Current return | Day 1 — too early |
| Closed trades | 0 |
| Decision date | 2026-11-25 (184 days) |
| Success criterion | Beat SPY by ≥3% with ≥30 closed trades |

### 10.2 Swing Bot v1

| Metric | Value |
|--------|-------|
| Status | Alert-only smoke test (day 1) |
| `alert_mode_only` | `true` |
| Expected live execution start | After 3 clean trading days of alert-only logs |
| Earliest flip to live | ~2026-05-29 (end of week) |
| Kill switch armed | ✓ Soft −10%, Hard −20% |
| Auto-disable | 2026-11-25 |
| Decision criteria | ≥30 trades, beat SPY by ≥3% → build v2; else kill |

### 10.3 Telegram delivery

| Channel | Bot | Status |
|---------|-----|--------|
| Long-term agent (main) | `TELEGRAM_BOT_TOKEN` | ✓ Confirmed working — live digest delivered 2026-05-25 |
| Swing bot ("ATS Short Plays") | `SWING_BOT_TOKEN` | ✓ Confirmed working — smoke test message delivered 2026-05-25 17:23 UTC |

---

## 11. Deferred Spec Inventory

| Spec file | Status | Trigger to activate |
|-----------|--------|---------------------|
| `SWING_BOT_V1_BUILD_SPEC.md` | **Active** — Phase A/B/C/D in progress | N/A |
| `PAPER_TRADING_BUILD_SPEC.md` | **Superseded** — paper trading layer built | Archived; long-term paper layer is live |
| `TELEGRAM_COCKPIT_BUILD_SPEC.md` | **Phase 1 complete**, Phases 2–3 parked | Phase 2 (command handling `/holds`, `/sells`) triggers when user wants interactive digest. No urgency. |
| `CADENCE_BUILD_SPEC.md` | **Implemented** — cadence engine live in `cadence.py` | N/A |
| `PHASE2_SIGNAL_CROSSCHECK_BUILD_SPEC.md` | **Parked** — per-sector multiple calibration | Trigger: BUG-003 (LMT/MA BROKEN) becomes widespread enough to matter, OR long-term paper return shows systematic sector bias at 6-month review |
| `DEXTER_REVIEW.md` | Unknown status — not found in repo root | Check if this was a design review from an earlier session; may be ephemeral |
| `SWING_SCANNER_BUILD_SPEC.md` | **Superseded by** `SWING_BOT_V1_BUILD_SPEC.md` | The swing bot IS the swing scanner concept |

*Note: `DEXTER_REVIEW.md` was referenced in the spec but not found in the current repo. Either it was never committed or was an in-session document. Not a concern.*

---

## 12. Overall Verdict

The system is well-built and the hard rules are genuinely enforced in code, not just documented. `place_real_order()` raises unconditionally, the deploy script checks hostname in two independent ways, the swing bot has zero imports from the long-term agent, and the kill switch arms on every poll. The test suite is substantial — 253 tests total across both systems, all passing — and it explicitly tests the hard-rule enforcement paths rather than just happy-path logic.

**What's at risk:** Both paper books are on day 1 with no performance history yet. The long-term agent's 12 positions are all STRONG_BUY / MED (no HIGH confidence), and 20 of 61 universe names are STRONG_SELL — a bearish tilt that could look either prescient or overfitted depending on the next 6 months. The swing bot has never executed a live paper trade; the Tier 1 broad scan and EOD mark jobs have never run at all. The next two weeks will reveal whether the catalyst pipeline actually generates useful signals or fires blanks.

**Watch closely in the next 2 weeks:** (1) First swing bot catalyst detections — do EDGAR 8-Ks and volume spikes fire on real tickers, or does the momentum filter (≥3% intraday) eliminate everything? (2) The long-term agent's paper book vs SPY — do the STRONG_BUY positions hold their price targets or immediately diverge? (3) The `edgartools` deprecation warning — v6 will break `edgar_8k.py` when released.

**Over-confident about:** The swing bot catalyst pipeline working correctly end-to-end. It has been unit-tested and smoke-tested on a market holiday, but the EDGAR EFTS search, yfinance earnings data, and Finnhub quote timing have never all fired together on a live catalyst event. The first real week of trading days is where unknown unknowns will surface.

**Under-confident about:** The long-term agent's valuation model. The paper book shows implied upsides ranging from +21% (J) to +161% (ACM) — a very wide spread. ACM's +161% target suggests either a genuine undervaluation or a model artefact. BUG-003 (net debt bridge producing BROKEN for some names) may be a symptom of a broader peer-multiple calibration problem that currently only surfaces for LMT and MA but could affect other sectors. Six months of paper trading will stress-test the model in a way no unit test can.

---

*Audit conducted 2026-05-25. Read-only — no code changes made during this audit. All evidence collected via SSH, file reads, grep, and test execution.*
