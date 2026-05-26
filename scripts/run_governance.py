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

from src.governance.constitution import load_constitution, run_all_checks
from src.governance.regime import run_regime_engine
from src.governance.exposure import run_exposure_analysis
from src.governance.calibration import run_calibration
from src.governance.signal_tracker import run_signal_tracker
from src.governance.adversarial import run_adversarial_review, load_latest_adversarial
from src.governance.dashboard import render_dashboard, to_dict


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

    return run_all_checks(
        position_weights=position_weights,
        theme_weights=theme_weights,
        factor_weights=factor_weights,
        confidence_counts=confidence_counts,
    )


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

    if args.json:
        output = to_dict(
            regime_result=regime_result,
            exposure_result=exposure_result,
            signal_result=signal_result,
            calib_result=calib_result,
            adversarial_result=adversarial_result,
        )
        print(json.dumps(output, indent=2, default=str))
    else:
        report = render_dashboard(
            regime_result=regime_result,
            exposure_result=exposure_result,
            signal_result=signal_result,
            calib_result=calib_result,
            adversarial_result=adversarial_result,
            constitution_report=constitution_report,
        )
        print(report)

    # Exit with error code if constitutional violations detected
    if not constitution_report.is_compliant:
        sys.exit(2)


if __name__ == "__main__":
    main()
