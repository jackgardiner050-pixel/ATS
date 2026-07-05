"""Tests for the rating-distribution governor (PART D) — diagnostic only.

The warning firing on the CURRENT live distribution is a FEATURE, not a bug to
be fixed by loosening the thresholds.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.constitution import (
    check_rating_distribution,
    compute_rating_distribution,
    run_all_checks,
)

ROOT = Path(__file__).parent.parent
# Empty constitution → code defaults (0.20 SB, 0.35 tail) are used.
CFG = {}


def test_17_of_60_strong_buy_triggers_both_warnings():
    counts = {"STRONG_BUY": 17, "BUY": 3, "HOLD": 12, "SELL": 8, "STRONG_SELL": 20}
    warns = check_rating_distribution(counts, CFG)
    assert len(warns) == 2, warns          # SB fraction AND extreme-tail
    assert any("STRONG_BUY" in w for w in warns)
    assert any("extreme-tail" in w for w in warns)
    print("  ✓ 17/60 STRONG_BUY (tail-heavy) triggers both warnings")


def test_5_of_60_triggers_neither():
    counts = {"STRONG_BUY": 5, "BUY": 3, "HOLD": 49, "SELL": 0, "STRONG_SELL": 3}
    assert check_rating_distribution(counts, CFG) == []
    print("  ✓ 5/60 STRONG_BUY, small tail → no warnings")


def test_zero_rated_no_division_error():
    assert check_rating_distribution({}, CFG) == []
    assert check_rating_distribution({"ERROR": 5, "EXCLUDED": 3}, CFG) == []
    print("  ✓ zero rated → no warnings, no ZeroDivisionError")


def test_accepts_list_of_ratings():
    ratings = ["STRONG_BUY"] * 17 + ["BUY"] * 3 + ["HOLD"] * 12 + ["SELL"] * 8 + ["STRONG_SELL"] * 20
    assert len(check_rating_distribution(ratings, CFG)) == 2
    print("  ✓ accepts an iterable of rating strings")


def test_compute_distribution_fractions():
    d = compute_rating_distribution({"STRONG_BUY": 17, "HOLD": 23, "STRONG_SELL": 20})
    assert d["total"] == 60
    assert abs(d["strong_buy_fraction"] - 17 / 60) < 1e-9
    assert abs(d["extreme_tail_fraction"] - 37 / 60) < 1e-9
    print("  ✓ compute_rating_distribution fractions correct")


def test_run_all_checks_surfaces_rating_warnings():
    report = run_all_checks(
        position_weights={}, theme_weights={}, factor_weights={},
        confidence_counts={},
        rating_counts={"STRONG_BUY": 17, "BUY": 3, "HOLD": 12, "SELL": 8, "STRONG_SELL": 20},
    )
    assert any("Rating distribution" in w for w in report.warnings)
    print("  ✓ run_all_checks surfaces rating-distribution warnings")


def test_integration_current_status_txt_warning_fires():
    """The real, current STATUS.txt distribution MUST trigger a warning (feature)."""
    text = (ROOT / "STATUS.txt").read_text()
    m = re.search(r"SB=(\d+)\s+B=(\d+)\s+H=(\d+)\s+S=(\d+)\s+SS=(\d+)", text)
    assert m, "could not parse Distribution line from STATUS.txt"
    sb, b, h, s, ss = map(int, m.groups())
    counts = {"STRONG_BUY": sb, "BUY": b, "HOLD": h, "SELL": s, "STRONG_SELL": ss}
    warns = check_rating_distribution(counts, CFG)
    assert warns, "current STATUS.txt distribution should trigger a warning — it did not"
    print(f"  ✓ live STATUS.txt distribution fires {len(warns)} warning(s) (expected)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All rating-distribution tests passed.")
