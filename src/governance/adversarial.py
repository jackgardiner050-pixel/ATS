"""Adversarial Review Engine — LLM-powered thesis critique.

This IS an acceptable use of LLM reasoning. Purpose:
  - Generate the strongest possible counterarguments to the current portfolio
  - Prevent narrative lock-in and false confidence
  - Surface hidden assumptions and macro dependencies

LLM role: CRITIQUE and CONTRADICTION FINDING only.
LLM role: NOT trade prediction, NOT price targets, NOT financial math.

Hard rules:
  - Adversarial outputs stored in data/governance/adversarial_log.jsonl only
  - Never overwrites core data files (paper_positions.yaml, signal_log.jsonl, etc.)
  - Disabled gracefully when ANTHROPIC_API_KEY is absent
  - Output is clearly labelled as adversarial critique, not recommendation

Cost: single Claude Haiku call per run (~$0.001). Should be rate-limited to weekly.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, UTC

from src.io_utils import append_jsonl
from pathlib import Path
from typing import Optional

import yaml

_POSITIONS_PATH = Path(__file__).parent.parent.parent / "data" / "paper_positions.yaml"
_SCREEN_STATE = Path(__file__).parent.parent.parent / "data" / "screen_state.yaml"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_ADVERSARIAL_LOG = _DATA_PATH / "adversarial_log.jsonl"

# Never touch any of these files from this module
_PROTECTED_PATHS = [
    "data/paper_positions.yaml",
    "data/paper_trades.jsonl",
    "data/signal_log.jsonl",
    "data/screen_state.yaml",
    "data/last_digest_state.json",
]

_SYSTEM_PROMPT = """You are a professional risk analyst conducting a formal stress test of a paper equity portfolio.
Your only job is to find what is WRONG with the portfolio thesis.

Rules:
- Do NOT make price predictions or investment recommendations
- Do NOT generate buy/sell ratings
- Do NOT invent financial numbers
- DO surface hidden risks, wrong assumptions, and macro dependencies
- DO identify the strongest counterarguments to the current thesis
- Be genuinely critical — not performatively cautious

Respond in valid JSON only. No prose outside the JSON structure."""

_USER_PROMPT_TEMPLATE = """Stress-test this paper portfolio:

Portfolio tickers: {tickers}
Portfolio themes: {themes}
Portfolio factors: {factors}
Concentration warnings already identified: {warnings}
Signal alignment summary: {alignment_summary}

Generate adversarial analysis in this exact JSON structure:
{{
  "macro_counterarguments": [
    "string: strongest macro argument AGAINST this portfolio (3 entries)"
  ],
  "hidden_assumptions": [
    "string: key assumption that if wrong would invalidate the thesis (3 entries)"
  ],
  "concentration_concerns": [
    "string: concentration risk not obvious from ticker list alone (2–3 entries)"
  ],
  "historical_analogues": [
    "string: historical period where a similar portfolio failed badly (1–2 entries)"
  ],
  "regime_vulnerabilities": [
    "string: specific market regime where this portfolio would underperform most (2 entries)"
  ],
  "single_biggest_risk": "string: the one scenario that would be most damaging"
}}"""


def _load_portfolio_context(
    positions_path: Path | None = None,
    screen_state_path: Path | None = None,
) -> dict:
    """Load current portfolio data for the adversarial prompt."""
    positions_p = positions_path or _POSITIONS_PATH
    state_p = screen_state_path or _SCREEN_STATE

    tickers = []
    if positions_p.exists():
        with open(positions_p) as f:
            data = yaml.safe_load(f) or {}
        tickers = [p["ticker"] for p in data.get("positions", []) if "ticker" in p]

    # Pull themes and factors from exposure module without triggering a fetch
    from .exposure import (
        compute_theme_weights,
        compute_factor_weights,
        THEME_MEMBERSHIP,
        FACTOR_MEMBERSHIP,
    )
    theme_weights = compute_theme_weights(tickers)
    factor_weights = compute_factor_weights(tickers)

    # Build alignment summary from screen state
    alignment_summary = "insufficient_data"
    if state_p.exists():
        with open(state_p) as f:
            state = yaml.safe_load(f) or {}
        entries = state.get("state", [])
        if entries:
            ratings = [e.get("last_rating") for e in entries if e.get("last_rating")]
            strong_buys = ratings.count("STRONG_BUY")
            sells = sum(1 for r in ratings if "SELL" in r)
            alignment_summary = f"{strong_buys} STRONG_BUY, {sells} SELL/STRONG_SELL in universe"

    return {
        "tickers": tickers,
        "themes": {k: f"{v:.1%}" for k, v in theme_weights.items() if v > 0},
        "factors": {k: f"{v:.1%}" for k, v in factor_weights.items() if v > 0.10},
        "alignment_summary": alignment_summary,
    }


def _call_claude(prompt: str) -> Optional[str]:
    """Call Claude Haiku for adversarial critique. Returns raw response text or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text if message.content else None
    except Exception as e:
        return f'{{"error": "Claude call failed: {e}"}}'


def _parse_adversarial_response(raw: str) -> dict:
    """Parse Claude's JSON response. Returns dict with error key on failure."""
    if raw is None:
        return {"error": "no_api_key", "note": "Set ANTHROPIC_API_KEY to enable adversarial review"}

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "json_parse_failed", "raw_response": raw[:500]}


def run_adversarial_review(
    positions_path: Path | None = None,
    screen_state_path: Path | None = None,
    persist: bool = True,
    warnings: list[str] | None = None,
) -> dict:
    """Run adversarial review of the current portfolio.

    Returns a dict with critiques or error information.
    Never modifies any core data files.
    DIAGNOSTIC ONLY.
    """
    context = _load_portfolio_context(positions_path, screen_state_path)

    if not context["tickers"]:
        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "no_positions",
            "critique": None,
            "diagnostic_only": True,
        }
        if persist:
            _persist(result)
        return result

    prompt = _USER_PROMPT_TEMPLATE.format(
        tickers=", ".join(context["tickers"]),
        themes=json.dumps(context["themes"], indent=2),
        factors=json.dumps(context["factors"], indent=2),
        warnings=json.dumps(warnings or [], indent=2),
        alignment_summary=context["alignment_summary"],
    )

    raw = _call_claude(prompt)
    critique = _parse_adversarial_response(raw)

    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "error" if "error" in critique else "ok",
        "tickers_reviewed": context["tickers"],
        "themes_at_review": context["themes"],
        "factors_at_review": context["factors"],
        "critique": critique,
        "diagnostic_only": True,
        "note": "LLM critique only — not investment advice, not price predictions",
    }

    if persist:
        _persist(result)

    return result


def _persist(result: dict) -> None:
    """Append to adversarial_log.jsonl only — never touch core data."""
    _DATA_PATH.mkdir(parents=True, exist_ok=True)
    append_jsonl(_ADVERSARIAL_LOG, result)


def load_latest_adversarial(path: Path | None = None) -> Optional[dict]:
    """Return the most recent adversarial review result, or None."""
    log_path = path or _ADVERSARIAL_LOG
    if not log_path.exists():
        return None
    last = None
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    pass
    return last
