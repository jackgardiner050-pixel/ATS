"""Forward-prediction resolution (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY, step 5).

At the NEXT eligible review, each lesson adopted at the PRIOR boundary has its
forward_prediction evaluated against the intervening journal exits → TRUE / FALSE /
AMBIGUOUS. AMBIGUOUS is a DEFECT in the prediction (poorly specified), logged as such —
not a null result. This resolution history feeds the kill criterion (step 6) and the
review report (step 3); it is NEVER fed to Phaethon.

A prediction is resolvable only if it names a known metric, a comparator, and a numeric
threshold (e.g. "override_rate < 20%", "hit_rate > 0.55"). Anything else → AMBIGUOUS.
"""
from __future__ import annotations

import re
import statistics

TRUE, FALSE, AMBIGUOUS = "TRUE", "FALSE", "AMBIGUOUS"

_METRICS = {
    "override_rate": lambda es: (sum(1 for e in es if e.get("override_direction") in ("hold", "sell")) / len(es)) if es else None,
    "hit_rate": lambda es: (sum(1 for e in es if str(e.get("outcome", "")).lower() == "win") / len(es)) if es else None,
    "median_hold_days": lambda es: statistics.median([float(e["hold_days"]) for e in es if e.get("hold_days") is not None]) if any(e.get("hold_days") is not None for e in es) else None,
}
_METRIC_ALIASES = [
    (r"override[ _-]?rate", "override_rate"),
    (r"hit[ _-]?rate", "hit_rate"),
    (r"median[ _-]?hold|hold[ _-]?days|holding[ _-]?period", "median_hold_days"),
]
# Word-form comparators are \b-anchored so "over" inside "override_rate" is not a match.
_LT = re.compile(r"(?:<=|<)|\b(?:below|under|less than|falls? below|drops? below)\b", re.I)
_GT = re.compile(r"(?:>=|>)|\b(?:above|over|greater|exceeds?|rises? above)\b", re.I)
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(%?)")


def _find_metric(text: str):
    for pat, name in _METRIC_ALIASES:
        if re.search(pat, text, re.I):
            return name
    return None


def resolve_prediction(text: str, intervening_exits: list[dict]) -> dict:
    """Resolve one forward_prediction. Returns {resolution, metric, comparator, threshold,
    observed, note}."""
    if not text or not text.strip():
        return {"resolution": AMBIGUOUS, "note": "empty prediction"}
    metric = _find_metric(text)
    m_num = _NUM.search(text)
    lt, gt = _LT.search(text), _GT.search(text)
    comparator = "<" if (lt and not gt) else (">" if (gt and not lt) else None)
    if not (metric and m_num and comparator):
        return {"resolution": AMBIGUOUS, "metric": metric, "comparator": comparator,
                "note": "unparseable — no {metric, comparator, threshold} triple (prediction defect)"}
    thr = float(m_num.group(1)) / (100.0 if m_num.group(2) == "%" else 1.0)
    observed = _METRICS[metric](intervening_exits)
    if observed is None:
        return {"resolution": AMBIGUOUS, "metric": metric, "comparator": comparator,
                "threshold": thr, "observed": None, "note": "no intervening data for metric"}
    ok = (observed < thr) if comparator == "<" else (observed > thr)
    return {"resolution": TRUE if ok else FALSE, "metric": metric, "comparator": comparator,
            "threshold": thr, "observed": round(observed, 4),
            "note": f"observed {metric}={observed:.4f} {comparator} {thr}"}


def resolve_boundary_predictions(prior_boundary: dict, intervening_exits: list[dict]) -> list[dict]:
    """Resolve every adopted lesson's forward_prediction from the prior boundary."""
    out = []
    for lesson in prior_boundary.get("lessons_adopted", []):
        res = resolve_prediction(lesson.get("forward_prediction", ""), intervening_exits)
        out.append({"lesson_id": lesson.get("lesson_id"),
                    "category": lesson.get("category"), "stance": lesson.get("stance"),
                    "forward_prediction": lesson.get("forward_prediction"), **res})
    return out
