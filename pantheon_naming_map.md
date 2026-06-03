# The Pantheon — Naming Map

> Convention: the ecosystem ("Olympus") names every component for the Greek god whose domain matches its FUNCTION. Any new model/member/layer added from here gets a pantheon name proposed on the same basis (function → god → reason).
> Established: 2026-05-29.

## System

**Olympus** (a.k.a. the Pantheon) — the whole ecosystem; the assembly of gods, each with a domain, presided over by one.

## Members (the viewpoints / edges)

| Name | Function (was) | Why this god |
|---|---|---|
| **Apollo** | structural / thematic detection (SCAI-II) | God of prophecy, light, pattern — the Oracle. Sees where the market is structurally heading; home of the "next-wave" founding challenge. |
| **Oracle** | causal-reasoning rating engine; forward-test, unvalidated. (Apollo = parked, falsified picker.) | Reasoned buy/sell/hold ideas with a falsifiable invalidation line, logged before the outcome — `~/labs/oracle/`. Advisory only: no broker, feeds other models as inputs. |
| **Demeter** | valuation / value member (new) | Goddess of harvest and the slow cycle — sow cheap, reap later, endure the lean seasons (value's droughts). That is value investing. |
| **Phobos** | volatility / variance premium (new) | God of fear — the VIX is literally the "fear gauge." (Alt: Poseidon, storm/turbulence, if naming the chaos over the fear.) |
| **Hades** | crash detection / de-risk | Ruler of the underworld; presides over the downside everyone else pretends won't come. See `hades_design_note.md`. |
| **Kairos** | short-horizon event / earnings reaction (Mercury) | God of the fleeting opportune moment — seize it instantly or it's gone; the earnings pop at the open. Renaming kills the Hermes/Mercury duplication (same god). Currently parked (~null in large caps). |

## Layers (machinery, not viewpoints)

| Name | Function (was) | Why this god |
|---|---|---|
| **Zeus** | the Council / decision layer | King of the gods; presides over the pantheon and arbitrates the gods' disputes — the "council tears it apart or agrees" dynamic. He decides; members argue before him. |
| **Themis** | governance / benchmark discipline (ATS) | Titaness of divine law, order, and the scales. The rules everything runs under. In myth she counsels Zeus — governance sits beside the council exactly as it should. |
| **Hermes** | execution / the book (Hermes v3) | Messenger and god of trade/merchants who crosses between worlds — carries Zeus's decision into the market. (Also god of thieves — fitting for whoever handles slippage.) |
| **Athena** | learning / critique layer (Hermes v2) | Goddess of wisdom and strategic counsel, born of pure thought, the check on hubris. Generates and scrutinises hypotheses. |
| **Mnemosyne** | attribution / observability | Titaness of memory — remembers what every member did and credits each one's contribution; the system's record. |

## Dissolved / retired

- **Hermes v1** — dissolves; it was only Apollo's signal run through Themis's rules and executed by Hermes. No separate identity needed.
- **Mercury** — renamed **Kairos** (same god as Hermes in Roman form; the duplication is removed).

## Coherences worth keeping

- **Zeus** (council) decides but is bound and advised by **Themis** (governance).
- **Hermes** (execution) carries Zeus's rulings to market.
- **Athena** (learning) counsels; **Mnemosyne** (memory) records; **Hades** guards the downside.
- **Apollo, Demeter, Phobos, Kairos** are the members who bring their views to the assembly.

## Candidate future members (untried, orthogonal — for when a slot is earned)

The critical review: everything built so far is the *same* bet — long, US, equity, momentum/event-driven, concentrated. These are the genuinely *different* bets, ranked by orthogonality + buildability on free data. The discipline gate still applies (validate something first; don't build all of them).

| Name | Function | How it serves Olympus |
|---|---|---|
| **Nemesis** | mean-reversion / contrarian | Buys oversold, fades overbought — the literal opposite of every momentum member; the most anti-correlated thing you could add. Most orthogonal. |
| **Plutus** | FX / carry | Currencies + carry trade — not US equity at all; free/backtestable data; documented carry/trend/value effects. The cleanest decorrelation. |
| **Hephaestus** | commodities / real assets | Metals & energy (the forge); decorrelated from equities, and a *real* crash diversifier you simply hold — no timing (unlike the falsified Hades overlay). |
| **Hestia** | quality / durability factor | Stable, profitable, low-debt companies (the enduring hearth) — the counterweight to momentum and junk-loading. |
| **Phobos** | volatility | Designed, shelved on the options-data wall; a future member when data allows. |

Priority order: **Nemesis → Plutus → Hephaestus.**

## Hades — reframed (2026-06-01)
The automated de-risk overlay is FALSIFIED (recovery-miss tax). Reframed role: **human-in-the-loop master kill switch / circuit breaker** — at a large portfolio drawdown (e.g. −20%) it surfaces context + historical analogs + a recommendation and *asks the human to decide*; it never auto-sells. Honesty rules: recommendation = context, not a confident sell/hold (can't time it); default lean = "hold through unless structural" (recovery was always bigger). The behavioural backstop, not a timing strategy.

## Explicitly excluded
**Penny stocks / micro-caps** — not in the T212 ISA, lottery-grade risk, spreads that eat any edge, manipulation/fraud-prone, base rate near-zero. This is the day-one "biggest movers = least tradeable" lesson (Astrotech +527% et al.). Permanently out of scope.

## Cross-references
- `council_architecture_note.md` — the three-tier architecture (members → Zeus → Hermes, with Athena + Mnemosyne cross-cutting).
- `hades_design_note.md` — crash/de-risk member.
- `mercury_design_note.md` — Kairos (post-earnings drift), parked.
