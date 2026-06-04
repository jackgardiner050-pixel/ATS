"""Zeus one-page decision report (§12.1) — human-readable markdown."""
from __future__ import annotations

from olympus.core.constants import ADVISORY_FOOTER
from olympus.models.records import ZeusDecision


def render(d: ZeusDecision) -> str:
    b = d.benchmark_alternative or {}
    etf = b.get("etf_alternative", {})
    L = [
        f"# Zeus Decision — {d.candidate_id.split('_')[-1]}  ·  **{d.decision}**",
        f"*decision {d.decision_id} · {d.date} · confidence {d.confidence_band} · evidence {d.evidence_grade}*",
        "",
        "## Decision",
        f"**{d.decision}** · confidence **{d.confidence_band}** · target {d.target_allocation:.0%} "
        f"(max {d.max_allocation:.0%}) · current {d.current_allocation:.0%}",
        "",
        "**Confidence constrained by:**",
        *([f"- {c}" for c in d.confidence_constrained_by] or ["- (none)"]),
        "",
        "## Thesis (Oracle)",
        d.thesis_summary,
        "",
        "## Strongest counter-case (Athena-Nemesis)",
        d.strongest_counter_case,
        "",
        "**Key risks:** " + ("; ".join(d.key_risks) or "n/a"),
        "**Thesis break:** " + ("; ".join(d.thesis_break_conditions) or "n/a"),
        "",
        "## Why not just the cheaper ETF? (§8)",
        f"- Thematic: {etf.get('thematic', 'n/a')} · Broad: {etf.get('broad', 'n/a')}",
        f"- {etf.get('note', '')}",
        f"- Priced-in / benchmark gauge: {b.get('priced_in_stance', 'n/a')}",
        "",
        "## Exposure (Hecate — core + satellite)",
        f"- **Core overlap:** {d.core_overlap_warning}",
        f"- **Satellite overlap:** {d.satellite_overlap_warning}",
        f"- Factor exposure: {d.factor_exposure}",
        "",
        "## Evidence independence (§7)",
        d.evidence_independence,
        "",
        "## Execution pathway (Hermes)",
        d.hermes_pathway,
        "",
        f"## Review by: {d.review_date or 'n/a'}",
        "",
        f"> {ADVISORY_FOOTER}",
    ]
    return "\n".join(L) + "\n"
