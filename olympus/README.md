# Olympus MVP — governed, paper-only decision-support (Phase 1 thin slice)

> Olympus researches. Zeus decides. Hermes prepares. **The human authorises.**

This is the **consolidation** package (§0): a thin orchestration layer that **wraps the existing
members in place** — it does not fork or duplicate them. Phase 1 is an end-to-end **thin slice**
that runs **one real candidate (ORCL, from Oracle's actual forward-test ledger)** through every
member, the **real governance limits**, and the **real hash-chained `pit_ledger`** — no stubs.

## Run
```bash
cd ~/agent/olympus && python3 -m olympus.cli decision create --candidate ORCL
python3 -m pytest tests/ -q
```

## Wrapped members (in place — nothing moved)
| MVP member | Wraps (real code) |
|---|---|
| Oracle (§4.1) | `~/labs/oracle` — thesis + hash-chained forward-test ledger |
| Athena-Nemesis (§4.2) | `~/labs/awareness/athena.py` (pre-mortem; LLM red team `src.governance.adversarial` plugs in) |
| Hecate (§4.3/§9) | `~/agent/src/governance/exposure.py` + core/satellite overlap |
| Tyche (§4.4) | `~/agent/src/governance/concentration_governor.py` + `src/portfolio/survivability_engine.py` |
| Themis-Mnemosyne (§4.5/§7) | `~/agent/src/governance/constitution.py` + correlated-council rule |
| Zeus (§4.6) | new synthesis (no mechanical averaging) |
| Hermes (§4.7) | execution pathway only — wraps `~/trading/hermes_v3_lab` (no broker) |
| ledger spine (§11) | `~/labs/experimental_pot_engine/track/pit_ledger.py` (real, immutable) |

## What it produced for ORCL
**HOLD · LOW confidence**, confidence constrained by 6 real findings (weak evidence, priced-in,
core overlap, Athena reduce-confidence, correlated agreement, a constitution violation). The
honest dominant output — HOLD / buy-the-cheaper-ETF / insufficient evidence — emerged on its own.

## Invariants
Paper-only · no broker · no autonomous optimisation · every output ends "Human authorisation
required" · research-grade (forward-test in progress, NOT validated) · nothing published live
(`olympus/data/` is ring-fenced).

## Not built (by design)
The full pantheon. §5 gods are documented placeholders only (`docs/constitution.md`).
