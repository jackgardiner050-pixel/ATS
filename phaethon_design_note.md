# Phaethon — Self-Learning Trading Agent, Grounded by Zeus (Design Note)

> Status: **ACTIVE — PAPER, two arms (2026-07-05).** Brought under governance 2026-07-05:
> the render + governance checks now live in the repo (`src/phaethon/`, thin cron wrapper
> `scripts/phaethon/publish.sh`); strategy logic is FROZEN. Original concept saved 2026-06-04
> (below) — the parked/backtest concerns there still hold; this is a forward-only paper run.
>
> **The two arms (mandates verbatim):**
> - **Arm A — "Disciplined (A)"** — mandate: *"research-grade discipline"* (cohort `phaethon_a`).
> - **Arm B — "Aggressive (B)"** — mandate: *"+10%/qtr, concentrated"* (cohort `phaethon_b`);
>   kill-switch −25% peak-to-trough.
>
> **Arm B cash accounting:** Arm B's cash accounting (−38%, positions summed to 138%
> gross) is **confirmed by the operator as a bug, not intended leverage** — the fix is
> tracked separately (item 10). The governance leverage check *correctly* flags Arm B as
> NONCONFORMING on this data; that is the check working, not a false positive. Whether B
> remains a live candidate after the fix, or serves only as a falsification control, is
> **still an open operator question.**

> Name: **Phaethon** — son of Helios who insisted on driving the sun-chariot *himself*, couldn't control it, and was struck down by **Zeus** to stop the damage. The fit is exact: a self-directing agent that wants to run on its own, with Zeus (the council) as the governor that reins it in — and the myth honestly encodes the prior (over-reach → fall). (Alt considered: Icarus.)

## The concept (Jack's idea)
A self-learning LLM trading agent that:
- makes its **own assumptions** and proposes trades freely (creative idea-generation),
- is **grounded by Olympus** — Zeus decides, on the council's feedback, whether each proposal is actionable,
- "**learns**" and improves over time,
- runs **in parallel with Olympus**, so the two scorecards can be compared honestly.

Powered by Hermes for (paper) execution. The appeal: separate a bold generator from a disciplined governor — let it propose wildly, let the council reject most of it.

## Why it's parked — the honest constraints (from the 2026-06-04 discussion)
1. **It can't be backtested.** The hindsight is baked into the model's *weights*, not just the prompt — it already absorbed 25+ years including how every period ended. Blinding the dates/tickers blinds the *input*, but the model still recognises the *pattern* ("hyper-growth + AI hype + low rates" → it knows the era and the outcome). **The world-knowledge that makes an LLM worth using IS the contamination.** Blind it enough to be clean and you've removed the reason to use an LLM (and a plain rule-based model would then be better *and* cleanly testable).
2. **Showing it history ≠ learning.** An LLM doesn't weight-update from data fed at run-time; it just reads it. The real learning already happened in pretraining, with the future included. Even fine-tuning on 25 years teaches it one mostly-bull regime → overfit, not skill.
3. **Goodhart risk.** A self-learner pointed at a fixed governance filter learns to *game the filter* (shape proposals to pass Zeus) rather than to be right — turning the council from a check into a target.
4. **Evidence prior.** LLM trading agents mostly lose (the Metis research: StockBench / AI-Trader; "a no-intelligence agent routinely beats AI traders"). Grounding by Olympus can only *reject* bad ideas; it can't make a generator's output good — and Olympus already rejects nearly everything (holds the fund).

## The fork (name it before building)
"Self-learning agent" is two different animals with opposite testability:
- A **machine-learning model** trained on 25y of features: *can* be backtested (walk-forward) — but overfits notoriously, is banned by the current spec (§2.4), and doesn't "reason."
- An **LLM agent that reasons** (Phaethon): can't be backtested; **forward-test only.**
You can't have "reasons like a human *and* learns provably from history" in one box — the reasoning is what makes it un-backtestable.

## The only honest way to build it, if revisited
- **Forward, paper, logged-before-outcome, in parallel with Olympus** — on genuinely-unknown future data. Compare the two scorecards over time. History may *prompt* it; it can never *validate* it.
- **Non-self-modifying / human-gated learning only** — improvement via the journal + post-mortem + calibration loop with rule-changes flagged for human approval, NOT autonomous policy rewriting (which overfits and games the filter).
- **Firewalled from Zeus's criteria** so it can't learn to game the governor.
- **Hosted on the droplet**, not the MacBook (a laptop is not a server).
- Honest prior going in: it will probably lose to passive — but a forward parallel run would settle it with evidence instead of assumption.

## Relationship to Metis
Phaethon is the **evolution of Metis** (the parked once-daily AI agent) — same family, but with the forward-tested, run-in-parallel-with-Olympus, grounded-by-Zeus framing. If built, it supersedes the Metis concept.

## Revisit trigger
Build only if/when: (a) models materially improve, or (b) Olympus itself has earned its keep and you want a benchmarked challenger — and even then, forward-only, human-gated, on the droplet.

## References — repos to draw on (added 2026-06-04)
Mine these for **architecture**, not their backtested returns (LLM backtests are hindsight-contaminated).

**Closest to Phaethon (study first):**
- **TradingAgents** — `github.com/TauricResearch/TradingAgents`. Multi-agent LLM framework: fundamental/sentiment/technical analysts + bull/bear debate + risk team + trader synthesis, on LangGraph, supports Claude. Already does reflection-based self-learning (fetches realized return → writes reflection → stores in memory). ~80% of Phaethon; maps onto Olympus's council too. Build on it; wrap it in Olympus governance + forward-test, which it lacks.
- **FinMem** — `github.com/pipiku915/FinMem-LLM-StockTrading`. Layered memory + reflection + character profiling — the "self-evolve via memory aligned to market feedback" blueprint.

**RL / quant branch (backtestable but overfits) — only if going the ML-model route, not LLM:**
- **FinRL** — `github.com/AI4Finance-Foundation/FinRL` (deep RL: PPO/SAC/DQN). Plus **FinGPT** (finance LLM) and **Qlib** (Microsoft quant ML platform).

**Memory design + references:**
- `alejandroll10/llm_trading_sim` (agents write notes to themselves between rounds — minimal self-memory loop).
- `MemoryAgentBench` (ICLR 2026, evaluating agent memory) + `DEEP-PolyU/Awesome-GraphMemory` (graph-based agent memory survey).
- `wangzhe3224/awesome-systematic-trading` (meta-list to mine further).

**How to use them:** lift the multi-agent-debate + layered-memory + reflection-loop patterns; run forward-only; guard against Goodhart (gaming the council); keep Olympus's discipline (governance, honest forward scorecard, no real money) as Phaethon's edge over these projects.

## Chassis — build on NousResearch/hermes-agent (added 2026-06-05)
Recommended foundation: **`github.com/NousResearch/hermes-agent`** (MIT, ~181k stars) — a self-improving *general* AI agent with a built-in closed learning loop (agent-curated memory, autonomous skill creation, skills that self-improve in use, FTS5 cross-session recall, user modeling). Model-agnostic, designed to run on a cheap VPS/cloud (not a laptop), with a built-in cron scheduler and Telegram/Discord gateways. It solves Phaethon's self-learning scaffold AND the deployment questions (droplet, scheduled, Telegram) out of the box. Build Phaethon *on* it, not from scratch.

Caveats (critical):
- **General assistant, not a trader** — zero market logic or edge. Build the trading reasoning + Zeus grounding + forward scorecard on top. It's the body, not the strategy.
- **Its learning improves skills/recall, not market forecasting** — the honest prior is UNCHANGED: forward-only, can't be backtested, most likely loses on markets. It makes Phaethon easier to build/run, not more likely to have edge.
- **Security — sandbox heavily.** It runs shell + 40+ tools autonomously. For paper-only/no-real-money: lock the toolset to read-only market data + analysis + the paper executor; deny any broker/money/order tool; lock the command allowlist; no real credentials; isolated on the droplet.
- **Naming:** this "Hermes" (Nous's agent framework) ≠ Olympus's "Hermes" (execution layer). Phaethon is *built on* nous-hermes-agent; Olympus-Hermes stays the paper executor underneath. Keep distinct.
