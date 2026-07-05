#!/usr/bin/env python3
"""Human-facing review artifact (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY, step 3).

Renders runs/phaethon/review_<date>.md for the OPERATOR to read and manually decide
adoption. This script adopts nothing and never touches Phaethon's prompt/context.

Runs only when is_review_eligible() is true, or with --force to preview early (clearly
labeled PREVIEW — not yet eligible, informational only).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.phaethon.journal import read_journal, boundaries, exits_since_last_boundary, DEFAULT_JOURNAL
from src.phaethon.review_trigger import is_review_eligible
from src.phaethon.lessons_ledger import generate_candidate_lessons
from src.phaethon.prediction_resolution import resolve_boundary_predictions
from src.phaethon.learning_kill_switch import is_suspended

_ROOT = Path(__file__).resolve().parent.parent


def render_report(records: list[dict], now: datetime | None = None, preview: bool = False) -> str:
    now = now or datetime.now(timezone.utc)
    eligible, closed, weeks, reason = is_review_eligible(records, now=now)
    candidates = generate_candidate_lessons(records, write=False, now=now)
    exits, _ = exits_since_last_boundary(records)
    bs = boundaries(records)
    L = []
    hdr = "PREVIEW — not yet eligible, informational only" if (preview and not eligible) else "Phaethon Boundary Review"
    L += [f"# {hdr} — {now.date().isoformat()}", ""]
    if is_suspended():
        L += ["> ⛔ **LEARNING SUSPENDED** (kill switch fired) — ledger continues observation-only; "
              "adoption is blocked. Reverting to calendar-only review.", ""]
    L += [f"**Eligibility:** {reason}",
          f"({closed} closed since last boundary, {weeks} weeks elapsed)", ""]

    L += ["## Candidate lessons (with arithmetic — adopt via phaethon_adopt_lesson.py)", ""]
    for c in candidates:
        mark = "✅ ADOPTABLE" if c["adoptable"] else "⏸ " + c["status"]
        L += [f"### `{c['lesson_id']}` — {mark}",
              f"- level: {c['level']} · bucket: {c['bucket']} · **n={c['n']}**",
              f"- {c['claim']}",
              f"- statistic: `{c['statistic']}` (test: {c['test']})", ""]

    L += ["## Prior boundary's forward predictions — did they resolve?", ""]
    if bs:
        res = resolve_boundary_predictions(bs[-1], exits)
        if res:
            for r in res:
                L += [f"- `{r.get('lesson_id')}` → **{r['resolution']}** — {r.get('note','')}",
                      f"  (predicted: {r.get('forward_prediction')!r})"]
        else:
            L += ["- prior boundary adopted no lessons"]
    else:
        L += ["- no prior boundary (first review)"]
    L += [""]

    L += ["## Prompt version & lesson history", ""]
    if bs:
        for b in bs:
            ids = ", ".join(l.get("lesson_id", "?") for l in b.get("lessons_adopted", []))
            L += [f"- v{b.get('prompt_version')} @ {b.get('ts')} — lessons: {ids or '(none)'} "
                  f"— prompt_hash {str(b.get('prompt_hash',''))[:12]}…"]
    else:
        L += ["- no boundaries yet"]
    L += ["", "---", "*Human-side artifact. Adoption is a human act (step 4). Nothing here reaches "
          "Phaethon's context — NO_LIVE_PNL_LEARNING.*"]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render the Phaethon boundary-review report (human-facing).")
    ap.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    ap.add_argument("--force", action="store_true", help="preview even when not eligible (labeled PREVIEW)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    records = read_journal(args.journal)
    now = datetime.now(timezone.utc)
    eligible, *_ = is_review_eligible(records, now=now)
    if not eligible and not args.force:
        print("not eligible for review — rerun with --force to preview (labeled PREVIEW)", file=sys.stderr)
        return 1
    report = render_report(records, now=now, preview=not eligible)
    out = Path(args.out) if args.out else _ROOT / "runs" / "phaethon" / f"review_{now.date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
