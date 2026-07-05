# Phaethon Arm B — Cash-Accounting Bug: Ledger Reconstruction & Fix (2026-07-05)

> **OPEN OPERATOR QUESTION (surfaced, not answered — not Claude's/Claude Code's call):**
> Now that the cash bug is fixed, is Arm B's *restated* performance still interesting
> enough to be a **live candidate**, or does it serve only as a **falsification control**
> going forward? (Note the restated book is still NONCONFORMING on concentration — §4.)

Operator has already determined this is a **cash-accounting bug, not intended leverage**
— this memo goes straight to mechanism and fix.

## 1. Reconstructed ledger

Source: `trader_b/state/book.json` (17 holdings, `cash: -3834.5`, `peak_value: 10715.4`).
Implied starting capital = `cash + Σ(shares·entry) = -3834.5 + 13994.5 = 10160`. Buys,
in fill order (entry_date, then book order), cumulative % of starting capital:

| # | ticker | date | notional | cum % |
|--:|--------|------|---------:|------:|
| 1–11 | CEG…MSFT | 2026-06-24 | — | **95.0%** (11 positions) |
| 12 | **PLTR** | 2026-06-24 | 601.72 | **100.9%** ← first breach |
| 13 | FSLR | 2026-06-29 | 902.28 | 109.8% |
| 14 | ENPH | 2026-06-29 | 683.70 | 116.5% |
| 15 | REGN | 2026-06-29 | 756.43 | 123.9% |
| 16 | JPM | 2026-06-29 | 683.53 | 130.7% |
| 17 | ISRG | 2026-06-29 | 719.85 | **137.7%** |

Σ cost-basis = **$13,994** on **$10,160** of capital → **138% gross exposure, cash −38%**.

## 2. The exact bug (pinpointed)

Cash **is** debited on every fill (that is *why* it is negative — this is not a
"buys don't debit cash" bug). The defect is that **position sizing never caps
cumulative buys against remaining available cash**: each buy is sized to a target
%-of-**NAV** weight, using the full book value as the denominator. The 06-24 batch
already reached ~100% invested; the **06-29 rebalance then added 5 new positions
(FSLR/ENPH/REGN/JPM/ISRG) sized against full NAV as if cash were available**, funded
entirely by driving cash negative. In the task's terms: *stale/carried-forward NAV used
as the sizing denominator + weights not re-derived against actual remaining cash on the
second rebalance.* It is **not** a unit/notional mismatch (price×shares reconciles) and
**not** a missing debit.

## 3. The fix (scorecard layer — strategy FROZEN)

`src/phaethon/ledger.py` replays fills in order with a **hard available-cash cap**:
a buy whose cost exceeds current cash is **rejected/flagged**, never executed into
negative cash. Applied on every publish (`assemble_arm`, `restate=True`) so cash_pct ∈
[0, 100%] and gross ≤ 100%. A within-cash book (Arm A) is unchanged — no false
rejections. Proven by `tests/test_phaethon_ledger.py` (synthetic sequential-buys-exceed-
cash fixture → rejects the breaching order, bounds cash/gross).

## 4. Restatement & NONCONFORMING re-check (reported plainly)

Restated via the corrected math; **originals archived** at
`docs/data/archive/phaethon_{live,b_live}_pre_restatement_2026-07-05.json`; the live
series are marked `"restated 2026-07-05, cash-accounting bug fixed"` with the rejected
orders listed.

| | before | **restated** |
|---|---:|---:|
| **Arm A** (disciplined) | conforming | **38.0% gross, 62% cash — CONFORMING** (unchanged; was within cash) |
| **Arm B** (aggressive) | 138% gross, −38% cash | **94.8% gross, +5.1% cash** — 6 over-cash buys rejected (PLTR, FSLR, ENPH, REGN, JPM, ISRG) |

**Re-check result:** the **leverage flag is now clear** (94.8% ≤ 100%). But Arm B is
**still NONCONFORMING** — for a **different, previously-masked reason**: **concentration**
(CEG 13.5%, GOOGL 13.8% > `MAX_SINGLE_POSITION` 10%). This is **new information for the
operator**, not papered over: the cash bug was hiding an independent position-limit
breach. The aggressive arm's "concentrated" mandate collides with the constitution's 10%
cap — a separate operator decision (and the input to the open question at the top).

## 5. Note
The balance-sheet figures (cash, gross, weights, position count) are restated with full
fidelity from the corrected ledger. A full **return-series** restatement (active-return /
vs-QQQ recomputed over the corrected holdings) requires the trader's per-mark price
history; the headline figures are marked "restated" and the corrected holdings drive them,
but a mark-by-mark performance re-derivation is a follow-up if the operator wants it.
