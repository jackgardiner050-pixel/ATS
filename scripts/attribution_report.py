#!/usr/bin/env python3
"""Attribution report — closed-trade outcomes bucketed by entry signals.

Joins data/paper_trades.jsonl on each trade's entry_signals snapshot (attached at
open time by paper_run.py) and reports mean return / mean alpha bucketed by
momentum quintile, revision direction, and confidence tier — always WITH n per
bucket. Buckets with n < 10 print "insufficient data (n<N)" rather than showing a
tiny-sample mean, so a thin book is never dressed up as signal.

Read-only / diagnostic: it reads trade outcomes for display only and is imported
NOWHERE under src/engine or src/signals (enforced by tests/test_no_feedback_imports.py).
It must never feed back into ratings or decision inputs.

Usage:
    python scripts/attribution_report.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.paper_trading import load_trades

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

MIN_N = 10
_DIMENSIONS = [
    ("momentum_quintile", "Momentum quintile"),
    ("revision_direction", "Revision direction"),
    ("confidence_after", "Confidence tier (after signals)"),
]


def bucket_by(trades: list[dict], signal_key: str) -> dict:
    """Group trades by entry_signals[signal_key] → {bucket: {n, mean_return, mean_alpha}}."""
    buckets: dict = defaultdict(list)
    for t in trades:
        sig = t.get("entry_signals") or {}
        buckets[sig.get(signal_key)].append(t)
    out = {}
    for val, ts in buckets.items():
        rets = [x["return_pct"] for x in ts if x.get("return_pct") is not None]
        alphas = [x["alpha"] for x in ts if x.get("alpha") is not None]
        out[val] = {
            "n": len(ts),
            "mean_return": (sum(rets) / len(rets)) if rets else None,
            "mean_alpha": (sum(alphas) / len(alphas)) if alphas else None,
        }
    return out


def render_dimension(label: str, stats: dict, min_n: int = MIN_N) -> list[str]:
    lines = [f"  {label}:"]
    if not stats:
        lines.append("    (no trades with this signal recorded)")
        return lines
    for val, s in sorted(stats.items(), key=lambda kv: str(kv[0])):
        if s["n"] < min_n:
            lines.append(f"    {str(val):<16} n={s['n']:<3} insufficient data (n<{min_n})")
        else:
            lines.append(
                f"    {str(val):<16} n={s['n']:<3} "
                f"mean_return={s['mean_return']*100:+.2f}%  "
                f"mean_alpha={s['mean_alpha']*100:+.2f}%"
            )
    return lines


def build_report(trades: list[dict], min_n: int = MIN_N) -> str:
    lines = ["=" * 70, "  ATTRIBUTION REPORT — closed trades bucketed by entry signal",
             "=" * 70, f"  total closed trades: {len(trades)}"]
    tagged = [t for t in trades if t.get("entry_signals")]
    lines.append(f"  trades with entry_signals: {len(tagged)}")
    if not tagged:
        lines.append("  no entry-tagged trades yet — attribution accrues as Cohort-1 closes.")
        return "\n".join(lines)
    for key, label in _DIMENSIONS:
        lines.append("")
        lines.extend(render_dimension(label, bucket_by(tagged, key), min_n))
    return "\n".join(lines)


def main() -> int:
    trades = load_trades()
    print(build_report(trades))
    return 0


if __name__ == "__main__":
    sys.exit(main())
