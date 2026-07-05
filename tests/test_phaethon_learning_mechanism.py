"""Adoption change-budget, forward-prediction resolution, and the learning kill switch."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.phaethon_adopt_lesson import adopt_lessons, check_prediction, CHANGE_BUDGET
from src.phaethon.journal import read_journal, boundaries
from src.phaethon.prediction_resolution import resolve_prediction, TRUE, FALSE, AMBIGUOUS
from src.phaethon.learning_kill_switch import (
    check_kill_criterion, maybe_suspend, is_suspended, clear_suspension,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prompt(tmp_path):
    p = tmp_path / "new_prompt.txt"
    p.write_text("frozen prompt v-next")
    return str(p)


def _lesson(i, pred="override_rate < 20%"):
    return {"lesson_id": f"L{i}", "category": "cat", "stance": "reduce", "forward_prediction": pred}


# ─── step 4: change budget (2) + non-triviality ──────────────────────────────

def test_two_lessons_adopts_ok(tmp_path):
    j = tmp_path / "journal.jsonl"
    rec = adopt_lessons([_lesson(1), _lesson(2)], _prompt(tmp_path), 3, "2026-07-05",
                        journal_path=j, now=BASE)
    assert rec["event"] == "WINDOW_BOUNDARY" and len(rec["lessons_adopted"]) == 2
    assert len(boundaries(read_journal(j))) == 1
    print(f"  ✓ 2 lessons (== budget {CHANGE_BUDGET}) adopted → one WINDOW_BOUNDARY")


def test_three_lessons_refused(tmp_path):
    with pytest.raises(ValueError, match="change budget exceeded"):
        adopt_lessons([_lesson(1), _lesson(2), _lesson(3)], _prompt(tmp_path), 3, "2026-07-05",
                      journal_path=tmp_path / "j.jsonl", now=BASE)
    print("  ✓ 3-lesson adoption refused by the hard cap")


def test_trivial_prediction_refused(tmp_path):
    assert check_prediction("it will improve")[0] == "trivial"
    assert check_prediction("override_rate < 20%")[0] == "ok"
    with pytest.raises(ValueError):
        adopt_lessons([_lesson(1, pred="it will improve")], _prompt(tmp_path), 3, "2026-07-05",
                      journal_path=tmp_path / "j.jsonl", now=BASE)
    print("  ✓ trivial forward prediction refused; measurable one accepted")


# ─── step 5: forward-prediction resolution ───────────────────────────────────

def _exits(n_override, n_total):
    out = []
    for i in range(n_total):
        r = {"event": "EXIT", "outcome": "win" if i % 2 else "loss", "hold_days": 10}
        if i < n_override:
            r["override_direction"] = "hold"
        out.append(r)
    return out


def test_prediction_resolves_true_false_ambiguous():
    exits = _exits(2, 10)                       # override_rate = 0.2
    assert resolve_prediction("override_rate < 0.5", exits)["resolution"] == TRUE
    assert resolve_prediction("override_rate > 0.5", exits)["resolution"] == FALSE
    assert resolve_prediction("it will get better", exits)["resolution"] == AMBIGUOUS
    print("  ✓ prediction resolves TRUE / FALSE / AMBIGUOUS(defect)")


# ─── step 6: kill switch ─────────────────────────────────────────────────────

def _cycle(resolutions=(), adopted=()):
    return {"resolutions": [{"resolution": r} for r in resolutions], "adopted": list(adopted)}


def test_kill_fires_on_half_false():
    cycles = [_cycle([TRUE]), _cycle([FALSE]), _cycle([TRUE]), _cycle([FALSE])]   # 2/4 FALSE
    fired, diag = check_kill_criterion(cycles)
    assert fired and "50%" in diag
    print("  ✓ 2/4 false → fires")


def test_kill_does_not_fire_on_quarter_false():
    cycles = [_cycle([TRUE]), _cycle([TRUE]), _cycle([TRUE]), _cycle([FALSE])]    # 1/4 FALSE
    assert check_kill_criterion(cycles)[0] is False
    print("  ✓ 1/4 false → does not fire")


def test_kill_fires_on_oscillation():
    # adopt A, adopt not-A, adopt A again on the same category across 3 boundaries
    cycles = [_cycle(adopted=[{"category": "turnaround", "stance": "A"}]),
              _cycle(adopted=[{"category": "turnaround", "stance": "B"}]),
              _cycle(adopted=[{"category": "turnaround", "stance": "A"}])]
    fired, diag = check_kill_criterion(cycles)
    assert fired and "oscillation" in diag
    print("  ✓ A→B→A oscillation → fires")


def test_suspend_and_reinstatement_ceremony(tmp_path):
    sentinel = tmp_path / "LEARNING_SUSPENDED"
    cycles = [_cycle([FALSE]), _cycle([FALSE]), _cycle([TRUE]), _cycle([FALSE])]
    fired, _ = maybe_suspend(cycles, sentinel=sentinel)
    assert fired and is_suspended(sentinel)
    # silent reinstatement refused
    assert clear_suspension(tmp_path / "nope.md", sentinel=sentinel)[0] is False
    thin = tmp_path / "LEARNING_REINSTATEMENT_2026-08-01.md"; thin.write_text("ok")
    assert clear_suspension(thin, sentinel=sentinel)[0] is False           # too thin
    good = tmp_path / "LEARNING_REINSTATEMENT_2026-08-02.md"
    good.write_text("Diagnosis of the false-prediction cluster and the corrective change. " * 6)
    ok, _ = clear_suspension(good, sentinel=sentinel)
    assert ok and not is_suspended(sentinel)
    print("  ✓ suspend writes sentinel; reinstatement requires a non-trivial diagnosis doc")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
