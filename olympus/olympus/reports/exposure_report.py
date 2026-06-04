"""Exposure report (§12.2) — core + satellite concentration, overlap, ETF alternative.

Runs the REAL Hecate exposure assessment (which itself runs the real src.governance.exposure
engine on the real 12-stock paper book) and renders it. Core is the example core until real
holdings are dropped into portfolio_policy.real.yaml.
"""
from __future__ import annotations

from olympus.adapters import hecate_adapter
from olympus.core.constants import ADVISORY_FOOTER


def build(ticker: str, candidate_id: str = "adhoc"):
    return hecate_adapter.assess(ticker, candidate_id=candidate_id)


def render(exp) -> str:
    etf = exp.etf_alternative or {}
    themes = sorted(exp.satellite_theme_weights.items(), key=lambda kv: -kv[1])
    L = [
        f"# Exposure Report — {exp.candidate_ticker}",
        f"*core {'SUPPLIED' if exp.core_supplied else 'EXAMPLE (not your real holdings)'} · "
        f"satellite theme status: **{exp.theme_exposure_status}***",
        "",
        "## Satellite theme weights (after adding candidate)",
        *([f"- {t}: {w:.0%}" for t, w in themes[:8]] or ["- (none)"]),
        "",
        "## Factor exposure",
        *([f"- {f}: {w:.0%}" for f, w in sorted(exp.factor_weights.items(), key=lambda kv: -kv[1])[:8]] or ["- (none)"]),
        "",
        "## Overlap warnings",
        "**Satellite:**",
        *([f"- {w}" for w in exp.satellite_overlap_warnings] or ["- none"]),
        "**Core (real-money / passive):**",
        *([f"- {w}" for w in exp.core_overlap_warnings] or ["- none"]),
        "",
        "## Why own this single name vs the cheapest ETF? (§8)",
        f"- Thematic ETF: {etf.get('thematic', 'n/a')}",
        f"- Broad-market: {etf.get('broad', 'n/a')}",
        f"- {etf.get('note', '')}",
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
