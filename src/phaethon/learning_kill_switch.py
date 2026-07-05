"""Kill criterion for the learning mechanism itself (step 6).

Tracks the trailing 4 review cycles' adopted-lesson resolutions. FIRES (writing the
sentinel data/phaethon/LEARNING_SUSPENDED with a diagnosis) if, across any 4 consecutive
cycles, EITHER:
  (a) >= 50% of RESOLVED forward predictions (TRUE/FALSE; AMBIGUOUS excluded) are FALSE, or
  (b) OSCILLATION — a lesson is adopted, later reversed (a subsequent boundary adopts a
      contradicting stance on the same category), then re-adopted in its original form.

When suspended, is_review_eligible() still computes eligibility (observation continues),
but phaethon_adopt_lesson refuses to adopt. Reinstatement (clear_suspension) requires the
operator to have written a non-trivial LEARNING_REINSTATEMENT_<date>.md — no silent clear.
"""
from __future__ import annotations

from pathlib import Path

from src.phaethon.prediction_resolution import FALSE, TRUE

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA = _ROOT / "data" / "phaethon"
SENTINEL = _DATA / "LEARNING_SUSPENDED"
TRAILING_CYCLES = 4
FALSE_FRACTION_TRIGGER = 0.5
_MIN_REINSTATEMENT_CHARS = 200


def _false_fraction_fires(cycles: list[dict]) -> str | None:
    resolved = [r for c in cycles for r in c.get("resolutions", [])
                if r.get("resolution") in (TRUE, FALSE)]
    if not resolved:
        return None
    n_false = sum(1 for r in resolved if r["resolution"] == FALSE)
    frac = n_false / len(resolved)
    if frac >= FALSE_FRACTION_TRIGGER:
        return f"(a) {n_false}/{len(resolved)} resolved forward predictions FALSE ({frac:.0%} >= 50%)"
    return None


def _oscillation_fires(cycles: list[dict]) -> str | None:
    """A>B>A stance sequence on the same category across boundaries in order."""
    by_cat: dict[str, list[str]] = {}
    for c in cycles:
        for a in c.get("adopted", []):
            cat, stance = a.get("category"), a.get("stance")
            if cat is not None and stance is not None:
                by_cat.setdefault(cat, []).append(stance)
    for cat, seq in by_cat.items():
        for i in range(len(seq)):
            for j in range(i + 1, len(seq)):
                if seq[j] != seq[i]:                       # reversal at j
                    if seq[i] in seq[j + 1:]:              # re-adopt original after reversal
                        return (f"(b) oscillation on '{cat}': stance {seq[i]!r} → {seq[j]!r} → "
                                f"{seq[i]!r} (adopt, reverse, re-adopt)")
    return None


def check_kill_criterion(cycles: list[dict]) -> tuple[bool, str | None]:
    """cycles: ordered list of {boundary_ts, adopted:[{category,stance,...}],
    resolutions:[{resolution,...}]}. Evaluated over the trailing TRAILING_CYCLES."""
    window = cycles[-TRAILING_CYCLES:]
    for check in (_false_fraction_fires, _oscillation_fires):
        diag = check(window)
        if diag:
            return True, diag
    return False, None


def is_suspended(sentinel: Path = SENTINEL) -> bool:
    return Path(sentinel).exists()


def maybe_suspend(cycles: list[dict], sentinel: Path = SENTINEL) -> tuple[bool, str | None]:
    """Fire the kill switch if warranted — write the sentinel with its diagnosis."""
    fired, diag = check_kill_criterion(cycles)
    if fired and not Path(sentinel).exists():
        Path(sentinel).parent.mkdir(parents=True, exist_ok=True)
        Path(sentinel).write_text(
            f"LEARNING_SUSPENDED\ndiagnosis: {diag}\n"
            "Adoption is blocked; review/ledger continue observation-only. Reverting to annual\n"
            "calendar review. Reinstatement requires a non-trivial LEARNING_REINSTATEMENT_<date>.md.\n")
    return fired, diag


def clear_suspension(reinstatement_doc: Path, sentinel: Path = SENTINEL) -> tuple[bool, str]:
    """Clear the sentinel ONLY if a non-trivial reinstatement diagnosis exists. No silent clear."""
    doc = Path(reinstatement_doc)
    if not is_suspended(sentinel):
        return False, "not suspended — nothing to clear"
    if (not doc.exists()) or doc.name.startswith("LEARNING_REINSTATEMENT") is False:
        return False, "refused — need a LEARNING_REINSTATEMENT_<date>.md diagnosis file"
    if len((doc.read_text().strip())) < _MIN_REINSTATEMENT_CHARS:
        return False, f"refused — reinstatement diagnosis too thin (< {_MIN_REINSTATEMENT_CHARS} chars)"
    Path(sentinel).unlink()
    return True, f"reinstated per {doc.name}"
