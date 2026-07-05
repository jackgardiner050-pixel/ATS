"""lessons_ledger: the 30-trade / 3-category adoptable-vs-carried-forward split at the bar."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.phaethon.lessons_ledger import generate_candidate_lessons, min_observations
from src.research.registry import verify_chain

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = BASE + timedelta(weeks=20)


def ex(day, cat=None, outcome="loss", **kw):
    r = {"ts": (BASE + timedelta(days=day)).isoformat(), "event": "EXIT", "outcome": outcome}
    if cat:
        r["thesis_category"] = cat
    r.update(kw)
    return r


def _30_trades_3_categories():
    recs = []
    # capacity: n=22, 3 wins → extreme vs 50%, n>=20 → ADOPTABLE
    recs += [ex(1 + i, "capacity", "win" if i < 3 else "loss") for i in range(22)]
    # turnaround: n=5 → below MIN_OBSERVATIONS → carried forward
    recs += [ex(30 + i, "turnaround", "win" if i < 2 else "loss") for i in range(5)]
    # momentum: n=3 → carried forward
    recs += [ex(40 + i, "momentum", "win" if i < 1 else "loss") for i in range(3)]
    return recs


def test_min_observations_reused_from_constitution():
    assert min_observations() == 20     # NOT a new magic number


def test_30_trade_split_is_correct_at_the_bar():
    cands = {c["lesson_id"]: c for c in generate_candidate_lessons(_30_trades_3_categories(),
                                                                   write=False, now=NOW)}
    cap = cands["thesis_category:capacity"]
    assert cap["n"] == 22 and cap["adoptable"] is True and cap["status"] == "adoptable"
    assert cap["statistic"]["p_value"] < 0.05
    for cat, n in (("turnaround", 5), ("momentum", 3)):
        c = cands[f"thesis_category:{cat}"]
        assert c["n"] == n and c["adoptable"] is False
        assert c["status"] == "candidate — insufficient n, carried forward"
    print("  ✓ 30/3-category → capacity ADOPTABLE, turnaround+momentum carried forward")


def test_insufficient_n_never_silently_dropped():
    cands = generate_candidate_lessons(_30_trades_3_categories(), write=False, now=NOW)
    ids = {c["lesson_id"] for c in cands}
    assert {"thesis_category:capacity", "thesis_category:turnaround", "thesis_category:momentum"} <= ids
    print("  ✓ carried-forward candidates recorded, not dropped")


def test_category_unavailable_pre_scaffold_skip():
    recs = [ex(i) for i in range(10)]           # no thesis_category
    cands = {c["lesson_id"]: c for c in generate_candidate_lessons(recs, write=False, now=NOW)}
    assert "thesis_category:unavailable" in cands
    assert "unavailable pre-scaffold" in cands["thesis_category:unavailable"]["status"]
    print("  ✓ pre-scaffold → 'category data unavailable', not a crash")


def test_ledger_is_hash_chained(tmp_path):
    ledger = tmp_path / "lessons_ledger.jsonl"
    generate_candidate_lessons(_30_trades_3_categories(), ledger_path=ledger, write=True, now=NOW)
    ok, err = verify_chain(ledger)
    assert ok, err
    print("  ✓ ledger written hash-chained + verifies")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
