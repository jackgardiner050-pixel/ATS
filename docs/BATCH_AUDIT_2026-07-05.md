# Batch Self-Audit — 2026-07-05

Governance/observability batch. Branch `governance-batch` (off `nav-ledger`).
One commit per PART. **PARTs A–E implemented; PARTs F and G STOPPED at the protocol
lock and reported below (not implemented).**

## 1. Test suite

`pytest tests/ -q` → **747 passed, 6 failed, 0 skipped/xfailed.**

The 6 failures are the pre-existing `tests/test_dashboard_live.py` HTML-id checks
(unrelated to this batch — the committed `docs/index.html` uses a newer structure
than that test expects). **No new failures introduced.** Per-PART test additions:
admission 7 +1, constitutional-guards 7, extraction 14, rating-distribution 7,
attribution/feedback 6 (+ helpers) — all green.

## 2. Files touched (git diff --stat vs batch base 260fc71) — annotated

| File | PART | In scope? |
|------|------|-----------|
| `src/universe/admission.py` (new) | A | ✓ market-cap admission |
| `scripts/run_universe.py` | A + E | ✓ A: mcap gate; E: log_screen_decision |
| `tests/test_universe_admission.py` (new) | A | ✓ |
| `tests/test_governance_constitution.py` | A | ✓ read-only mcap-floor assertion |
| `tests/test_constitutional_guards.py` (new) | B | ✓ CI §1 guards |
| `src/data/extraction_invariants.py` (new) | C | ✓ pure invariants |
| `scripts/extraction_audit.py` (new) | C | ✓ audit harness |
| `tests/test_extraction_invariants.py` (new) | C | ✓ |
| `tests/test_extraction_audit.py` (new) | C | ✓ |
| `scripts/run_weekly.sh` | C | ✓ Step 0b (extraction audit) |
| `src/governance/constitution.py` | D | ✓ check_rating_distribution (`.py`, not the locked yaml) |
| `src/governance/dashboard.py` | D | ✓ calibration card |
| `scripts/run_governance.py` | D | ✓ wire rating_counts |
| `tests/test_rating_distribution.py` (new) | D | ✓ |
| `scripts/paper_run.py` | E | ✓ entry_signals enrichment (unlocked route) |
| `scripts/attribution_report.py` (new) | E | ✓ |
| `tests/test_no_feedback_imports.py` (new) | E | ✓ permanent feedback guard |
| `tests/test_attribution_report.py` (new) | E | ✓ |

18 files, +1305/−4. Every file matches its PART's stated scope.

## 3. Global hard boundaries — checked one by one

1. **No edits to `src/signals/momentum.py` / `revisions.py` logic** — ✓ neither file
   is in the diff.
2. **No edits to any `config/protocol_lock.yaml` ruleset_file** (`paper_trading.py`,
   `engine/calculator.py`, `signals/*.py`, `constitution.yaml`, `settings.yaml`,
   `universe.yaml`) — ✓ confirmed: `git diff --name-only` shows NONE touched.
   `src/paper_trading.py` is byte-for-byte **unchanged**.
3. **No changes to `should_enter` / `should_exit` core downgrade / anything under
   `src/engine/`** — ✓ `paper_trading.py` unchanged; no `src/engine/*` in diff.
4. **No parameter derived from live book / 12 legacy positions / realized P&L** — ✓
   every threshold is sourced from existing docs/config (§4). None chosen against
   current data.
5. **Every new check is diagnostic (logs/warns/reports), no state mutation** — ✓
   admission excludes pre-rating (gate, no rating/position/trade change); extraction
   audit writes a report; rating-distribution warns; attribution logs/reports.
6. **Reuse existing `config/portfolio.yaml`** — N/A in A–E (relevant to F, which was
   stopped); no duplicate config created.

## 4. New parameters / thresholds — every one tagged

All **sourced** — none are placeholders (the placeholder-bearing PART G was not built).

| Parameter | Value | PART | Source |
|-----------|-------|------|--------|
| min/max_market_cap_usd | 500M / 200B | A | **config/settings.yaml** (read, not chosen) |
| mcap-floor assertion | ≥ 100M | A | task spec (read-only invariant) |
| broker-lib denylist | 7 libs | B | task / SYSTEM_AUDIT_2026-05-25.md §1 |
| revenue tolerance | 15% | C | **KNOWN_BUGS.md** BUG-004/006 |
| gross_margin band | (0, 0.90) | C | **KNOWN_BUGS.md** BUG-006 |
| op_margin vs yfinance | 10pp | C | task (carried from bug reports) |
| shares tolerance | 10% | C | **KNOWN_BUGS.md** BUG-002 |
| net_debt tolerance | 25% | C | **KNOWN_BUGS.md** BUG-003 |
| unit magnitude | [1e6, 1e13] | C | **KNOWN_BUGS.md** BUG-002 |
| PT/price ratio | [0.2, 3.0] | C | **KNOWN_BUGS.md** BUG-002/005 |
| WARN_STRONG_BUY_FRACTION | 0.20 | D | task / prior review discussion |
| WARN_EXTREME_TAIL_FRACTION | 0.35 | D | task / prior review discussion |
| attribution MIN_N | 10 | E | task spec ("insufficient data (n<10)") |

## 5. Protocol lock

`python scripts/verify_protocol_lock.py` → **PASS** (exit 0):
> Protocol lock OK — protocol + ruleset match config/protocol_lock.yaml.

No locked file needs re-registration for A–E. Two deviations were taken specifically
to AVOID a lock break (both flagged, human may choose to re-register later):
- **PART D**: the task wanted `WARN_*` keys in `config/constitution.yaml` (locked).
  Delivered as code-level defaults in `constitution.py` (identical pattern to the
  existing `WARN_CONFIDENCE_LOW_FRACTION`). To move them into `constitution.yaml`,
  re-register the lock deliberately.
- **PART E**: the task wanted `entry_signals` added to `open_position`/`close_position`
  (locked `paper_trading.py`). Delivered as an additive enrichment in `paper_run.py`
  (orchestration layer) — same persisted field, zero decision-input change.

## 6. NAV-ledger / trade-record reconciliation (Part F cross-check)

**NOT PERFORMED — deferred with PART F (see §7).** PART F requires editing
`close_position` inside the protocol-locked `src/paper_trading.py`; per the boundary
and PART F's own instruction ("STOP and report back rather than triggering a lock
break"), it was not implemented, so `tests/test_nav_and_trade_reconciliation.py` was
not created and the cross-check was not run. What exists today: the NAV ledger's
**portfolio-level** per-side cost haircut (`build_snapshot`, tested). The **trade-level**
net / dividend-adjusted alpha and the reconciliation test are part of F and remain
undone. This is stated explicitly rather than omitted.

## 7. Plain-language summary

This batch adds five diagnostic/observability layers, all additive and none touching
decision logic or locked files: **(A)** a market-cap admission gate that excludes
out-of-band names before rating; **(B)** CI tests that enforce the hard constitutional
rules (no broker libs, swing-bot ringfence, deploy guards, locked configs, place_real_order
raises); **(C)** an EDGAR-vs-yfinance extraction audit with bug-report-sourced invariants;
**(D)** a rating-distribution governor that (correctly) warns on the current tail-heavy
book; **(E)** attribution wiring — screen-decision logging, an `entry_signals` snapshot on
positions/trades, and a bucketed attribution report — plus a permanent guard that outcome
data never reaches the engine/signals.

**Stopped and awaiting a human decision:** **PART F** (honest net/total-return math in
`close_position`) and **PART G** (feature-flagged exit rules v2) both require editing
protocol-locked files (`paper_trading.py`, and for G also `settings.yaml`) and, for G,
touch decision logic. Both were left unimplemented per the lock boundary. To proceed, a
human must decide to deliberately re-register the lock; **PART G should be its own isolated
PR** as specified. F's reconciliation cross-check is undone until F is built. Options for F/G:
implement in the locked files (then re-register), or — if acceptable — deliver F's net/TR
fields via the same unlocked orchestration-layer enrichment used in PART E, and G's
`evaluate_exit_v2` as a new unlocked pure module (flag OFF, unwired) with the gate wiring
deferred. Awaiting direction.
