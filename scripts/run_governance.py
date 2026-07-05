#!/usr/bin/env python3
"""Governance pipeline runner — Phase II anti-delusion layer.

Runs all 7 governance components and outputs the anti-delusion dashboard.

Usage:
  python scripts/run_governance.py                  # full run, no adversarial
  python scripts/run_governance.py --adversarial    # include LLM critique (Haiku call)
  python scripts/run_governance.py --no-persist     # run without writing to data/governance/
  python scripts/run_governance.py --json           # output JSON instead of CLI report

Intended cadence: weekly (same day as screener run).
Cost: ~$0.001 per run (only when --adversarial is passed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root or scripts/ directory
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from scripts._common import get_print
print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

from src.governance.constitution import load_constitution, run_all_checks
from src.governance.regime import run_regime_engine
from src.governance.exposure import run_exposure_analysis
from src.governance.calibration import run_calibration
from src.governance.signal_tracker import run_signal_tracker
from src.governance.adversarial import run_adversarial_review, load_latest_adversarial
from src.governance.dashboard import render_dashboard, to_dict
from src.portfolio.exposure_engine import run_portfolio_exposure
from src.portfolio.factor_engine import run_factor_analysis
from src.portfolio.survivability_engine import compute_survivability
from src.portfolio.portfolio_stress import run_portfolio_stress
from src.governance.concentration_governor import (
    check_current_portfolio,
    compute_escalation_triggers,
)
from src.universe.universe_balance_audit import run_universe_audit
from src.universe.universe_governor import assess_universe_balance
from src.universe.candidate_diversifier_engine import (
    recommend_diversifiers,
    check_universe_portfolio_alignment,
)
from src.governance.attribution_log import log_governance_run
from src.version import version_dict


def _build_constitution_report(exposure_result: dict, calib_result: dict):
    """Compute constitutional report from live paper positions and exposure analysis.

    Uses paper position confidence tiers (not universe-wide signal log), since
    satellite capital limits apply to what we're actually holding.
    """
    import yaml

    tickers = exposure_result.get("tickers", [])
    n = len(tickers)

    position_weights = {t: 1.0 / n for t in tickers} if n > 0 else {}
    theme_weights = exposure_result.get("theme_weights", {})
    factor_weights = exposure_result.get("factor_weights", {})

    # Load confidence tiers from paper positions directly
    positions_path = _ROOT / "data" / "paper_positions.yaml"
    confidence_counts: dict[str, int] = {}
    if positions_path.exists():
        with open(positions_path) as f:
            data = yaml.safe_load(f) or {}
        for pos in data.get("positions", []):
            tier = pos.get("entry_confidence", "UNKNOWN")
            confidence_counts[tier] = confidence_counts.get(tier, 0) + 1
    else:
        # Fallback to universe-wide distribution from signal log
        confidence_counts = calib_result.get("confidence_distribution", {})

    # Rating-distribution governor (PART D): counts from the latest screen summary.
    rating_counts = _latest_rating_counts()

    return run_all_checks(
        position_weights=position_weights,
        theme_weights=theme_weights,
        factor_weights=factor_weights,
        confidence_counts=confidence_counts,
        rating_counts=rating_counts or None,
    )


def _latest_rating_counts() -> dict[str, int]:
    """Rating counts from the most recent runs/_screen/*/summary.json (empty if none)."""
    import json
    summaries = sorted((_ROOT / "runs" / "_screen").glob("*/summary.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if not summaries:
        return {}
    try:
        data = json.loads(summaries[0].read_text())
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for r in data.get("results", []):
        rating = r.get("rating")
        if rating in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"):
            counts[rating] = counts.get(rating, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description="ATS Phase II governance pipeline")
    parser.add_argument(
        "--adversarial",
        action="store_true",
        help="Run adversarial review (requires ANTHROPIC_API_KEY, costs ~$0.001)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run without writing to data/governance/",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of CLI report",
    )
    parser.add_argument(
        "--no-correlations",
        action="store_true",
        help="Skip rolling correlation fetch (faster, no network for exposure step)",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="Run portfolio intelligence layer (exposure engine, survivability, stress tests)",
    )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Run universe intelligence layer (archetype audit, diversifier recommendations)",
    )
    args = parser.parse_args()

    persist = not args.no_persist

    print("[governance] Loading constitution...", file=sys.stderr)
    try:
        load_constitution()
    except Exception as e:
        print(f"[governance] CONSTITUTIONAL FAILURE: {e}", file=sys.stderr)
        sys.exit(1)

    print("[governance] Running regime engine...", file=sys.stderr)
    try:
        regime_result = run_regime_engine(persist=persist)
        print(
            f"[governance]   Leading regime: {regime_result['leading_regime']} "
            f"({regime_result['confidence']:.1%} confidence)",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[governance] Regime engine failed: {e}", file=sys.stderr)
        regime_result = None

    print("[governance] Running exposure analysis...", file=sys.stderr)
    exposure_result = run_exposure_analysis(
        fetch_correlations=not args.no_correlations,
        persist=persist,
    )
    print(
        f"[governance]   {exposure_result['n_positions']} positions, "
        f"{len(exposure_result['warnings'])} warnings",
        file=sys.stderr,
    )

    print("[governance] Running confidence calibration...", file=sys.stderr)
    calib_result = run_calibration(persist=persist)
    print(
        f"[governance]   {calib_result['total_signal_entries']} signal entries, "
        f"{calib_result['total_closed_trades']} closed trades",
        file=sys.stderr,
    )

    print("[governance] Running signal tracker...", file=sys.stderr)
    signal_result = run_signal_tracker(persist=persist)

    print("[governance] Running constitutional checks...", file=sys.stderr)
    constitution_report = _build_constitution_report(exposure_result, calib_result)
    if not constitution_report.is_compliant:
        print(
            f"[governance]   {len(constitution_report.violations)} CONSTITUTIONAL VIOLATIONS",
            file=sys.stderr,
        )

    # ── Portfolio intelligence layer (Phase II) ────────────────────────────
    portfolio_result = None
    if args.portfolio:
        print("[governance] Running portfolio intelligence layer...", file=sys.stderr)
        try:
            tickers = exposure_result.get("tickers", [])
            if tickers:
                port_exposure = run_portfolio_exposure(tickers)
                factor_analysis = run_factor_analysis(tickers)
                survivability = compute_survivability(tickers)
                stress = run_portfolio_stress(tickers)

                # Escalation triggers (concentration + survivability)
                escalation_triggers = compute_escalation_triggers(
                    tickers,
                    survivability_score=survivability.survivability_score,
                    expected_max_drawdown=survivability.estimated_max_drawdown,
                )

                # Merge concentration governor check
                gov_decision = check_current_portfolio(tickers)
                escalation_triggers.extend(
                    [f"CONCENTRATION_BLOCK: {r}" for r in gov_decision.block_reasons]
                )

                portfolio_result = {
                    "exposure": port_exposure,
                    "survivability": {
                        "survivability_score": survivability.survivability_score,
                        "classification": survivability.classification,
                        "estimated_max_drawdown": survivability.estimated_max_drawdown,
                        "effective_bets": survivability.effective_bets,
                        "cluster_contagion_risk": survivability.cluster_contagion_risk,
                        "component_breakdown": survivability.component_breakdown,
                        "escalation_required": survivability.escalation_required,
                    },
                    "stress": {
                        "worst_scenario": stress.worst_scenario,
                        "worst_case_drawdown": stress.worst_case_drawdown,
                        "portfolio_classification": stress.portfolio_classification,
                        "average_drawdown": stress.average_drawdown,
                        "always_vulnerable": stress.always_vulnerable,
                        "always_resilient": stress.always_resilient,
                        "escalation_required": stress.escalation_required,
                        "scenario_summary": {
                            name: {
                                "drawdown": r.estimated_portfolio_drawdown,
                                "classification": r.classification,
                                "vulnerable": r.vulnerable_positions,
                            }
                            for name, r in stress.scenarios.items()
                        },
                    },
                    "factor": {
                        "portfolio_factors": factor_analysis.portfolio_factors,
                        "most_concentrated_factor": factor_analysis.most_concentrated_factor,
                        "most_concentrated_score": factor_analysis.most_concentrated_score,
                        "factor_dominance_score": factor_analysis.factor_dominance_score,
                        "warnings": factor_analysis.warnings,
                    },
                    "concentration_decision": gov_decision.decision,
                    "escalation_triggers": escalation_triggers,
                }

                n_escalations = len(escalation_triggers)
                print(
                    f"[governance]   effective_bets={survivability.effective_bets}  "
                    f"survivability={survivability.survivability_score:.0f}/100 "
                    f"[{survivability.classification}]  "
                    f"worst_scenario={stress.worst_scenario}  "
                    f"escalations={n_escalations}",
                    file=sys.stderr,
                )
                if escalation_triggers:
                    print("[governance]   ESCALATION TRIGGERS:", file=sys.stderr)
                    for trigger in escalation_triggers:
                        print(f"[governance]     ⚠ {trigger}", file=sys.stderr)
            else:
                print("[governance]   No positions found — skipping portfolio layer", file=sys.stderr)
        except Exception as e:
            print(f"[governance] Portfolio intelligence failed: {e}", file=sys.stderr)
            portfolio_result = None

    # ── Universe intelligence layer (Phase III) ───────────────────────────
    universe_result = None
    if args.universe:
        print("[governance] Running universe intelligence layer...", file=sys.stderr)
        try:
            from pathlib import Path
            import yaml
            _universe_path = _ROOT / "config" / "universe.yaml"
            _taxonomy_path = _ROOT / "config" / "universe_taxonomy.yaml"
            with open(_universe_path) as f:
                u_cfg = yaml.safe_load(f)
            universe_tickers = [t.upper() for t in u_cfg.get("universe", [])]

            audit = run_universe_audit(universe_tickers, _taxonomy_path)
            gov_result = assess_universe_balance(universe_tickers, _taxonomy_path)
            diversifier = recommend_diversifiers(universe_tickers, _taxonomy_path, n=8)

            portfolio_tickers = exposure_result.get("tickers", [])
            alignment = check_universe_portfolio_alignment(
                portfolio_tickers, universe_tickers, _taxonomy_path
            )

            universe_result = {
                "audit": {
                    "n_tickers": audit.n_tickers,
                    "archetype_exposures": audit.archetype_exposures,
                    "cyclicality_distribution": audit.cyclicality_distribution,
                    "avg_cyclicality": audit.avg_cyclicality,
                    "avg_defensiveness": audit.avg_defensiveness,
                    "defensive_fraction": audit.defensive_fraction,
                    "recession_resilient_fraction": audit.recession_resilient_fraction,
                    "policy_fraction": audit.policy_fraction,
                    "leverage_fraction": audit.leverage_fraction,
                    "cyclical_fraction": audit.cyclical_fraction,
                    "global_diversifier_fraction": audit.global_diversifier_fraction,
                    "overrepresented_archetypes": audit.overrepresented_archetypes,
                    "underrepresented_archetypes": audit.underrepresented_archetypes,
                    "absent_archetypes": audit.absent_archetypes,
                    "diversification_gaps": audit.diversification_gaps,
                    "balance_score": audit.balance_score,
                    "universe_bias_summary": audit.universe_bias_summary,
                    "escalation_triggers": audit.escalation_triggers,
                },
                "governance": {
                    "warnings": gov_result.warnings,
                    "gap_alerts": gov_result.gap_alerts,
                    "diversity_score": gov_result.diversity_score,
                    "escalation_triggers": gov_result.escalation_triggers,
                },
                "diversifier": {
                    "top_recommendations": [
                        {
                            "ticker": r.ticker,
                            "archetype_memberships": r.archetype_memberships,
                            "diversification_contribution": r.diversification_contribution,
                            "addresses_gaps": r.addresses_gaps,
                            "rationale": r.rationale,
                            "priority": r.priority,
                        }
                        for r in diversifier.top_recommendations
                    ],
                    "addressed_gaps": diversifier.addressed_gaps,
                    "remaining_gaps": diversifier.remaining_gaps,
                },
                "alignment": alignment,
            }

            n_gaps = len(audit.absent_archetypes)
            n_overrep = len(audit.overrepresented_archetypes)
            print(
                f"[governance]   universe={audit.n_tickers} tickers  "
                f"balance={audit.balance_score:.2f}  "
                f"absent={n_gaps}  overrep={n_overrep}  "
                f"cyclical={audit.cyclical_fraction:.0%}",
                file=sys.stderr,
            )
            if audit.escalation_triggers:
                print("[governance]   UNIVERSE ESCALATION TRIGGERS:", file=sys.stderr)
                for trigger in audit.escalation_triggers:
                    print(f"[governance]     ⚠ {trigger}", file=sys.stderr)
        except Exception as e:
            print(f"[governance] Universe intelligence failed: {e}", file=sys.stderr)
            universe_result = None

    adversarial_result = None
    if args.adversarial:
        print("[governance] Running adversarial review (Claude Haiku)...", file=sys.stderr)
        warnings = exposure_result.get("warnings", [])
        adversarial_result = run_adversarial_review(warnings=warnings, persist=persist)
        print(
            f"[governance]   Status: {adversarial_result.get('status')}",
            file=sys.stderr,
        )
    else:
        # Load last persisted adversarial if available
        adversarial_result = load_latest_adversarial()

    ver = version_dict()

    if args.json:
        output = to_dict(
            regime_result=regime_result,
            exposure_result=exposure_result,
            signal_result=signal_result,
            calib_result=calib_result,
            adversarial_result=adversarial_result,
            portfolio_result=portfolio_result,
            universe_result=universe_result,
        )
        output["version"] = ver
        print(json.dumps(output, indent=2, default=str))
    else:
        report = render_dashboard(
            regime_result=regime_result,
            exposure_result=exposure_result,
            signal_result=signal_result,
            calib_result=calib_result,
            adversarial_result=adversarial_result,
            constitution_report=constitution_report,
            portfolio_result=portfolio_result,
            universe_result=universe_result,
            rating_counts=_latest_rating_counts(),
        )
        print(report)

    # ── Attribution log + governance journal ──────────────────────────────────
    if persist:
        all_escalations: list[str] = []
        if portfolio_result:
            all_escalations.extend(portfolio_result.get("escalation_triggers", []))
        if universe_result:
            all_escalations.extend(
                universe_result.get("governance", {}).get("escalation_triggers", [])
            )

        log_governance_run(
            regime=regime_result.get("leading_regime") if regime_result else None,
            regime_confidence=regime_result.get("confidence") if regime_result else None,
            n_positions=exposure_result.get("n_positions", 0),
            constitution_compliant=constitution_report.is_compliant,
            violations=[str(v) for v in constitution_report.violations],
            escalation_triggers=all_escalations,
            version_dict=ver,
        )

        # Per-run JSON snapshot for decision journal (governance_journal/)
        from datetime import datetime, UTC
        import os
        journal_dir = _ROOT / "data" / "governance_journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        journal_path = journal_dir / f"governance_{ts}.json"
        snapshot = {
            "timestamp": datetime.now(UTC).isoformat(),
            "version": ver,
            "regime": regime_result,
            "exposure": {
                "n_positions": exposure_result.get("n_positions"),
                "tickers": exposure_result.get("tickers", []),
                "warnings": exposure_result.get("warnings", []),
            },
            "constitution": {
                "is_compliant": constitution_report.is_compliant,
                "violations": [str(v) for v in constitution_report.violations],
            },
            "signal_quality": {
                "n_signal_entries": signal_result.get("n_signal_entries"),
                "any_decay_warning": signal_result.get("any_decay_warning"),
                "signals": {
                    k: {
                        "quality": v.get("overall_quality"),
                        "decay_warning": v.get("decay_warning"),
                    }
                    for k, v in signal_result.get("signals", {}).items()
                    if isinstance(v, dict)
                },
            } if signal_result else None,
            "calibration": {
                "total_closed_trades": calib_result.get("total_closed_trades"),
                "calibration_ready": calib_result.get("calibration_ready"),
                "status": calib_result.get("status"),
            } if calib_result else None,
            "escalation_triggers": all_escalations,
        }
        try:
            with open(journal_path, "w") as f:
                json.dump(snapshot, f, indent=2, default=str)
        except Exception as e:
            print(f"[governance] Journal write failed (non-fatal): {e}", file=sys.stderr)

    # Exit with error code if constitutional violations detected
    if not constitution_report.is_compliant:
        sys.exit(2)


if __name__ == "__main__":
    main()
