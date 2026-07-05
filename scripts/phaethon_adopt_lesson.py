#!/usr/bin/env python3
"""Human adoption act (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY, step 4).

Records ADOPTED lesson(s) into the journal as ONE WINDOW_BOUNDARY record. This is the
ONLY sanctioned path by which anything learned reaches Phaethon — and only via a NEW
FROZEN PROMPT the operator supplies (this script hashes it; it does NOT generate it).

Enforced in code (not by discipline):
  * change budget: at most CHANGE_BUDGET (2) lessons per boundary event
  * every lesson needs a non-trivial, falsifiable forward prediction
  * refuses entirely if learning is SUSPENDED (kill switch, step 6)

Usage:
  phaethon_adopt_lesson.py --review 2026-07-05 --prompt-file new_prompt.txt --prompt-version 3 \\
     --lesson-id thesis_category:turnaround --forward-prediction "turnaround hit_rate > 0.45" \\
     [--lesson-id ... --forward-prediction ...]   # paired by order, max 2
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.phaethon.journal import append_boundary, DEFAULT_JOURNAL
from src.phaethon.learning_kill_switch import is_suspended

CHANGE_BUDGET = 2
_MIN_PREDICTION_CHARS = 15
_HAS_NUMBER = re.compile(r"\d")
_HAS_COMPARATOR = re.compile(r"(?:<=|>=|<|>)|\b(?:below|under|above|over|less than|greater|exceeds?|rises?|falls?|drops?)\b", re.I)
_KNOWN_METRIC = re.compile(r"override[ _-]?rate|hit[ _-]?rate|median[ _-]?hold|hold[ _-]?days", re.I)


def check_prediction(text: str) -> tuple[str, str]:
    """Return (level, msg): 'ok' | 'weak' | 'trivial'."""
    t = (text or "").strip()
    if len(t) < _MIN_PREDICTION_CHARS or not _HAS_NUMBER.search(t) or not _HAS_COMPARATOR.search(t):
        return "trivial", "forward prediction is trivial — need a measurable, comparable claim (metric, comparator, number)"
    if not _KNOWN_METRIC.search(t):
        return "weak", "prediction has a number/comparator but no recognized metric — refine or pass --confirm-weak"
    return "ok", "ok"


def adopt_lessons(lessons: list[dict], prompt_file: str, prompt_version, review_date: str,
                  journal_path=DEFAULT_JOURNAL, now: datetime | None = None,
                  confirm_weak: bool = False) -> dict:
    """Core (testable). Raises ValueError on any guard breach; returns the boundary record."""
    if is_suspended():
        raise ValueError("LEARNING_SUSPENDED — adoption refused; reverts to calendar-only review")
    if len(lessons) == 0:
        raise ValueError("no lessons supplied")
    if len(lessons) > CHANGE_BUDGET:
        raise ValueError(f"change budget exceeded: {len(lessons)} lessons > cap {CHANGE_BUDGET} per boundary")
    for L in lessons:
        level, msg = check_prediction(L.get("forward_prediction", ""))
        if level == "trivial" or (level == "weak" and not confirm_weak):
            raise ValueError(f"lesson {L.get('lesson_id')}: {msg}")
    p = Path(prompt_file)
    if not p.exists():
        raise ValueError(f"prompt file not found: {prompt_file} (operator must supply the NEW frozen prompt)")
    prompt_hash = hashlib.sha256(p.read_bytes()).hexdigest()
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return append_boundary(prompt_version=prompt_version,
                           lessons_adopted=[{"lesson_id": L["lesson_id"],
                                             "category": L.get("category"), "stance": L.get("stance"),
                                             "forward_prediction": L["forward_prediction"],
                                             "adoption_stats": L.get("adoption_stats", {})} for L in lessons],
                           prompt_hash=prompt_hash, ts=ts, path=journal_path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record a Phaethon boundary lesson adoption (human act).")
    ap.add_argument("--review", required=True)
    ap.add_argument("--prompt-file", required=True, help="the NEW frozen prompt the operator supplies (hashed, not generated)")
    ap.add_argument("--prompt-version", required=True)
    ap.add_argument("--lesson-id", action="append", default=[], required=True)
    ap.add_argument("--forward-prediction", action="append", default=[], required=True,
                    help="mandatory, falsifiable, measurable claim per lesson")
    ap.add_argument("--confirm-weak", action="store_true", help="accept a non-trivial but metric-unrecognized prediction")
    args = ap.parse_args(argv)

    if len(args.lesson_id) != len(args.forward_prediction):
        print("error: --lesson-id and --forward-prediction must be paired 1:1", file=sys.stderr)
        return 2
    lessons = [{"lesson_id": lid, "forward_prediction": fp}
               for lid, fp in zip(args.lesson_id, args.forward_prediction)]
    try:
        rec = adopt_lessons(lessons, args.prompt_file, args.prompt_version, args.review,
                            confirm_weak=args.confirm_weak)
    except ValueError as e:
        print(f"ADOPTION REFUSED: {e}", file=sys.stderr)
        return 1
    print(f"adopted {len(lessons)} lesson(s) → WINDOW_BOUNDARY v{args.prompt_version} "
          f"(prompt_hash {rec['prompt_hash'][:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
