"""Confidence Calibration Engine — empirical confidence tier performance analysis.

Evaluates whether HIGH confidence historically behaves differently from LOW confidence.
Reads from signal_log.jsonl and paper_trades.jsonl to build calibration evidence.

Critical: this engine is DIAGNOSTIC ONLY.
  - Never self-modifies live ratings
  - Never adjusts capital autonomously
  - Never mutates risk rules
  - Write path: calibration_log.jsonl (separate from core data)

Early-life note: with < MIN_OBSERVATIONS_FOR_CALIBRATION closed trades, most
metrics will report "insufficient_data" rather than fabricate numbers. The
infrastructure is here to accumulate evidence over time.
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path

from src.io_utils import append_jsonl

import yaml

_SIGNAL_LOG = Path(__file__).parent.parent.parent / "data" / "signal_log.jsonl"
_TRADES_LOG = Path(__file__).parent.parent.parent / "data" / "paper_trades.jsonl"
_POSITIONS_PATH = Path(__file__).parent.parent.parent / "data" / "paper_positions.yaml"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_CALIB_LOG = _DATA_PATH / "calibration_log.jsonl"

_CONSTITUTION_PATH = Path(__file__).parent.parent.parent / "config" / "constitution.yaml"
_DEFAULT_MIN_OBS = 20


def _load_min_observations() -> int:
    if _CONSTITUTION_PATH.exists():
        with open(_CONSTITUTION_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return int(cfg.get("MIN_OBSERVATIONS_FOR_CALIBRATION", _DEFAULT_MIN_OBS))
    return _DEFAULT_MIN_OBS


def load_signal_log(path: Path | None = None) -> list[dict]:
    """Load all signal log entries."""
    p = path or _SIGNAL_LOG
    if not p.exists():
        return []
    entries = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def load_closed_trades(path: Path | None = None) -> list[dict]:
    """Load all closed paper trades."""
    p = path or _TRADES_LOG
    if not p.exists():
        return []
    trades = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return trades


def compute_confidence_distribution(signal_entries: list[dict]) -> dict[str, int]:
    """Count signal log entries by confidence tier (after escalation)."""
    counts: dict[str, int] = {}
    for e in signal_entries:
        tier = e.get("confidence_after", "UNKNOWN")
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def compute_tier_performance(
    closed_trades: list[dict],
    min_observations: int,
) -> dict[str, dict]:
    """Compute per-confidence-tier performance statistics from closed trades.

    Returns {tier: {count, avg_return, avg_excess_return_vs_spy, avg_days_held,
                    win_rate, max_drawdown, status}}
    """
    by_tier: dict[str, list[dict]] = {}
    for trade in closed_trades:
        tier = trade.get("entry_confidence", "UNKNOWN")
        by_tier.setdefault(tier, []).append(trade)

    result = {}
    for tier, trades in by_tier.items():
        n = len(trades)
        if n < min_observations:
            result[tier] = {
                "count": n,
                "status": f"insufficient_data (need {min_observations}, have {n})",
                "avg_return": None,
                "avg_excess_return_vs_spy": None,
                "win_rate": None,
                "max_drawdown": None,
            }
            continue

        returns = [t.get("return_pct", 0.0) / 100 for t in trades if "return_pct" in t]
        spy_returns = []
        for t in trades:
            entry_spy = t.get("spy_entry_price")
            exit_spy = t.get("spy_exit_price")
            if entry_spy and exit_spy and entry_spy > 0:
                spy_returns.append(exit_spy / entry_spy - 1)

        avg_ret = sum(returns) / len(returns) if returns else None
        avg_spy = sum(spy_returns) / len(spy_returns) if spy_returns else None
        avg_excess = (avg_ret - avg_spy) if (avg_ret is not None and avg_spy is not None) else None

        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else None

        max_dd = min(returns) if returns else None

        days_held_list = [t.get("days_held") for t in trades if t.get("days_held") is not None]
        avg_days = sum(days_held_list) / len(days_held_list) if days_held_list else None

        result[tier] = {
            "count": n,
            "status": "calibrated",
            "avg_return": round(avg_ret, 4) if avg_ret is not None else None,
            "avg_excess_return_vs_spy": round(avg_excess, 4) if avg_excess is not None else None,
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "max_drawdown": round(max_dd, 4) if max_dd is not None else None,
            "avg_days_held": round(avg_days, 1) if avg_days is not None else None,
        }
    return result


def compute_contradiction_rate(signal_entries: list[dict]) -> dict:
    """Measure how often confidence and rating alignment are contradictory.

    A contradictory state: HIGH confidence + 2+ contradicting signals,
    or LOW confidence + strong rating (STRONG_BUY).
    These suggest the model is internally inconsistent.
    """
    total = len(signal_entries)
    if total == 0:
        return {"total": 0, "contradictions": 0, "rate": None, "status": "no_data"}

    contradictions = 0
    for e in signal_entries:
        tier = e.get("confidence_after", "")
        rating = e.get("rating", "")
        alignment = e.get("alignment_score", "")

        # Parse alignment score "+0 aligned, -2 contradicted"
        contradicting_count = 0
        if "contradicted" in alignment:
            try:
                part = alignment.split(",")[-1].strip()
                contradicting_count = abs(int(part.split()[0]))
            except (ValueError, IndexError):
                pass

        # Contradictory state: HIGH confidence but 2+ signals contradict
        if tier == "HIGH" and contradicting_count >= 2:
            contradictions += 1
        # LOW confidence STRONG_BUY with aligned signals — under-confident or calibration error
        elif tier == "LOW" and rating == "STRONG_BUY" and "2 aligned" in alignment:
            contradictions += 1

    return {
        "total": total,
        "contradictions": contradictions,
        "rate": round(contradictions / total, 4),
        "status": "computed",
    }


def run_calibration(
    signal_log_path: Path | None = None,
    trades_path: Path | None = None,
    persist: bool = True,
) -> dict:
    """Run full calibration analysis. Returns diagnostic dict.

    Diagnostic only — never modifies any core data files.
    """
    min_obs = _load_min_observations()
    signal_entries = load_signal_log(signal_log_path)
    closed_trades = load_closed_trades(trades_path)

    confidence_distribution = compute_confidence_distribution(signal_entries)
    tier_performance = compute_tier_performance(closed_trades, min_obs)
    contradiction_report = compute_contradiction_rate(signal_entries)

    total_tickers = len(set(e.get("ticker") for e in signal_entries))
    total_closed = len(closed_trades)

    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_signal_entries": len(signal_entries),
        "total_unique_tickers": total_tickers,
        "total_closed_trades": total_closed,
        "min_observations_required": min_obs,
        "calibration_ready": total_closed >= min_obs,
        "confidence_distribution": confidence_distribution,
        "tier_performance": tier_performance,
        "contradiction_report": contradiction_report,
        "diagnostic_only": True,
    }

    if persist:
        _DATA_PATH.mkdir(parents=True, exist_ok=True)
        append_jsonl(_CALIB_LOG, result)

    return result
