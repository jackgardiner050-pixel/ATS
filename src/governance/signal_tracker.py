"""Signal Reliability Tracker — rolling effectiveness by signal and regime.

Treats each signal as a temporary hypothesis. Tracks which signals work,
in what environments, and whether reliability is degrading over time.

Signals tracked:
  1. 12m momentum (momentum_quintile from signal_log.jsonl)
  2. EPS revisions (revision_direction)
  3. Cohort outlier flag (confidence_flags in signal_log)
  4. Signal alignment score (from alignment_score field)

Regime conditioning: when regime history is available, compute signal
effectiveness split by leading regime at time of signal.

DIAGNOSTIC ONLY: never modifies signal logic, ratings, or risk rules.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

_SIGNAL_LOG = Path(__file__).parent.parent.parent / "data" / "signal_log.jsonl"
_TRADES_LOG = Path(__file__).parent.parent.parent / "data" / "paper_trades.jsonl"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_REGIME_LOG = _DATA_PATH / "regime_log.jsonl"
_SIGNAL_TRACKER_LOG = _DATA_PATH / "signal_tracker_log.jsonl"

_CONSTITUTION_PATH = Path(__file__).parent.parent.parent / "config" / "constitution.yaml"
_DEFAULT_DECAY_WEEKS = 8
_DEFAULT_MIN_QUALITY = 0.45


def _load_thresholds() -> tuple[int, float]:
    """Load SIGNAL_DECAY_LOOKBACK_WEEKS and MIN_SIGNAL_QUALITY_THRESHOLD."""
    if _CONSTITUTION_PATH.exists():
        import yaml
        with open(_CONSTITUTION_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return (
            int(cfg.get("SIGNAL_DECAY_LOOKBACK_WEEKS", _DEFAULT_DECAY_WEEKS)),
            float(cfg.get("MIN_SIGNAL_QUALITY_THRESHOLD", _DEFAULT_MIN_QUALITY)),
        )
    return _DEFAULT_DECAY_WEEKS, _DEFAULT_MIN_QUALITY


def _load_signal_log(path: Path | None = None) -> list[dict]:
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


def _load_closed_trades(path: Path | None = None) -> list[dict]:
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


def _parse_alignment(alignment_score: str) -> tuple[int, int]:
    """Parse '+2 aligned, -1 contradicted' → (aligned_count, contradicting_count)."""
    aligned = 0
    contradicting = 0
    try:
        parts = alignment_score.split(",")
        for part in parts:
            part = part.strip()
            if "aligned" in part:
                aligned = abs(int(part.split()[0]))
            elif "contradicted" in part:
                contradicting = abs(int(part.split()[0]))
    except (ValueError, IndexError):
        pass
    return aligned, contradicting


def compute_momentum_signal_stats(signal_entries: list[dict]) -> dict:
    """Analyse 12m momentum signal: how often does Q1 momentum support a bullish rating?

    'Quality' = fraction of Q1 entries where rating is STRONG_BUY or BUY
               + fraction of Q5 entries where rating is SELL or STRONG_SELL.
    This measures whether the momentum signal is internally consistent with ratings.
    As performance history accumulates, this can be replaced with return-based quality.
    """
    q1_entries = [e for e in signal_entries if e.get("momentum_quintile") == 1]
    q5_entries = [e for e in signal_entries if e.get("momentum_quintile") == 5]

    n_q1 = len(q1_entries)
    n_q5 = len(q5_entries)

    if n_q1 + n_q5 == 0:
        return {
            "signal": "12m_momentum",
            "status": "no_data",
            "n_q1": 0,
            "n_q5": 0,
            "overall_quality": None,
            "decay_warning": False,
            "instability_score": None,
        }

    # Q1 aligned with bullish rating
    q1_consistent = sum(
        1 for e in q1_entries if e.get("rating") in ("STRONG_BUY", "BUY")
    )
    # Q5 aligned with bearish rating
    q5_consistent = sum(
        1 for e in q5_entries if e.get("rating") in ("SELL", "STRONG_SELL")
    )

    total_directional = n_q1 + n_q5
    total_consistent = q1_consistent + q5_consistent
    overall_quality = total_consistent / total_directional if total_directional > 0 else None

    # Q1 used as bullish confirmation but rating is bearish = contradiction
    q1_contradictions = sum(
        1 for e in q1_entries if e.get("rating") in ("SELL", "STRONG_SELL")
    )
    instability = q1_contradictions / n_q1 if n_q1 > 0 else 0.0

    _, min_quality = _load_thresholds()
    decay_warning = overall_quality is not None and overall_quality < min_quality

    return {
        "signal": "12m_momentum",
        "status": "computed",
        "n_q1": n_q1,
        "n_q5": n_q5,
        "n_q1_consistent": q1_consistent,
        "n_q5_consistent": q5_consistent,
        "overall_quality": round(overall_quality, 4) if overall_quality is not None else None,
        "instability_score": round(instability, 4),
        "decay_warning": decay_warning,
    }


def compute_revision_signal_stats(signal_entries: list[dict]) -> dict:
    """Analyse EPS revision signal: how often does POSITIVE revision support bullish rating?"""
    positive_entries = [e for e in signal_entries if e.get("revision_direction") == "POSITIVE"]
    negative_entries = [e for e in signal_entries if e.get("revision_direction") == "NEGATIVE"]

    n_pos = len(positive_entries)
    n_neg = len(negative_entries)

    if n_pos + n_neg == 0:
        return {
            "signal": "eps_revisions",
            "status": "no_directional_data",
            "n_positive": 0,
            "n_negative": 0,
            "overall_quality": None,
            "decay_warning": False,
            "instability_score": None,
        }

    pos_consistent = sum(
        1 for e in positive_entries if e.get("rating") in ("STRONG_BUY", "BUY")
    )
    neg_consistent = sum(
        1 for e in negative_entries if e.get("rating") in ("SELL", "STRONG_SELL")
    )

    total = n_pos + n_neg
    total_consistent = pos_consistent + neg_consistent
    overall_quality = total_consistent / total if total > 0 else None

    pos_contradictions = sum(
        1 for e in positive_entries if e.get("rating") in ("SELL", "STRONG_SELL")
    )
    instability = pos_contradictions / n_pos if n_pos > 0 else 0.0

    _, min_quality = _load_thresholds()
    decay_warning = overall_quality is not None and overall_quality < min_quality

    return {
        "signal": "eps_revisions",
        "status": "computed",
        "n_positive": n_pos,
        "n_negative": n_neg,
        "n_pos_consistent": pos_consistent,
        "n_neg_consistent": neg_consistent,
        "overall_quality": round(overall_quality, 4) if overall_quality is not None else None,
        "instability_score": round(instability, 4),
        "decay_warning": decay_warning,
    }


def compute_alignment_effectiveness(signal_entries: list[dict]) -> dict:
    """Analyse signal alignment: does having 2+ aligned signals predict well?

    'Quality' here = fraction of high-alignment (2+ aligned) entries that
    maintained their confidence tier (didn't get bumped back down next week).
    With only one day of data, this is structural analysis only.
    """
    high_alignment = [
        e for e in signal_entries
        if _parse_alignment(e.get("alignment_score", ""))[0] >= 2
    ]
    zero_alignment = [
        e for e in signal_entries
        if _parse_alignment(e.get("alignment_score", ""))[0] == 0
        and _parse_alignment(e.get("alignment_score", ""))[1] == 0
    ]

    return {
        "signal": "signal_alignment",
        "status": "structural_analysis",
        "n_high_alignment": len(high_alignment),
        "n_zero_alignment": len(zero_alignment),
        "high_alignment_ratings": _count_ratings(high_alignment),
        "zero_alignment_ratings": _count_ratings(zero_alignment),
        "note": "Return-based effectiveness requires closed trade history",
    }


def compute_cohort_outlier_stats(signal_entries: list[dict]) -> dict:
    """Analyse cohort outlier flag: how many tickers have outlier-capped confidence?

    A high fraction of cohort outliers in STRONG_BUY ratings suggests the model
    is rating too many over-valued (vs peers) names as buys.
    """
    strong_buys = [e for e in signal_entries if e.get("rating") == "STRONG_BUY"]
    sb_low_confidence = [
        e for e in strong_buys if e.get("confidence_after") == "LOW"
    ]

    total_tickers = len(set(e.get("ticker") for e in signal_entries))
    sb_low_frac = len(sb_low_confidence) / len(strong_buys) if strong_buys else 0.0

    warning = sb_low_frac > 0.30  # warn if >30% of STRONG_BUYs are LOW confidence

    return {
        "signal": "cohort_outlier_flag",
        "status": "computed",
        "total_tickers": total_tickers,
        "strong_buy_count": len(strong_buys),
        "strong_buy_low_confidence": len(sb_low_confidence),
        "sb_low_confidence_fraction": round(sb_low_frac, 4),
        "instability_warning": warning,
        "note": "High LOW-confidence STRONG_BUY fraction suggests model-market divergence",
    }


def _count_ratings(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        r = e.get("rating", "UNKNOWN")
        counts[r] = counts.get(r, 0) + 1
    return counts


def run_signal_tracker(
    signal_log_path: Path | None = None,
    persist: bool = True,
) -> dict:
    """Run full signal reliability analysis. Returns diagnostic dict."""
    signal_entries = _load_signal_log(signal_log_path)

    momentum_stats = compute_momentum_signal_stats(signal_entries)
    revision_stats = compute_revision_signal_stats(signal_entries)
    alignment_stats = compute_alignment_effectiveness(signal_entries)
    outlier_stats = compute_cohort_outlier_stats(signal_entries)

    any_decay = any(
        s.get("decay_warning", False)
        for s in [momentum_stats, revision_stats]
    )

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "n_signal_entries": len(signal_entries),
        "any_decay_warning": any_decay,
        "signals": {
            "momentum_12m": momentum_stats,
            "eps_revisions": revision_stats,
            "signal_alignment": alignment_stats,
            "cohort_outlier": outlier_stats,
        },
        "diagnostic_only": True,
    }

    if persist:
        _DATA_PATH.mkdir(parents=True, exist_ok=True)
        with open(_SIGNAL_TRACKER_LOG, "a") as f:
            f.write(json.dumps(result) + "\n")

    return result
