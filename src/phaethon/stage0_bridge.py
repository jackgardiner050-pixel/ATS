"""Phaethon → Stage-0 registration bridge (B-22 / §G-6).

A one-way, read-only extractor: it turns a Phaethon arm's *proposal rationale* (the reasoning
behind a BUY it proposed — never an outcome, win/loss, fill, or realised P&L) into a Stage-0
**registration candidate**: a plain YAML file a human reviews before advancing it into the
hash-chained research registry.

Direction is Phaethon → registry ONLY. Nothing in this module reads registry state, a Stage
result, `retired.yaml`, or any council output — and none of that may ever flow back into a
Phaethon prompt-construction path (enforced by tests/test_constitutional_guards.py). This
module is HUMAN-SIDE machinery (like src/phaethon/journal.py); it is not on any path that
builds what Phaethon sees.

A candidate carries **zero inherited credibility** (§33): `source_provenance` records only that
it came from an LLM arm's rationale on a given prompt version and date. It must clear Stage 1–3
on its own like any other Stage-0 entry; being Phaethon-sourced licenses nothing.

Activation / kill (§G-6, §M.1 elapsed-time fallback):
  * Active the moment this is built — every extracted rationale is a Stage-0 candidate.
  * Retire the bridge if extracted candidates produce Stage-1 survivors at a rate
    indistinguishable from random eligible names over 50 candidates (same test as §G-5).
    If 50 candidates has not been reached by the §M.4 programme-review date, review then.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path

import yaml

# ── forbidden inputs: a rationale must never carry an outcome. Enforced at runtime, not just
#    by convention — if any of these keys appear in the input dict the extraction is refused.
_OUTCOME_FRAGMENTS = (
    "outcome", "win", "loss", "won", "lost", "pnl", "return", "fill", "exit_price",
    "hold_days", "mark_to_market", "book_value", "cash_pct", "drawdown", "profit",
    "realiz", "realis",  # realized/realised gain
)

_DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "research" / "stage0_candidates"

# best-effort map from a Phaethon thesis_category to the B-16 fingerprint vocabulary. A human
# corrects this during review; it is a starting point, never authoritative.
_THESIS_TO_SIGNAL_FAMILY = {
    "momentum": "price_momentum", "trend": "price_momentum",
    "earnings": "post_earnings_drift", "pead": "post_earnings_drift",
    "catalyst": "catalyst_momentum", "event": "event_8k", "8k": "event_8k",
    "value": "value_cross_sectional", "valuation": "value_cross_sectional",
    "reversion": "mean_reversion", "mean_reversion": "mean_reversion",
    "quality": "value_cross_sectional", "thematic": "thematic_momentum",
    "ai": "thematic_momentum", "secular": "thematic_momentum",
}


class RationaleContainsOutcome(ValueError):
    """The proposal rationale carries an outcome/P&L field — refusing (one-way, no learning)."""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"


def _guard_no_outcome(rationale: dict) -> None:
    hits = sorted(k for k in rationale
                  if any(frag in k.lower() for frag in _OUTCOME_FRAGMENTS))
    if hits:
        raise RationaleContainsOutcome(
            f"rationale must contain only proposal reasoning, never an outcome; "
            f"offending key(s): {', '.join(hits)}")


def rationale_to_stage0_candidate(rationale: dict, *, arm: str, prompt_version: str,
                                  date: str | None = None) -> dict:
    """Map ONE Phaethon proposal rationale to a Stage-0 registration candidate dict.

    `rationale` expected keys (all proposal-side, no outcomes):
        ticker (str, required), thesis_text / reasoning (str), thesis_category (str),
        stated_conviction / conviction_tier (str|num), horizon (str), universe (str).
    """
    if not isinstance(rationale, dict):
        raise ValueError(f"rationale must be a dict, got {type(rationale).__name__}")
    _guard_no_outcome(rationale)

    ticker = rationale.get("ticker")
    if not ticker:
        raise ValueError("rationale missing required 'ticker'")
    date = date or _dt.date.today().isoformat()
    thesis = (rationale.get("thesis_text") or rationale.get("reasoning")
              or rationale.get("thesis") or "").strip()
    category = (rationale.get("thesis_category") or "").strip()
    fam = _THESIS_TO_SIGNAL_FAMILY.get(category.lower().replace(" ", "_"), "UNCLASSIFIED")

    cand_id = f"phaethon-{_slug(arm)}-{_slug(ticker)}-{_slug(date)}"
    hyp = (f"A Phaethon-{arm} rationale claims {ticker} has forward excess return via: "
           f"{thesis[:240] or '(no thesis text supplied)'}")

    return {
        "candidate_id": cand_id,
        "created": date,
        "stage": 0,
        "status": "CANDIDATE",          # NOT a registry status — a human runs registry.py to advance
        "credibility": "zero inherited (§33) — must clear Stage 1-3 independently",
        "hypothesis": hyp,
        "mechanism": thesis or "UNSPECIFIED — human must state the counterparty / why the edge exists",
        "universe": rationale.get("universe") or "Phaethon eligible universe (state precisely on review)",
        "window": rationale.get("horizon") or "UNSPECIFIED",
        "source_provenance": {
            "phaethon_arm": arm,
            "prompt_version": prompt_version,
            "date": date,
            "stated_conviction": rationale.get("stated_conviction")
            or rationale.get("conviction_tier"),
            "thesis_category": category or None,
        },
        "proposed_fingerprint": {          # B-16 vocab — starting point for functional_equivalence_check
            "signal_family": fam,
            "lookback_class": "UNSPECIFIED",
            "horizon_class": "UNSPECIFIED",
            "universe_class": "us_large_cap",
            "action_type": "long_only",
            "conditioning": "catalyst" if category.lower() in ("catalyst", "event", "8k")
            else "unconditional",
        },
        "interpretation_contract": {
            "licenses": "nothing yet — this is an unreviewed candidate; a PASS would license only "
                        "what its eventual registered hypothesis states",
            "does_not_license": "any claim that a Phaethon arm's conviction is itself evidence",
        },
        "note": "Generated by src/phaethon/stage0_bridge.py from a proposal rationale. One-way: "
                "no registry state or Stage result informed this file.",
    }


def write_stage0_candidates(rationales, *, arm: str, prompt_version: str,
                            date: str | None = None, out_dir: Path | str | None = None) -> list[Path]:
    """Extract each rationale and write `<out_dir>/<candidate_id>.yaml`. Returns the paths.
    out_dir defaults to research/stage0_candidates/ — a plain directory of proposals, NOT the
    hash-chained registry."""
    out = Path(out_dir) if out_dir is not None else _DEFAULT_OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for r in rationales:
        cand = rationale_to_stage0_candidate(r, arm=arm, prompt_version=prompt_version, date=date)
        p = out / f"{cand['candidate_id']}.yaml"
        text = yaml.safe_dump(cand, sort_keys=False, allow_unicode=True)
        cand["_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        p.write_text(yaml.safe_dump(cand, sort_keys=False, allow_unicode=True))
        written.append(p)
    return written
