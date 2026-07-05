"""review_trigger: both floors (>=25 closed AND >=13 weeks) required."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.phaethon.review_trigger import is_review_eligible

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def ex(day):
    return {"ts": (BASE + timedelta(days=day)).isoformat(), "event": "EXIT", "outcome": "loss"}


def boundary(day):
    return {"ts": (BASE + timedelta(days=day)).isoformat(), "event": "WINDOW_BOUNDARY",
            "prompt_version": 1, "lessons_adopted": [], "prompt_hash": "x"}


def test_exactly_25_and_13wk_eligible():
    recs = [boundary(0)] + [ex(1 + i) for i in range(25)]
    elig, closed, weeks, _ = is_review_eligible(recs, now=BASE + timedelta(weeks=13))
    assert elig and closed == 25 and weeks >= 13
    print("  ✓ 25 closed & 13wk → eligible")


def test_24_trades_20wk_not_eligible():
    recs = [boundary(0)] + [ex(1 + i) for i in range(24)]
    elig, closed, weeks, _ = is_review_eligible(recs, now=BASE + timedelta(weeks=20))
    assert not elig and closed == 24 and weeks >= 13   # calendar met, count fails
    print("  ✓ 24 trades / 20wk → not eligible (count floor)")


def test_30_trades_10wk_not_eligible():
    recs = [boundary(0)] + [ex(1 + i) for i in range(30)]
    elig, closed, weeks, _ = is_review_eligible(recs, now=BASE + timedelta(weeks=10))
    assert not elig and closed == 30 and weeks < 13    # count met, calendar fails
    print("  ✓ 30 trades / 10wk → not eligible (calendar floor)")


def test_first_ever_review_from_inception():
    recs = [ex(i) for i in range(25)]                  # no boundary; inception = day 0
    assert is_review_eligible(recs, now=BASE + timedelta(weeks=13))[0] is True
    assert is_review_eligible(recs, now=BASE + timedelta(weeks=8))[0] is False   # not until floors met
    print("  ✓ first-ever review: eligible once both floors met from inception")


def test_empty_journal_not_eligible():
    assert is_review_eligible([], now=BASE)[0] is False
    print("  ✓ empty journal → not eligible")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("review_trigger tests passed.")
