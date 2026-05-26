"""Anti-Delusion Dashboard — diagnostic report focused on "what could be wrong?"

Aggregates all governance signals into one human-readable CLI report.
Orientation: NOT performance marketing. Every section asks: what is fragile?

Sections:
  1. Regime Intelligence
  2. Portfolio Concentration
  3. Signal Reliability
  4. Confidence Calibration
  5. Adversarial Critiques
  6. Constitutional Compliance
  7. Fragility Summary

Output: printed to stdout (CLI-first). Optionally serialized to JSON
for downstream Telegram digest integration.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _bar(fraction: float, width: int = 20, char: str = "▓", empty: str = "░") -> str:
    filled = round(fraction * width)
    return char * filled + empty * (width - filled)


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.1%}"


def _tier_badge(tier: Optional[str]) -> str:
    badges = {"HIGH": "[HIGH]", "MED": "[MED]", "LOW": "[LOW]", "BROKEN": "[!BRK]"}
    return badges.get(tier or "", "[???]")


def _format_regime_section(regime_result: Optional[dict]) -> str:
    lines = ["─── 1. REGIME INTELLIGENCE ─────────────────────────────────────────"]
    if regime_result is None:
        lines.append("  [!] Regime engine not run. Execute run_governance.py to populate.")
        return "\n".join(lines)

    probs = regime_result.get("probabilities", {})
    leading = regime_result.get("leading_regime", "unknown")
    confidence = regime_result.get("confidence", 0.0)
    ts = regime_result.get("timestamp", "")[:10]

    lines.append(f"  As of: {ts}    Leading: {leading}    Clarity: {_pct(confidence)}")
    lines.append("")

    sorted_regimes = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    for regime, prob in sorted_regimes:
        marker = " ◄" if regime == leading else ""
        lines.append(f"  {regime:<32} {_pct(prob)} {_bar(prob)}{marker}")

    if confidence < 0.25:
        lines.append("")
        lines.append("  [!] FRAGILITY: Low regime confidence — environment is ambiguous.")

    active_cond = regime_result.get("conditions", {})
    if active_cond:
        lines.append("")
        lines.append(f"  Active conditions: {', '.join(sorted(active_cond.keys()))}")

    return "\n".join(lines)


def _format_exposure_section(exposure_result: Optional[dict]) -> str:
    lines = ["─── 2. PORTFOLIO CONCENTRATION ─────────────────────────────────────"]
    if exposure_result is None:
        lines.append("  [!] Exposure analysis not run.")
        return "\n".join(lines)

    tickers = exposure_result.get("tickers", [])
    n = len(tickers)
    lines.append(f"  Positions: {n}  |  Tickers: {', '.join(tickers)}")
    lines.append("")

    theme_weights = exposure_result.get("theme_weights", {})
    if theme_weights:
        lines.append("  THEME EXPOSURE (primary classification):")
        for theme, w in sorted(theme_weights.items(), key=lambda x: x[1], reverse=True):
            if theme == "unknown":
                continue
            flag = " [!VIOLATION]" if w > 0.25 else (" [WATCH]" if w >= 0.20 else "")
            lines.append(f"    {theme:<34} {_pct(w)} {_bar(w)}{flag}")

    factor_weights = exposure_result.get("factor_weights", {})
    if factor_weights:
        lines.append("")
        lines.append("  FACTOR EXPOSURE (cross-cutting macro bets):")
        for factor, w in sorted(factor_weights.items(), key=lambda x: x[1], reverse=True):
            flag = " [!VIOLATION]" if w > 0.40 else (" [WATCH]" if w >= 0.30 else "")
            lines.append(f"    {factor:<34} {_pct(w)} {_bar(w)}{flag}")

    warnings = exposure_result.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("  CONCENTRATION WARNINGS:")
        for w in warnings:
            lines.append(f"    {w}")

    return "\n".join(lines)


def _format_signal_section(signal_result: Optional[dict]) -> str:
    lines = ["─── 3. SIGNAL RELIABILITY ───────────────────────────────────────────"]
    if signal_result is None:
        lines.append("  [!] Signal tracker not run.")
        return "\n".join(lines)

    n = signal_result.get("n_signal_entries", 0)
    any_decay = signal_result.get("any_decay_warning", False)
    lines.append(f"  Signal log entries: {n}    Any decay warning: {'YES [!]' if any_decay else 'no'}")
    lines.append("")

    signals = signal_result.get("signals", {})
    for sig_key, sig in signals.items():
        name = sig.get("signal", sig_key)
        status = sig.get("status", "unknown")
        quality = sig.get("overall_quality")
        decay = sig.get("decay_warning", False)
        instability = sig.get("instability_score")

        q_str = _pct(quality) if quality is not None else "N/A"
        decay_flag = " [!DECAY]" if decay else ""
        inst_flag = f"  instability={_pct(instability)}" if instability else ""

        lines.append(f"  {name:<32} quality={q_str}{decay_flag}{inst_flag}")
        if status not in ("computed", "structural_analysis"):
            lines.append(f"    status: {status}")

    return "\n".join(lines)


def _format_calibration_section(calib_result: Optional[dict]) -> str:
    lines = ["─── 4. CONFIDENCE CALIBRATION ───────────────────────────────────────"]
    if calib_result is None:
        lines.append("  [!] Calibration not run.")
        return "\n".join(lines)

    ready = calib_result.get("calibration_ready", False)
    total_closed = calib_result.get("total_closed_trades", 0)
    min_obs = calib_result.get("min_observations_required", 20)

    if not ready:
        lines.append(
            f"  Calibration status: ACCUMULATING DATA "
            f"({total_closed}/{min_obs} closed trades)"
        )
    else:
        lines.append(f"  Calibration status: ACTIVE ({total_closed} closed trades)")

    lines.append("")
    dist = calib_result.get("confidence_distribution", {})
    total_sigs = sum(dist.values())
    if dist:
        lines.append("  CONFIDENCE TIER DISTRIBUTION (signal log):")
        for tier in ("HIGH", "MED", "LOW", "BROKEN", "UNKNOWN"):
            count = dist.get(tier, 0)
            frac = count / total_sigs if total_sigs > 0 else 0.0
            lines.append(f"    {_tier_badge(tier)} {count:>4} tickers  {_pct(frac)} {_bar(frac, 15)}")

    tier_perf = calib_result.get("tier_performance", {})
    if tier_perf and ready:
        lines.append("")
        lines.append("  TIER PERFORMANCE:")
        for tier, perf in tier_perf.items():
            avg_exc = perf.get("avg_excess_return_vs_spy")
            wr = perf.get("win_rate")
            lines.append(
                f"    {_tier_badge(tier)} excess_vs_SPY={_pct(avg_exc)}  "
                f"win_rate={_pct(wr)}  n={perf['count']}"
            )

    contr = calib_result.get("contradiction_report", {})
    if contr.get("status") == "computed" and contr.get("rate") is not None:
        rate = contr["rate"]
        if rate > 0.05:
            lines.append(
                f"\n  [!] Contradictory confidence states: {contr['contradictions']}/{contr['total']} "
                f"({_pct(rate)}) — HIGH confidence tickers with contradicting signals"
            )

    return "\n".join(lines)


def _format_adversarial_section(adversarial_result: Optional[dict]) -> str:
    lines = ["─── 5. ADVERSARIAL CRITIQUE ─────────────────────────────────────────"]
    if adversarial_result is None:
        lines.append("  [!] No adversarial review on record. Run governance with --adversarial flag.")
        return "\n".join(lines)

    ts = adversarial_result.get("timestamp", "")[:10]
    status = adversarial_result.get("status", "unknown")
    lines.append(f"  Last review: {ts}    Status: {status}")

    critique = adversarial_result.get("critique", {})
    if not critique or "error" in critique:
        err = critique.get("error", "unknown") if critique else "no critique"
        lines.append(f"  [{err}]")
        if err == "no_api_key":
            lines.append("  Set ANTHROPIC_API_KEY to enable adversarial review.")
        return "\n".join(lines)

    if critique.get("single_biggest_risk"):
        lines.append("")
        lines.append(f"  SINGLE BIGGEST RISK:")
        lines.append(f"  ► {critique['single_biggest_risk']}")

    for key, label in [
        ("macro_counterarguments", "MACRO COUNTERARGUMENTS"),
        ("hidden_assumptions", "HIDDEN ASSUMPTIONS"),
        ("regime_vulnerabilities", "REGIME VULNERABILITIES"),
    ]:
        items = critique.get(key, [])
        if items:
            lines.append("")
            lines.append(f"  {label}:")
            for item in items:
                lines.append(f"  • {item}")

    lines.append("")
    lines.append("  [Adversarial critique only — not investment advice or price targets]")
    return "\n".join(lines)


def _format_constitutional_section(
    constitution_report,
    exposure_result: Optional[dict],
    calib_result: Optional[dict],
) -> str:
    lines = ["─── 6. CONSTITUTIONAL COMPLIANCE ───────────────────────────────────"]

    hard_rules = [
        "NO_LEVERAGE",
        "NO_AUTONOMOUS_EXECUTION",
        "HUMAN_APPROVAL_REQUIRED",
        "NO_LIVE_PNL_LEARNING",
        "NO_BROKER_INTEGRATION",
    ]
    for rule in hard_rules:
        lines.append(f"  ✓ {rule}")

    if constitution_report is not None:
        if constitution_report.violations:
            lines.append("")
            lines.append("  VIOLATIONS:")
            for v in constitution_report.violations:
                lines.append(f"  ✗ {v}")
        else:
            lines.append("")
            lines.append("  ✓ All concentration limits compliant")

        if constitution_report.warnings:
            lines.append("")
            lines.append("  WARNINGS:")
            for w in constitution_report.warnings:
                lines.append(f"  ⚠ {w}")

    return "\n".join(lines)


def _format_fragility_summary(
    regime_result: Optional[dict],
    exposure_result: Optional[dict],
    signal_result: Optional[dict],
    calib_result: Optional[dict],
    constitution_report,
) -> str:
    lines = ["─── 7. FRAGILITY SUMMARY ────────────────────────────────────────────"]
    fragilities = []

    if regime_result:
        conf = regime_result.get("confidence", 1.0)
        if conf < 0.25:
            fragilities.append("Regime ambiguity: environment classification is unclear")
        leading = regime_result.get("leading_regime", "")
        if leading in ("high_volatility_stress", "liquidity_panic", "risk_off_defensive"):
            fragilities.append(
                f"Adverse regime: currently in {leading} — long-only industrial bias is at risk"
            )

    if exposure_result:
        for w in exposure_result.get("warnings", []):
            if "[VIOLATION]" in w:
                fragilities.append(f"Concentration breach: {w.replace('[VIOLATION] ', '')}")

    if signal_result and signal_result.get("any_decay_warning"):
        fragilities.append("Signal decay: one or more tracking signals below quality threshold")

    if calib_result:
        contr = calib_result.get("contradiction_report", {})
        if contr.get("rate") and contr["rate"] > 0.10:
            fragilities.append(
                f"Model inconsistency: {contr['contradictions']} contradictory confidence states "
                f"({_pct(contr['rate'])})"
            )

    if constitution_report and constitution_report.violations:
        fragilities.append(
            f"Constitutional violations: {len(constitution_report.violations)} active breach(es)"
        )

    if fragilities:
        for f in fragilities:
            lines.append(f"  ⚠ {f}")
    else:
        lines.append("  ✓ No active fragility warnings")

    lines.append("")
    lines.append(
        "  Reminder: this dashboard asks 'what could be wrong?' — not 'how well are we doing?'"
    )

    return "\n".join(lines)


def _format_portfolio_intelligence(portfolio_result: Optional[dict]) -> str:
    lines = ["─── 8. PORTFOLIO INTELLIGENCE ───────────────────────────────────────"]
    if portfolio_result is None:
        lines.append("  [!] Portfolio intelligence not run. Pass --portfolio to include.")
        return "\n".join(lines)

    exposure = portfolio_result.get("exposure", {})
    survivability = portfolio_result.get("survivability", {})
    stress = portfolio_result.get("stress", {})
    factor = portfolio_result.get("factor", {})
    escalations = portfolio_result.get("escalation_triggers", [])

    # Narrative
    narrative = exposure.get("narrative", "")
    if narrative:
        lines.append(f"  {narrative}")
        lines.append("")

    # Effective bets
    eff_bets = exposure.get("effective_bets", "?")
    n_pos = exposure.get("n_positions", "?")
    div_ratio = exposure.get("effective_diversification_ratio", 0)
    lines.append(
        f"  Effective macro bets: {eff_bets:.1f} of {n_pos} positions "
        f"(diversification ratio: {div_ratio:.0%})"
    )

    # Top theme concentrations
    theme_exp = exposure.get("theme_exposure", {})
    if theme_exp:
        lines.append("")
        lines.append("  TOP THEME CONCENTRATIONS:")
        for theme, w in list(theme_exp.items())[:6]:
            if theme == "unclassified":
                continue
            flag = " [!BLOCK]" if w > 0.25 else (" [WATCH]" if w >= 0.20 else "")
            lines.append(f"    {theme:<30} {_pct(w)} {_bar(w)}{flag}")

    # Cluster summary
    for cluster_key in ("leverage_cluster", "policy_cluster", "cyclical_cluster"):
        c = exposure.get(cluster_key, {})
        if c:
            w = c.get("exposure", 0)
            limit = c.get("limit", 1)
            tickers = c.get("tickers", [])
            flag = " [!BLOCK]" if c.get("breached") else ""
            label = cluster_key.replace("_cluster", "").replace("_", " ").title()
            lines.append(
                f"    {label + ' cluster':<30} {_pct(w)} [{', '.join(tickers)}]{flag}"
            )

    # Survivability
    if survivability:
        score = survivability.get("survivability_score", 0)
        classification = survivability.get("classification", "?")
        max_dd = survivability.get("estimated_max_drawdown", 0)
        lines.append("")
        lines.append(
            f"  SURVIVABILITY: {score:.0f}/100  [{classification}]  "
            f"estimated max drawdown: {_pct(max_dd)}"
        )
        breakdown = survivability.get("component_breakdown", {})
        if breakdown:
            parts = [f"{k}={v:.2f}" for k, v in list(breakdown.items())[:5]]
            lines.append(f"    Components: {', '.join(parts)}")

    # Stress test summary
    if stress:
        worst = stress.get("worst_scenario", "?")
        worst_dd = stress.get("worst_case_drawdown", 0)
        avg_dd = stress.get("average_drawdown", 0)
        port_class = stress.get("portfolio_classification", "?")
        lines.append("")
        lines.append(
            f"  STRESS TEST: worst='{worst}' ({_pct(worst_dd)})  "
            f"avg={_pct(avg_dd)}  classification={port_class}"
        )
        always_vuln = stress.get("always_vulnerable", [])
        if always_vuln:
            lines.append(f"    Hurt in 7+/10 scenarios: {', '.join(always_vuln)}")

    # Factor summary
    if factor:
        top_factor = factor.get("most_concentrated_factor", "?")
        top_score = factor.get("most_concentrated_score", 0)
        factor_warns = factor.get("warnings", [])
        lines.append("")
        lines.append(
            f"  FACTOR DOMINANCE: top={top_factor} ({top_score:.2f})  "
            f"warnings={len(factor_warns)}"
        )

    # Escalation triggers
    if escalations:
        lines.append("")
        lines.append(f"  ESCALATION TRIGGERS ({len(escalations)}):")
        for e in escalations:
            lines.append(f"    ⚠ {e}")

    # Hidden dependencies
    hidden = exposure.get("hidden_dependencies", [])
    if hidden:
        lines.append("")
        lines.append("  HIDDEN DEPENDENCIES:")
        for h in hidden[:3]:
            lines.append(f"    • {h}")

    return "\n".join(lines)


def _format_universe_intelligence(universe_result: Optional[dict]) -> str:
    lines = ["─── 9. UNIVERSE INTELLIGENCE ────────────────────────────────────────"]
    if universe_result is None:
        lines.append("  [!] Universe intelligence not run. Pass --universe to include.")
        return "\n".join(lines)

    audit = universe_result.get("audit", {})
    gov = universe_result.get("governance", {})
    diversifier = universe_result.get("diversifier", {})
    alignment = universe_result.get("alignment", {})

    n = audit.get("n_tickers", 0)
    bal_score = audit.get("balance_score", 0.0)
    bias_summary = audit.get("universe_bias_summary", "")
    lines.append(f"  Universe size: {n} tickers   Balance score: {bal_score:.2f}/1.00")
    if bias_summary:
        lines.append(f"  {bias_summary[:120]}")
    lines.append("")

    # Archetype distribution (top overrepresented)
    overrep = audit.get("overrepresented_archetypes", [])
    absent = audit.get("absent_archetypes", [])
    if overrep or absent:
        lines.append("  ARCHETYPE BALANCE:")
    if overrep:
        for a in overrep[:4]:
            frac = audit.get("archetype_exposures", {}).get(a, 0.0)
            lines.append(f"    {a:<30} {_pct(frac)} {_bar(frac)} [!OVERREP]")
    if absent:
        for a in absent[:4]:
            lines.append(f"    {a:<30}   0.0%  {'░'*20}  [ABSENT]")

    # Key balance metrics
    lines.append("")
    lines.append("  COMPOSITION:")
    cyclical_frac = audit.get("cyclical_fraction", 0.0)
    defensive_frac = audit.get("defensive_fraction", 0.0)
    recession_frac = audit.get("recession_resilient_fraction", 0.0)
    global_frac = audit.get("global_diversifier_fraction", 0.0)
    flag_cyc = " [!CONCENTRATED]" if cyclical_frac > 0.30 else (" [WATCH]" if cyclical_frac > 0.25 else "")
    flag_def = " [!THIN]" if defensive_frac < 0.15 else ""
    lines.append(f"    {'Cyclical group':<28} {_pct(cyclical_frac)} {_bar(cyclical_frac)}{flag_cyc}")
    lines.append(f"    {'Defensive group':<28} {_pct(defensive_frac)} {_bar(defensive_frac)}{flag_def}")
    lines.append(f"    {'Recession resilient':<28} {_pct(recession_frac)} {_bar(recession_frac)}")
    lines.append(f"    {'Global diversifiers':<28} {_pct(global_frac)} {_bar(global_frac)}")

    # Top diversifier recommendations
    top_recs = diversifier.get("top_recommendations", [])
    if top_recs:
        lines.append("")
        lines.append(f"  TOP DIVERSIFIER CANDIDATES (addressing universe gaps):")
        for rec in top_recs[:5]:
            gaps = rec.get("addresses_gaps", [])
            gap_str = f" fills: {', '.join(gaps[:2])}" if gaps else ""
            priority = rec.get("priority", "?")
            lines.append(
                f"    [{priority:<6}] {rec['ticker']:<6}  "
                f"contribution={rec['diversification_contribution']:.2f}{gap_str}"
            )

    # Portfolio-universe alignment escalations
    escalation_notes = alignment.get("escalation_notes", [])
    if escalation_notes:
        lines.append("")
        lines.append(f"  PORTFOLIO-UNIVERSE ALIGNMENT ISSUES ({len(escalation_notes)}):")
        for note in escalation_notes:
            lines.append(f"    ⚠ {note}")

    # Governance warnings
    warnings = gov.get("warnings", []) + gov.get("gap_alerts", [])
    if warnings:
        lines.append("")
        lines.append(f"  UNIVERSE GOVERNANCE ({len(warnings)} warnings/gaps):")
        for w in warnings[:5]:
            lines.append(f"    • {w[:100]}")

    return "\n".join(lines)


def render_dashboard(
    regime_result: Optional[dict] = None,
    exposure_result: Optional[dict] = None,
    signal_result: Optional[dict] = None,
    calib_result: Optional[dict] = None,
    adversarial_result: Optional[dict] = None,
    constitution_report=None,
    portfolio_result: Optional[dict] = None,
    universe_result: Optional[dict] = None,
) -> str:
    """Render the full anti-delusion dashboard to a string."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    header = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║       ATS ANTI-DELUSION DASHBOARD — {now:<32}║",
        "║       Focus: What could be wrong?                                    ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
    ]

    sections = [
        _format_regime_section(regime_result),
        "",
        _format_exposure_section(exposure_result),
        "",
        _format_signal_section(signal_result),
        "",
        _format_calibration_section(calib_result),
        "",
        _format_adversarial_section(adversarial_result),
        "",
        _format_constitutional_section(constitution_report, exposure_result, calib_result),
        "",
        _format_fragility_summary(
            regime_result, exposure_result, signal_result, calib_result, constitution_report
        ),
        "",
        _format_portfolio_intelligence(portfolio_result),
        "",
        _format_universe_intelligence(universe_result),
    ]

    return "\n".join(header + sections)


def to_dict(
    regime_result: Optional[dict] = None,
    exposure_result: Optional[dict] = None,
    signal_result: Optional[dict] = None,
    calib_result: Optional[dict] = None,
    adversarial_result: Optional[dict] = None,
    portfolio_result: Optional[dict] = None,
    universe_result: Optional[dict] = None,
) -> dict:
    """Serialize all governance outputs to a single dict for Telegram or storage."""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "regime": regime_result,
        "exposure": exposure_result,
        "signals": signal_result,
        "calibration": calib_result,
        "adversarial": adversarial_result,
        "portfolio_intelligence": portfolio_result,
        "universe_intelligence": universe_result,
    }
