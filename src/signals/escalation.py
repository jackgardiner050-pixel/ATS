"""Signal-based confidence escalation and alignment scoring.

Alignment rules (signals modify confidence, never the price target or rating):
  Rating          Mom (any Q)   Rev POSITIVE  Rev NEGATIVE
  STRONG_BUY/BUY  neutral       aligned       contradicts
  HOLD            neutral       neutral*      neutral*
  SELL/S_SELL     neutral       contradicts   aligned

  *HOLD + sharp revision → flag force_rescreen (see should_force_rescreen).

  MOMENTUM IS OBSERVATION-ONLY (2026-07-05, item 8): the momentum quintile is always
  classified NEUTRAL — it is still computed and recorded for attribution but no longer
  escalates confidence. Validation (signal-validation-studies: Q1−Q5 net-of-cost spread
  Newey-West t=0.09, n=121, 2015-2025) found no significant edge, so per the
  pre-committed decision frame (t<2 ⇒ neutralize) momentum no longer moves confidence.
  Only analyst revisions remain a directional confidence signal. Do NOT re-couple
  momentum without fresh, significant evidence.

Escalation:
  2+ aligned signals   → bump confidence up   (LOW→MED, MED→HIGH)
  2+ contradicting     → bump confidence down (HIGH→MED, MED→LOW)
  cohort_outlier       → hard cap at LOW (cannot escalate above LOW)
  BROKEN               → unchanged
  Floor: LOW   Ceiling: HIGH
"""
from __future__ import annotations

_TIERS = ("BROKEN", "LOW", "MED", "HIGH")


def get_signal_alignment(
    rating: str,
    momentum_quintile: int | None,
    revision_direction: str,
) -> tuple[list[str], list[str], list[str]]:
    """Classify each signal as aligned, contradicting, or neutral w.r.t. the rating.

    Returns (aligned, contradicting, neutral) lists of signal names.
    """
    aligned: list[str] = []
    contradicting: list[str] = []
    neutral: list[str] = []

    is_bullish = rating in ("STRONG_BUY", "BUY")
    is_bearish = rating in ("SELL", "STRONG_SELL")

    # Momentum signal — OBSERVATION-ONLY (2026-07-05, item 8). The quintile is still
    # computed and RECORDED (in `neutral`, so it flows to attribution / recommendation
    # signal lists) but it is never aligned/contradicting, so it can no longer change
    # the confidence tier. Rationale + evidence: module docstring. Do not re-couple
    # without fresh, significant evidence (current: Q1−Q5 spread t=0.09, n=121).
    if momentum_quintile is not None:
        neutral.append(f"momentum_q{momentum_quintile}")

    # Revision signal — POSITIVE and NEGATIVE are directional; FLAT / NO_COVERAGE are neutral
    if revision_direction == "POSITIVE":
        if is_bullish:
            aligned.append("revision_positive")
        elif is_bearish:
            contradicting.append("revision_positive")
        else:
            neutral.append("revision_positive")
    elif revision_direction == "NEGATIVE":
        if is_bearish:
            aligned.append("revision_negative")
        elif is_bullish:
            contradicting.append("revision_negative")
        else:
            neutral.append("revision_negative")
    elif revision_direction in ("FLAT", "NO_COVERAGE"):
        neutral.append(f"revision_{revision_direction.lower()}")

    return aligned, contradicting, neutral


def apply_confidence_escalation(
    confidence: str,
    aligned: list[str],
    contradicting: list[str],
    cohort_outlier: bool = False,
) -> str:
    """Return new confidence tier after applying signal alignment.

    Rules:
      BROKEN → always BROKEN (signals cannot fix a broken model)
      2+ aligned      → bump up one tier (ceiling: HIGH)
      2+ contradicting → bump down one tier (floor: LOW)
      cohort_outlier   → hard cap at LOW (applied after escalation)
    """
    if confidence == "BROKEN":
        return "BROKEN"

    conf = confidence
    if conf not in _TIERS:
        conf = "MED"

    tier_idx = _TIERS.index(conf)

    if len(aligned) >= 2:
        tier_idx = min(tier_idx + 1, _TIERS.index("HIGH"))

    if len(contradicting) >= 2:
        tier_idx = max(tier_idx - 1, _TIERS.index("LOW"))

    conf = _TIERS[tier_idx]

    # Cohort outlier hard cap — must be applied last
    if cohort_outlier and conf in ("MED", "HIGH"):
        conf = "LOW"

    return conf


def build_signal_alignment_list(
    aligned: list[str],
    contradicting: list[str],
    neutral: list[str],
    rating: str,
    momentum_quintile: int | None,
    revision_direction: str,
) -> list[dict]:
    """Build the signal_alignment list for recommendation.json."""
    rows = []
    _REASONS: dict[tuple[str, str], str] = {
        ("momentum_q1", "aligned"):       f"Q1 momentum ({momentum_quintile}) supports bullish rating {rating}",
        ("momentum_q1", "contradicts"):   f"Q1 momentum ({momentum_quintile}) contradicts bearish rating {rating}",
        ("momentum_q1", "neutral"):       f"Momentum Q{momentum_quintile} — observation-only (does not affect confidence)",
        ("momentum_q5", "aligned"):       f"Q5 momentum ({momentum_quintile}) supports bearish rating {rating}",
        ("momentum_q5", "contradicts"):   f"Q5 momentum ({momentum_quintile}) contradicts bullish rating {rating}",
        ("momentum_q5", "neutral"):       f"Momentum Q{momentum_quintile} — observation-only (does not affect confidence)",
        ("revision_positive", "aligned"):      f"Positive analyst revisions support bullish {rating}",
        ("revision_positive", "contradicts"):  f"Positive analyst revisions contradict bearish {rating}",
        ("revision_positive", "neutral"):      f"Positive revisions on HOLD — flagging for re-screen",
        ("revision_negative", "aligned"):      f"Negative analyst revisions support bearish {rating}",
        ("revision_negative", "contradicts"):  f"Negative analyst revisions contradict bullish {rating}",
        ("revision_negative", "neutral"):      f"Negative revisions on HOLD — flagging for re-screen",
        ("revision_flat", "neutral"):          "Revision direction flat — no signal",
        ("revision_no_coverage", "neutral"):   "Insufficient analyst coverage for revision signal",
    }
    for sig in aligned:
        reason_key = (sig if not sig.startswith("momentum_q") or sig in ("momentum_q1", "momentum_q5")
                      else "momentum_mid", "aligned")
        if sig.startswith("momentum_q") and sig not in ("momentum_q1", "momentum_q5"):
            reason = f"Momentum Q{momentum_quintile} (mid-quintile) — neutral"
        else:
            reason = _REASONS.get((sig, "aligned"), f"{sig}: aligned with {rating}")
        rows.append({"signal": sig, "alignment": "aligned", "reason": reason})
    for sig in contradicting:
        reason = _REASONS.get((sig, "contradicts"), f"{sig}: contradicts {rating}")
        rows.append({"signal": sig, "alignment": "contradicts", "reason": reason})
    for sig in neutral:
        reason = _REASONS.get((sig, "neutral"), f"{sig}: neutral")
        rows.append({"signal": sig, "alignment": "neutral", "reason": reason})
    return rows


def should_force_rescreen(rating: str, revision_direction: str) -> bool:
    """HOLD + sharp positive or negative revision triggers force_rescreen next run."""
    return rating == "HOLD" and revision_direction in ("POSITIVE", "NEGATIVE")


def revision_symbol(direction: str) -> str:
    """One-character display symbol for revision direction."""
    return {"POSITIVE": "▲", "NEGATIVE": "▼", "FLAT": "·"}.get(direction, "—")
