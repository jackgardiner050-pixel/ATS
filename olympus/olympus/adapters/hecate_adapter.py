"""Hecate adapter (§4.3 / §9) — hidden concentration across satellite AND real-money core.

Satellite theme/factor weights come from the REAL `src.governance.exposure` engine run on the
actual 12-stock paper book. Core overlap is checked against the holdings in portfolio_policy.yaml.
Mandatory standing question (§8): why own the single name rather than the cheapest relevant ETF?
"""
from __future__ import annotations

import yaml

from olympus.core import config
from olympus.core.constants import ETF_ALTERNATIVES, MAX_THEME
from olympus.models.records import ExposureReport

from src.governance import exposure as EXP   # REAL exposure engine (~/agent/src)


def _satellite_tickers() -> list[str]:
    data = yaml.safe_load(config.SATELLITE_POSITIONS.read_text())
    return [p["ticker"] for p in data.get("positions", []) if "ticker" in p]


def _policy() -> dict:
    # prefers the gitignored real-holdings file if present, else the committed example core
    return yaml.safe_load(config.portfolio_policy_path().read_text()) or {}


def assess(candidate_ticker: str, *, candidate_id: str) -> ExposureReport:
    cand = candidate_ticker.upper()
    sat = _satellite_tickers()
    policy = _policy()

    # REAL satellite theme/factor weights, before and after adding the candidate.
    theme_before = EXP.compute_theme_weights(sat)
    theme_after = EXP.compute_theme_weights(sat + [cand])
    factor_after = EXP.compute_factor_weights(sat + [cand])

    # satellite overlap: does adding the candidate push its dominant theme toward/over the 40% cap?
    sat_warnings = []
    top_theme = max(theme_after, key=theme_after.get) if theme_after else None
    top_w = theme_after.get(top_theme, 0.0)
    status = "ok"
    if top_w >= MAX_THEME:
        status = "breach"
        sat_warnings.append(f"theme '{top_theme}' would be {top_w:.0%} of satellite — at/over the {MAX_THEME:.0%} cap")
    elif top_w >= MAX_THEME * 0.75:
        status = "elevated"
        sat_warnings.append(f"theme '{top_theme}' at {top_w:.0%} of satellite — approaching the {MAX_THEME:.0%} cap")
    if cand in [t.upper() for t in sat]:
        sat_warnings.append(f"{cand} is already held in the satellite — adding doubles concentration")

    # core overlap (§9): does the real-money core already give this exposure?
    core_supplied = bool(policy.get("core_supplied"))
    cand_themes = set((policy.get("candidate_themes", {}) or {}).get(cand, []))
    core_warnings = []
    for h in (policy.get("core", {}) or {}).get("holdings", []):
        shared = cand_themes & set(h.get("themes", []))
        if shared and h.get("weight", 0) > 0:
            core_warnings.append(
                f"core holding {h['id']} ({h.get('weight', 0):.0%}) already gives "
                f"{', '.join(sorted(shared))} exposure — {cand} may duplicate core exposure")
    if not core_supplied:
        core_warnings.append("CORE NOT SUPPLIED (example data) — core-overlap check is INCOMPLETE; "
                             "supply real holdings in portfolio_policy.yaml")

    return ExposureReport(
        exposure_id=f"exp_{candidate_id}", candidate_id=candidate_id, candidate_ticker=cand,
        satellite_theme_weights={k: round(v, 3) for k, v in theme_after.items()},
        satellite_overlap_warnings=sat_warnings,
        core_overlap_warnings=core_warnings,
        theme_exposure_status=status,
        factor_weights={k: round(v, 3) for k, v in factor_after.items()},
        etf_alternative=ETF_ALTERNATIVES.get(cand, {"thematic": "unknown", "broad": "VWRP",
                        "note": "no curated ETF map for this name yet — default to a broad-market tracker"}),
        core_supplied=core_supplied,
    )
