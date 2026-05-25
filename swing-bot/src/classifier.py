"""Phase B: Haiku classifier for 8-K filing text.

Used for EXACTLY ONE task: classifying 8-K text into a category.
The classification result informs the entry filter — it never directly
instructs a trade. Hard rule: LLM never invents numbers.

Cost cap: fail loudly if monthly Anthropic spend exceeds £5 (≈ $6.35).
Approx cost: £0.001 per call → 5000 calls/month budget (far more than needed).

Output schema (strict JSON):
  {"category": str, "material": bool, "confidence": float}

Categories: "M&A" | "FDA" | "earnings" | "executive_change" | "Reg_FD" | "other"
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_COST_LOG_PATH = Path(__file__).parent.parent / "data" / "llm_cost_log.jsonl"
_MONTHLY_CAP_GBP = 5.0
_HAIKU_COST_PER_1K_INPUT_USD = 0.0008    # claude-haiku-4-5 approximate
_HAIKU_COST_PER_1K_OUTPUT_USD = 0.004
_GBPUSD = 1.27  # approximate; used only for cap enforcement

_SYSTEM_PROMPT = """You are a financial document classifier. Your only job is to classify
SEC 8-K filing text into one of the specified categories.

Respond with ONLY a JSON object in this exact schema:
{"category": "M&A" | "FDA" | "earnings" | "executive_change" | "Reg_FD" | "other",
 "material": true | false,
 "confidence": 0.0 to 1.0}

Rules:
- category: choose the single best-fit category
- material: true if this event is likely to move the stock price ≥2%
- confidence: your confidence in this classification (0.0 = uncertain, 1.0 = certain)
- Never output anything except the JSON object
- Never invent or assume data not present in the provided text"""


def classify_8k(
    text: str,
    item_codes: list[str],
    model: str = "claude-haiku-4-5-20251001",
    max_input_chars: int = 5000,
) -> Optional[dict]:
    """Classify an 8-K filing using Haiku. Returns None if disabled or on failure.

    Hard rules enforced here:
    - monthly cost cap checked before every call
    - output strictly validated against expected schema
    - never called for non-8K tasks
    """
    if not _is_enabled():
        log.debug("Haiku classifier disabled (Phase A) — skipping")
        return None

    if _monthly_cost_exceeded():
        log.error(
            "HARD COST CAP REACHED: monthly LLM spend ≥ £%.1f. "
            "No further Haiku calls until next month. Fix: check data/llm_cost_log.jsonl",
            _MONTHLY_CAP_GBP,
        )
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — classifier disabled")
        return None

    truncated_text = text[:max_input_chars]
    items_str = ", ".join(item_codes) if item_codes else "unknown"
    user_content = (
        f"8-K filing items: {items_str}\n\n"
        f"Filing text (first {len(truncated_text)} chars):\n{truncated_text}"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=128,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)

        # Validate schema
        assert "category" in result and isinstance(result["category"], str)
        assert "material" in result and isinstance(result["material"], bool)
        assert "confidence" in result and 0.0 <= float(result["confidence"]) <= 1.0

        _log_cost(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return result

    except json.JSONDecodeError as exc:
        log.warning("Haiku returned invalid JSON: %s", exc)
        return None
    except AssertionError:
        log.warning("Haiku output failed schema validation")
        return None
    except Exception as exc:
        log.warning("Haiku API call failed: %s", exc)
        return None


def _is_enabled() -> bool:
    """Read from settings.yaml whether Phase B is enabled."""
    try:
        import yaml
        cfg_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("llm", {}).get("enabled", False)
    except Exception:
        return False


def _monthly_cost_exceeded() -> bool:
    """Return True if this month's LLM spend has reached the cap."""
    if not _COST_LOG_PATH.exists():
        return False
    this_month = date.today().strftime("%Y-%m")
    total_gbp = 0.0
    with open(_COST_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("month") == this_month:
                    total_gbp += float(entry.get("cost_gbp", 0))
            except (json.JSONDecodeError, KeyError):
                pass
    return total_gbp >= _MONTHLY_CAP_GBP


def _log_cost(input_tokens: int, output_tokens: int) -> None:
    """Append a cost record to the monthly log."""
    cost_usd = (
        input_tokens / 1000 * _HAIKU_COST_PER_1K_INPUT_USD
        + output_tokens / 1000 * _HAIKU_COST_PER_1K_OUTPUT_USD
    )
    cost_gbp = cost_usd / _GBPUSD
    _COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "date": date.today().isoformat(),
        "month": date.today().strftime("%Y-%m"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
        "cost_gbp": round(cost_gbp, 6),
    }
    with open(_COST_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
