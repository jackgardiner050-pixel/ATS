"""Attribution logger — append-only JSONL record of governance decisions.

Captures per-screened-candidate data for longitudinal calibration validation.
Observation only: no feedback loop, no adaptive behavior.

Log location: data/attribution_log.jsonl
Each record is one JSON object per line.
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_LOG = _ROOT / "data" / "attribution_log.jsonl"


def log_screen_decision(
    ticker: str,
    rating: str,
    confidence: str,
    dcf_upside: float | None,
    themes: list[str],
    archetypes: list[str],
    regime: str | None,
    regime_confidence: float | None,
    signals: dict[str, Any] | None = None,
    notes: str | None = None,
    log_path: Path | None = None,
) -> None:
    """Record a single screening decision for later attribution analysis.

    Call this once per ticker whenever it passes or fails the final screen.
    Does not raise — attribution logging must never break the main pipeline.
    """
    record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ticker": ticker,
        "rating": rating,
        "confidence": confidence,
        "dcf_upside": dcf_upside,
        "themes": themes,
        "archetypes": archetypes,
        "regime_at_screen": regime,
        "regime_confidence": regime_confidence,
    }
    if signals:
        record["signals"] = signals
    if notes:
        record["notes"] = notes

    _append(record, log_path or _DEFAULT_LOG)


def log_governance_run(
    regime: str | None,
    regime_confidence: float | None,
    n_positions: int,
    constitution_compliant: bool,
    violations: list[str],
    escalation_triggers: list[str],
    version_dict: dict[str, str] | None = None,
    notes: str | None = None,
    log_path: Path | None = None,
) -> None:
    """Record a governance pipeline run for longitudinal tracking."""
    record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "governance_run",
        "regime": regime,
        "regime_confidence": regime_confidence,
        "n_positions": n_positions,
        "constitution_compliant": constitution_compliant,
        "violations": violations,
        "escalation_triggers": escalation_triggers,
    }
    if version_dict:
        record["version"] = version_dict
    if notes:
        record["notes"] = notes

    _append(record, log_path or _DEFAULT_LOG)


def _append(record: dict[str, Any], log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass  # attribution logging must not break the pipeline
