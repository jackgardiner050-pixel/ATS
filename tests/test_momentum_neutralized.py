"""Regression test proving momentum neutralization (item 8).

Two candidates identical in rating / prior confidence / revision but differing ONLY in
momentum quintile must now receive IDENTICAL confidence — and identical entry decisions.
Before neutralization, Q1 vs Q5 diverged (Q1 could bump MED→HIGH; Q5 could pull down).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.signals.escalation import get_signal_alignment, apply_confidence_escalation
from src.paper_trading import should_enter


def _confidence_after(rating, confidence_before, quintile, revision):
    aligned, contradicting, _ = get_signal_alignment(rating, quintile, revision)
    return apply_confidence_escalation(confidence_before, aligned, contradicting)


def test_confidence_identical_across_all_momentum_quintiles():
    """Same rating/confidence/revision, every quintile → one identical confidence."""
    for rating in ("STRONG_BUY", "BUY", "SELL", "STRONG_SELL", "HOLD"):
        for revision in ("POSITIVE", "NEGATIVE", "FLAT", "NO_COVERAGE"):
            for conf0 in ("LOW", "MED", "HIGH"):
                outs = {_confidence_after(rating, conf0, q, revision)
                        for q in (1, 2, 3, 4, 5, None)}
                assert len(outs) == 1, (
                    f"momentum changed confidence for {rating}/{conf0}/{revision}: {outs}")
    print("  ✓ momentum quintile never changes confidence (any rating/revision/tier)")


def test_previously_divergent_case_now_identical():
    """The exact case that used to diverge: STRONG_BUY + POSITIVE revision + Q1 vs Q5.

    Before: Q1 → 2 aligned (mom+rev) → MED→HIGH; Q5 → 1 aligned − 1 contradict → MED.
    After:  both → 1 aligned (revision only) → MED.
    """
    q1 = _confidence_after("STRONG_BUY", "MED", 1, "POSITIVE")
    q5 = _confidence_after("STRONG_BUY", "MED", 5, "POSITIVE")
    assert q1 == q5 == "MED"
    print("  ✓ STRONG_BUY + POSITIVE revision: Q1 and Q5 both → MED (were HIGH vs MED)")


def test_entry_decision_identical_across_quintiles():
    """should_enter depends on (rating, confidence); if confidence is quintile-invariant,
    so is the entry decision."""
    for q in (1, 5, None):
        conf = _confidence_after("STRONG_BUY", "MED", q, "FLAT")
        assert should_enter("STRONG_BUY", conf) is True   # STRONG_BUY + MED → enter, for all q
    # and a case that must NOT enter regardless of quintile
    for q in (1, 5):
        conf = _confidence_after("STRONG_BUY", "LOW", q, "FLAT")   # LOW, no bump → stays LOW
        assert should_enter("STRONG_BUY", conf) is False           # STRONG_BUY + LOW → no entry
    print("  ✓ entry decision is identical across momentum quintiles")


def test_revision_still_influences_confidence():
    """Neutralization is momentum-specific — revisions remain a directional signal.
    (Sanity: the change didn't accidentally neutralize everything.)"""
    # 2 aligned requires another signal beyond revision now; but a contradicting revision
    # pair still must be capable of moving confidence when doubled via two revision-class
    # signals is impossible (only one revision), so we assert revision is still classified
    # directionally rather than neutral.
    aligned, contradicting, _ = get_signal_alignment("STRONG_BUY", 3, "POSITIVE")
    assert "revision_positive" in aligned          # revision still aligns
    aligned2, contradicting2, _ = get_signal_alignment("STRONG_BUY", 3, "NEGATIVE")
    assert "revision_negative" in contradicting2   # revision still contradicts
    print("  ✓ revisions remain directional (only momentum was neutralized)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All momentum-neutralization regression tests passed.")
