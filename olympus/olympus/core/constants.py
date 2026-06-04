"""Olympus MVP constants — allocation bands, governance limits, evidence vocabulary.

These mirror the spec (§4.4 bands, §4.3 limits). The HARD limits are ALSO enforced by the
real governance engines (src.governance.concentration_governor / constitution); these constants
are the Olympus-side policy and the band mapping. No constant here overrides survivability.
"""
from __future__ import annotations

# Evidence labels (§4.1) — every Oracle claim must be one of these.
EVIDENCE_LABELS = ("Evidence", "Hypothesis", "Assumption", "Opinion", "Unknown")

# Allowed Zeus final decisions (§4.6).
ZEUS_DECISIONS = ("BUY", "HOLD", "REDUCE", "EXIT")

# Allocation bands (§4.4), as fraction of total satellite capital.
ALLOCATION_BANDS = {
    "research":   (0.0, 0.0),     # insufficient evidence
    "watchlist":  (0.0, 0.0),
    "actionable": (0.01, 0.03),   # 1–3%
    "high_conviction": (0.03, 0.05),  # 3–5%
}
MAX_INITIAL = 0.03   # hard: max initial 3%
MAX_SINGLE = 0.05    # hard: max single position 5%
MAX_THEME = 0.40     # hard: max theme 40%

# Map an Oracle (evidence_grade, confidence) → allocation band. Deliberately conservative:
# the honest dominant output is research/watchlist/HOLD, not BUY.
def band_for(evidence_grade: str, conviction_pct: int) -> str:
    eg = (evidence_grade or "").lower()
    if eg in ("weak", "thin", "speculative") or conviction_pct < 55:
        return "research"
    if conviction_pct >= 70 and eg in ("strong", "high"):
        return "high_conviction"
    if conviction_pct >= 60:
        return "actionable"
    return "watchlist"


# Cheapest-relevant-ETF map (§8). Small, honest, extend over time. Used to force the
# "why own the single name rather than the cheaper fund?" question.
ETF_ALTERNATIVES = {
    "ORCL": {"thematic": "SKYY (cloud) / IGV (software)", "broad": "QQQ / VWRP",
             "note": "AI-capex/cloud exposure is largely available passively and far cheaper."},
}

ADVISORY_FOOTER = (
    "RESEARCH-GRADE · PAPER ONLY · forward-test in progress, NOT validated. "
    "This is not an order. No trade has been placed. **Human authorisation required.**"
)
