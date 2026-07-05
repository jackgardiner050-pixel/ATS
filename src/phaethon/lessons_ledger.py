"""Statistical candidate-lesson generator (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY, step 2).

Reads the decision journal (item 1) + optional consistency-report data (item 4) and emits
CANDIDATE LESSONS at meta-level ONLY (never per-ticker), each with its n, statistic, and
p-value/CI. A lesson is `adoptable` only if it clears the pre-registered bar:
  (binomial p < 0.05 vs null 50%  OR  calibration-gap CI excludes zero)
  AND n >= MIN_OBSERVATIONS_FOR_CALIBRATION   (constitution — NOT a new magic number)
Lessons that fail the bar are recorded as "candidate — insufficient n / not significant,
carried forward" WITH their partial statistics — never silently dropped.

HUMAN-SIDE ONLY — this and everything it produces is for the review report; it never
enters Phaethon's prompt/context (NO_LIVE_PNL_LEARNING firewall).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path

import yaml
from scipy.stats import binomtest, mannwhitneyu

from src.phaethon.journal import exits_since_last_boundary
from src.research.registry import append_hashchained

_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEDGER = _ROOT / "data" / "phaethon" / "lessons_ledger.jsonl"


def min_observations() -> int:
    """MIN_OBSERVATIONS_FOR_CALIBRATION from the constitution (reused, not re-invented)."""
    c = yaml.safe_load((_ROOT / "config" / "constitution.yaml").read_text()) or {}
    return int(c.get("MIN_OBSERVATIONS_FOR_CALIBRATION", 20))


def _is_win(rec: dict) -> bool:
    return str(rec.get("outcome", "")).lower() == "win"


def _binom(k: int, n: int) -> tuple[float, tuple[float, float]]:
    """Two-sided binomial p vs 0.5 + Wilson 95% CI of the proportion."""
    r = binomtest(k, n, 0.5, alternative="two-sided")
    ci = r.proportion_ci(confidence_level=0.95, method="wilson")
    return float(r.pvalue), (float(ci.low), float(ci.high))


def _candidate(review_ts, lesson_id, level, bucket, n, statistic, test, adoptable, status, claim):
    return {"review_ts": review_ts, "lesson_id": lesson_id, "level": level, "bucket": bucket,
            "n": n, "statistic": statistic, "test": test, "adoptable": adoptable,
            "status": status, "claim": claim}


def _status(sig: bool, n: int, min_n: int) -> tuple[bool, str]:
    if n < min_n:
        return False, "candidate — insufficient n, carried forward"
    if not sig:
        return False, "candidate — not significant, carried forward"
    return True, "adoptable"


def generate_candidate_lessons(records: list[dict], ledger_path=DEFAULT_LEDGER,
                               write: bool = True, now: datetime | None = None,
                               consistency: dict | None = None) -> list[dict]:
    """Compute + (optionally) persist candidate lessons for the exits since the last boundary."""
    now = now or datetime.now(timezone.utc)
    review_ts = now.isoformat()
    exits, _ = exits_since_last_boundary(records)
    min_n = min_observations()
    out: list[dict] = []

    # ── (a) thesis-category hit-rate ─────────────────────────────────────────
    tagged = [e for e in exits if e.get("thesis_category")]
    if not tagged:
        out.append(_candidate(review_ts, "thesis_category:unavailable", "thesis_category",
                              None, 0, {}, "binomial_vs_0.5", False,
                              "skipped — category data unavailable pre-scaffold",
                              "Thesis-category hit-rate needs item-3 entry scaffold (or a manual tag)."))
    else:
        cats: dict[str, list] = {}
        for e in tagged:
            cats.setdefault(e["thesis_category"], []).append(e)
        for cat, es in sorted(cats.items()):
            n = len(es); k = sum(_is_win(e) for e in es)
            p, ci = _binom(k, n)
            adoptable, status = _status(p < 0.05, n, min_n)
            out.append(_candidate(review_ts, f"thesis_category:{cat}", "thesis_category", cat, n,
                                  {"hits": k, "hit_rate": round(k / n, 3), "p_value": round(p, 4),
                                   "wilson_ci": [round(ci[0], 3), round(ci[1], 3)]},
                                  "binomial_vs_0.5", adoptable, status,
                                  f"'{cat}' theses hit {k}/{n} ({k/n:.0%}) vs 50% null."))

    # ── (b) calibration by conviction tier ───────────────────────────────────
    conv = [e for e in exits if e.get("conviction_tier") and e.get("stated_conviction") is not None]
    if not conv:
        out.append(_candidate(review_ts, "calibration:unavailable", "calibration", None, 0, {},
                              "calibration_gap_ci", False,
                              "skipped — sizing/conviction data unavailable",
                              "Calibration needs stated_conviction + conviction_tier on exits."))
    else:
        tiers: dict[str, list] = {}
        for e in conv:
            tiers.setdefault(str(e["conviction_tier"]), []).append(e)
        for tier, es in sorted(tiers.items()):
            n = len(es); k = sum(_is_win(e) for e in es)
            realized = k / n
            stated = statistics.mean(float(e["stated_conviction"]) for e in es)
            _, ci = _binom(k, n)                       # Wilson CI of realized hit rate
            gap = stated - realized
            gap_ci = [round(stated - ci[1], 3), round(stated - ci[0], 3)]  # stated − CI(realized)
            excludes_zero = not (ci[0] <= stated <= ci[1])
            adoptable, status = _status(excludes_zero, n, min_n)
            out.append(_candidate(review_ts, f"calibration:{tier}", "calibration", tier, n,
                                  {"stated_conviction": round(stated, 3), "realized_hit_rate": round(realized, 3),
                                   "gap": round(gap, 3), "gap_ci": gap_ci},
                                  "calibration_gap_ci", adoptable, status,
                                  f"Tier '{tier}': stated {stated:.0%} vs realized {realized:.0%} (gap {gap:+.0%})."))

    # ── (c) behavioral: override direction + disposition ─────────────────────
    for direction in ("hold", "sell"):
        es = [e for e in exits if e.get("override_direction") == direction]
        if es:
            n = len(es); k = sum(_is_win(e) for e in es)
            p, ci = _binom(k, n)
            adoptable, status = _status(p < 0.05, n, min_n)
            out.append(_candidate(review_ts, f"behavioral:override_{direction}", "behavioral",
                                  f"override_{direction}", n,
                                  {"hits": k, "success_rate": round(k / n, 3), "p_value": round(p, 4),
                                   "wilson_ci": [round(ci[0], 3), round(ci[1], 3)]},
                                  "binomial_vs_0.5", adoptable, status,
                                  f"Override-to-{direction} succeeded {k}/{n} ({k/n:.0%})."))

    disp = [e for e in exits if e.get("hold_days") is not None and e.get("outcome")]
    if disp:
        win_h = [float(e["hold_days"]) for e in disp if _is_win(e)]
        los_h = [float(e["hold_days"]) for e in disp if not _is_win(e)]
        n = len(disp)
        if win_h and los_h:
            p = float(mannwhitneyu(win_h, los_h, alternative="two-sided").pvalue)
        else:
            p = 1.0
        adoptable, status = _status(p < 0.05, n, min_n)
        out.append(_candidate(review_ts, "behavioral:disposition_effect", "behavioral",
                              "disposition_effect", n,
                              {"median_hold_winners": round(statistics.median(win_h), 1) if win_h else None,
                               "median_hold_losers": round(statistics.median(los_h), 1) if los_h else None,
                               "p_value": round(p, 4)}, "mann_whitney_u", adoptable, status,
                              "Disposition effect: median hold of winners vs losers."))

    if write:
        for c in out:
            append_hashchained(ledger_path, c)
    return out
