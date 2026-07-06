# Live Pilot Protocol — E1 Human-Executed Long-Only US Equity Pilot

**Status:** DRAFT for hash-lock · **Start:** November 2026 · **Execution stage:** E1 (human places every order from system-generated order cards) · **System:** paper-validated *in process*, **not** performance-validated.

This protocol governs a small live pilot of the Oracle/Cohort-1 rating system. Its limits are enforced in code by `config/live_limits.yaml` + `src/live/limits.py`; the numbers in §2 and §5 populate that file's operator/protocol placeholders and change only by re-registration. It is written to be hash-locked: nothing here is meant to be softened later.

---

## 1. What this pilot can and cannot claim

**At the start of this pilot, the statistical evidence that this system generates alpha is effectively zero.** The paper cohort has validated the *process* — that rules execute as locked, that costs are modeled realistically, that a calibration sample accrues — but it has **not** validated *performance*: per the observation protocol, the window cannot establish that alpha ≠ 0.

**Outperformance versus SPY is NOT claimable at the start of this pilot, and it will NOT become claimable during the pilot at this capital and duration.** At pilot scale (§2) over 13 weeks (§3), the standard error on excess return dwarfs any plausible skill alpha; a positive or negative return over the pilot is noise and carries no evidentiary weight about edge.

**What the pilot CAN establish** is operational: that order cards translate to fills faithfully, that realized slippage matches the model, that the guard layer holds under live conditions, that no data gaps or reconciliation breaks occur, and that the human-execution loop works end to end. **This is a live rehearsal of the machinery, not a bet on returns.** Capital is treated as tuition (§2): money the operator is prepared to lose in full to learn whether the operational system is trustworthy before any question of edge is even asked.

## 2. Capital

`MAX_LIVE_CAPITAL_GBP` is **operator-set** and defaults to **0** (the guard layer refuses to generate order cards while it is 0). The operator sets it to an amount framed strictly as **loss tolerance**: the largest sum whose *total loss* would be an acceptable tuition cost, not an amount sized to a return target. Sizing is capital-preservation-first — position sizes follow `MAX_SINGLE_POSITION_LIVE` (10%) and are chosen to survive being wrong, not to maximize expected gain.

**Hard rule:** `MAX_LIVE_CAPITAL_GBP` changes **only via re-registration** of this protocol and `config/live_limits.yaml` — never intra-pilot, never by the system, never "just this once" to average down or press a winner.

## 3. Duration

**Recommended: 13 weeks** (one quarter), with a **pre-declared review at week 13** whose decision rule is fixed in advance: *continue to a re-registered pilot-2, stop, or extend* — decided against the §4 operational criteria only, never against the pilot's return. A calendar-fixed review prevents the outcome from choosing the stopping point. There is no mid-pilot lengthening on the basis of results.

## 4. Success criteria — all operational (returns are explicitly excluded)

The pilot **succeeds** only if ALL hold across the full window:
1. **100% intent/fill reconciliation** — every order card maps to exactly one recorded fill (or a logged, explained cancel); zero unreconciled orders.
2. **Realized slippage within ±10 bps/side of the modeled 20 bps/side** (i.e. realized ≤ 30 bps/side, and not systematically better in a way that implies the model is wrong).
3. **Zero guard violations** — no `LiveLimitViolation`, no breach of position/order-rate limits, no card issued while unfunded or out of stage.
4. **Zero unexplained data gaps** — every price/mark used is sourced and timestamped; any gap is logged and explained, none silently filled.
5. **All drills passed pre-start** — halt drill, kill drill, reconciliation drill, and a data-outage drill executed and passed before the first live order.

Return, IR, and alpha are **not** success criteria and are not reported as evidence of edge (§1).

## 5. Loss breakers (proposed — populate `config/live_limits.yaml` on re-registration)

Anchored to capital preservation, mirroring the existing subsystem pattern of **−10% soft / −20% hard cumulative**:

| Breaker (`live_limits.yaml` key) | Value | One-line justification |
|---|---|---|
| `DAILY_LOSS_HALT_PCT` | **−3%** | A single day beyond −3% at this scale signals an execution/data fault, not a market move — halt new cards for the day and inspect, don't trade through it. |
| `WEEKLY_LOSS_HALT_PCT` | **−6%** | A week down >6% on ≤5 orders is a sizing/concentration failure — pause new cards for the week and review before issuing more. |
| Cumulative **soft** review | **−10%** | Mandatory operator review and pause (not a kill) — the point at which "is the process sound?" must be answered before continuing. |
| `CUMULATIVE_KILL_PCT` | **−20%** | Hard terminate. −20% is the tuition ceiling; the pilot ends and goes to post-mortem (§8). No discretion, no averaging back in. |

A breaker halt/kill is a **stop**, never a signal to re-risk. Halts pause card generation; the kill ends the pilot.

## 6. Explicit non-goals

This pilot is **not** and will not, within its scope, become any of the following:
- **Scaling** — no capital increase intra-pilot; growth is a separate re-registered decision after a passed review.
- **Automation beyond E1** — no autonomous execution. `execution_stage: E2` cannot even parse under the current constitution (it requires constitution v3). A human executes every order.
- **Phaethon routing** — no pilot order originates from or routes through Phaethon unless Phaethon's *own* onboarding protocol is separately drafted and hash-locked. The two systems do not share an execution path here.

## 7. Relationship to Cohort-1

The paper cohort (Cohort-1) **continues to its full 52-week observation window, completely untouched.** This pilot:
- does **not** terminate, pause, shorten, or modify Cohort-1 or its ruleset;
- does **not** borrow, merge, or cite Cohort-1's data as evidence for the pilot, or vice versa;
- produces **operational** evidence only, which never feeds Cohort-1's performance record.

Both may draw picks from the same rating engine, but they are **separate books with separate evidence ledgers.** The pilot's existence changes nothing about Cohort-1's clock or its §5 gates.

## 8. Termination & post-mortem

The pilot **terminates** on any of: (a) `CUMULATIVE_KILL_PCT` (−20%) breached; (b) any §4 criterion definitively failed (e.g. a reconciliation break or a guard violation); (c) the week-13 review deciding "stop"; (d) operator halt for any reason.

On termination, before any decision about a successor pilot:
1. **Freeze** — no new cards; close or hand off open positions per the operator's instruction (human-executed).
2. **Reconcile** — final intent/fill/slippage reconciliation; archive the full order-card and fill log.
3. **Write the post-mortem** — what the machinery did vs. what it should have done, every guard event, every data gap, every drill result; state plainly whether the operational criteria (§4) were met. Returns are recorded but **not** interpreted as evidence of edge (§1).
4. **Decide deliberately** — any successor requires a new re-registration; nothing carries forward automatically.

---

*This document is hash-locked at approval. Every number in §2 and §5, and the stage in §1, is mirrored in `config/live_limits.yaml`; the two are changed together, only by deliberate re-registration.*
