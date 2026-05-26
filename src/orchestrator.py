"""Pipeline orchestrator — wires data → model → valuation → summary.

Hard constraint: this orchestrator NEVER places orders. It produces
a recommendation and writes it to disk. The human gate (you) acts on it.
"""
from __future__ import annotations
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .data.edgar_client import fetch_company, extract_historical_metrics
from .agents.model import build_model
from .agents.valuation import value_ticker
from .engine.calculator import assess_confidence_v2
from .governance.dcf_skeptic import run_stress_analysis

_EXIT_FLOOR = 8.0
_EXIT_CAP = 30.0


def resolve_exit_multiple(
    peer_median_ev_ebitda: float,
    n_peers_resolved: int,
    default: float = 12.0,
    floor: float = _EXIT_FLOOR,
    cap: float = _EXIT_CAP,
) -> tuple[float, str]:
    """Return (exit_multiple, source) for the DCF terminal-year exit multiple.

    Uses the peer cohort's median EV/EBITDA when ≥3 peers resolved, clamped
    to [floor, cap]. Falls back to the default when the cohort is too thin.
    """
    if n_peers_resolved >= 3:
        clamped = max(floor, min(cap, peer_median_ev_ebitda))
        return clamped, f"peer_median_{n_peers_resolved}peers"
    return default, "default"


def _load_settings(path: Path | None = None) -> dict:
    """Load settings.yaml — falls back to package default."""
    if path is None:
        path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _fetch_live_price(ticker: str) -> Optional[float]:
    """Pull live market price via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        for key in ("regularMarketPrice", "currentPrice", "previousClose"):
            v = info.get(key)
            if v is not None and v > 0:
                return float(v)
    except Exception:
        return None
    return None


def _fetch_target_ev_ebitda(ticker: str) -> Optional[float]:
    """Pull target's own EV/EBITDA via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        v = info.get("enterpriseToEbitda")
        if v is not None and 0 < v < 500:
            return float(v)
        # Fallback: compute from components
        mc = info.get("marketCap") or 0
        debt = info.get("totalDebt") or 0
        cash = info.get("totalCash") or 0
        ebitda = info.get("ebitda") or 0
        if mc > 0 and ebitda > 0:
            ev = mc + debt - cash
            return ev / ebitda if ebitda > 0 else None
    except Exception:
        return None
    return None


def _fetch_diluted_shares(ticker: str) -> Optional[float]:
    """Pull diluted shares outstanding (in millions) via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        for key in ("sharesOutstanding", "impliedSharesOutstanding"):
            v = info.get(key)
            if v is not None and v > 0:
                return float(v) / 1e6
    except Exception:
        return None
    return None


def _safe_json(obj):
    """Convert dataclasses, tuples, etc. to JSON-safe dict."""
    if is_dataclass(obj):
        return _safe_json(asdict(obj))
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    return obj


def run_pipeline(
    ticker: str,
    output_root: Path | None = None,
    settings_path: Path | None = None,
    override_price: Optional[float] = None,
    override_shares_mm: Optional[float] = None,
    peer_multiples: Optional[dict] = None,
    consensus_range: Optional[tuple[float, float]] = None,
) -> dict:
    """Run the full pipeline for one ticker. Returns a result dict.

    Side effects: writes model.xlsx, recommendation.json under runs/{ticker}/{ts}/
    """
    settings = _load_settings(settings_path)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_root = output_root or Path(settings.get("paths", {}).get("runs_dir", "runs"))
    run_dir = output_root / ticker.upper() / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{ticker}] Pipeline start → {run_dir}")

    # Stage 1: Data fetch
    print(f"[{ticker}] Stage 1: fetching EDGAR data...")
    cd = fetch_company(ticker)
    if cd.notes:
        print(f"[{ticker}] Notes: {cd.notes}")

    # Stage 2: Price + shares
    print(f"[{ticker}] Stage 2: fetching market data...")
    current_price = override_price if override_price is not None else _fetch_live_price(ticker)
    diluted_shares_mm = override_shares_mm if override_shares_mm is not None else _fetch_diluted_shares(ticker)
    if current_price is None or diluted_shares_mm is None:
        raise RuntimeError(
            f"Missing market data for {ticker}: price={current_price}, shares_mm={diluted_shares_mm}. "
            f"Pass --price and --shares overrides on the CLI."
        )
    print(f"[{ticker}]   current_price=${current_price:.2f}  shares={diluted_shares_mm:.1f}M")

    # Stage 3: Build model
    print(f"[{ticker}] Stage 3: building financial model...")
    proj_cfg = settings.get("projections", {})
    growth_decay = proj_cfg.get("revenue_growth_decay")
    model_path = run_dir / "model.xlsx"
    model = build_model(
        cd=cd,
        output_path=model_path,
        growth_decay=growth_decay,
        diluted_shares_mm=diluted_shares_mm,
    )

    # Stage 4: Valuation
    print(f"[{ticker}] Stage 4: running valuation...")
    dcf_cfg = settings.get("dcf", {})

    # Stage 4a: Resolve peer cohort (Path B)
    n_peers_resolved = 0
    if peer_multiples is None:
        from .data.peer_multiples import get_peer_multiples_for_ticker
        pm = get_peer_multiples_for_ticker(ticker)
        n_peers_resolved = pm.n_peers_resolved
        peer_multiples = {
            "median_ev_ebitda": pm.median_ev_ebitda,
            "p75_ev_ebitda": pm.p75_ev_ebitda,
            "median_pe": pm.median_pe,
        }
        if pm.n_peers_resolved > 0:
            print(f"[{ticker}]   peer cohort: {pm.n_peers_resolved} peers, "
                  f"median EV/EBITDA={pm.median_ev_ebitda:.1f}x, "
                  f"median P/E={pm.median_pe:.1f}x")
        else:
            print(f"[{ticker}]   peer cohort: using defaults ({pm.notes[0] if pm.notes else ''})")

    wacc = (dcf_cfg.get("risk_free_rate", 0.045)
            + dcf_cfg.get("default_beta", 1.20)
            * dcf_cfg.get("equity_risk_premium", 0.055))
    terminal_growth = dcf_cfg.get("terminal_growth", 0.025)
    exit_multiple_used, exit_multiple_source = resolve_exit_multiple(
        peer_median_ev_ebitda=peer_multiples.get("median_ev_ebitda", 12.0),
        n_peers_resolved=n_peers_resolved,
        default=dcf_cfg.get("exit_multiple", 12.0),
    )
    print(f"[{ticker}]   exit multiple: {exit_multiple_used:.1f}x ({exit_multiple_source})")

    # Stage 4b: cohort outlier check — if target trades at >1.5× peer median
    # EV/EBITDA, the peer multiples are not representative; cap confidence at LOW.
    cohort_outlier = False
    target_ev_ebitda = _fetch_target_ev_ebitda(ticker)
    peer_median = peer_multiples.get("median_ev_ebitda", 0)
    if target_ev_ebitda is not None and peer_median > 0:
        ratio = target_ev_ebitda / peer_median
        if ratio > 1.5:
            cohort_outlier = True
            print(f"[{ticker}]   cohort outlier: target EV/EBITDA={target_ev_ebitda:.1f}x "
                  f"vs peer median {peer_median:.1f}x (ratio={ratio:.2f}x) → confidence capped at LOW")

    fixed = value_ticker(
        model=model,
        current_price=current_price,
        wacc=wacc,
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple_used,
        peer_multiples=peer_multiples,
        consensus_range=consensus_range,
        excel_path=model_path,
        n_peers_resolved=n_peers_resolved,
        cohort_outlier=cohort_outlier,
    )

    # Stage 4c: Phase II — DCF skepticism overlay
    print(f"[{ticker}] Stage 4c: running DCF stress analysis...")
    hist_metrics = extract_historical_metrics(cd)
    historical_ebitda_mm: list[float] = []
    for period in sorted(hist_metrics.keys()):
        m = hist_metrics[period]
        oi = m.get("operating_income")
        dep = m.get("depreciation")
        if oi is not None and oi > 0:
            historical_ebitda_mm.append(
                (oi + (dep if dep is not None else 0)) / 1e6
            )

    stress = run_stress_analysis(
        ticker=ticker,
        current_price=current_price,
        raw_intrinsic_value=fixed.price_target_12m,
        ufcf_stream=model.ufcf_stream,
        terminal_ebitda_mm=model.terminal_ebitda,
        wacc=wacc,
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple_used,
        cash_plus_investments_mm=model.cash_plus_investments,
        debt_mm=model.debt,
        diluted_shares_mm=model.diluted_shares_mm,
        historical_ebitda_mm=historical_ebitda_mm,
    )
    print(
        f"[{ticker}]   stress: gate={stress.upside_gate}  "
        f"adj_upside={stress.adjusted_upside*100:+.1f}%  "
        f"fragility={stress.fragility_score:.2f}"
    )
    if stress.review_flags:
        for flag in stress.review_flags:
            print(f"[{ticker}]   [FLAG] {flag}")

    # Stage 4d: Phase II — enhanced confidence scoring (5-tier)
    net_debt_ebitda = (
        model.debt / model.fy1_ebitda
        if model.fy1_ebitda and model.fy1_ebitda > 0
        else 0.0
    )
    conf_v2, conf_v2_flags = assess_confidence_v2(
        expected_return=fixed.expected_return,
        n_peers_resolved=n_peers_resolved,
        dcf_gordon=fixed.dcf_price_gordon,
        dcf_exit=fixed.dcf_price_exit,
        comps_median=fixed.comps_price_median_ev_ebitda,
        price_target=fixed.price_target_12m,
        is_cyclical=stress.is_cyclical,
        cyclical_peak_detected=stress.cyclical_peak_detected,
        upside_gate=stress.upside_gate,
        wacc_destroys_upside=stress.wacc_destroys_upside,
        net_debt_ebitda=net_debt_ebitda,
        multiple_fragility_warning=stress.multiple_fragility_warning,
        fragility_score=stress.fragility_score,
    )
    print(f"[{ticker}]   confidence_v2={conf_v2}  (legacy={fixed.confidence})")

    # Stage 5: Persist outputs
    print(f"[{ticker}] Stage 5: writing recommendation.json...")
    result = {
        "ticker": ticker.upper(),
        "_run_dir": str(run_dir),
        "company_name": cd.name,
        "valuation_date": ts,
        "current_price": current_price,
        # Legacy confidence (backward-compatible)
        "rating": fixed.rating,
        "confidence": fixed.confidence,
        "confidence_flags": fixed.confidence_flags,
        "price_target_12m": fixed.price_target_12m,
        "expected_return": fixed.expected_return,
        # Phase II: stress-adjusted decision-grade outputs
        "confidence_v2": conf_v2,
        "confidence_v2_flags": conf_v2_flags,
        "stress_adjusted_pt": stress.adjusted_intrinsic_value,
        "stress_adjusted_upside": stress.adjusted_upside,
        "upside_gate": stress.upside_gate,
        "fragility_score": stress.fragility_score,
        "dcf_stress": {
            "raw_upside": stress.raw_upside,
            "adjusted_upside": stress.adjusted_upside,
            "downside_case": stress.downside_case,
            "wacc_destroys_upside": stress.wacc_destroys_upside,
            "cyclical_peak_detected": stress.cyclical_peak_detected,
            "cycle_inflation_pct": stress.cycle_inflation_pct,
            "multiple_fragility_warning": stress.multiple_fragility_warning,
            "normalization_method": stress.normalization_method,
            "review_flags": stress.review_flags,
            "sensitivity_summary": stress.sensitivity_summary,
        },
        "net_debt_ebitda": round(net_debt_ebitda, 2),
        # Underlying model and fixed numbers
        "fixed_numbers": _safe_json(fixed),
        "model_outputs": _safe_json(model),
        "notes": cd.notes,
        "files": {
            "model_xlsx": str(model_path.relative_to(output_root.parent) if output_root.parent in model_path.parents else model_path),
        },
        "assumptions": {
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "exit_multiple_used": exit_multiple_used,
            "exit_multiple_source": exit_multiple_source,
            "target_ev_ebitda": target_ev_ebitda,
            "peer_median_ev_ebitda": peer_median,
            "cohort_outlier": cohort_outlier,
        },
        "constraints": {
            "no_orders_placed": True,
            "no_live_pnl_learning": True,
        },
    }

    rec_path = run_dir / "recommendation.json"
    with open(rec_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[{ticker}] DONE  →  {fixed.rating}  PT=${fixed.price_target_12m:.0f}  return={fixed.expected_return*100:+.1f}%")

    return result


if __name__ == "__main__":
    # Direct invocation: python -m src.orchestrator AGX
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AGX"
    res = run_pipeline(ticker)
    print(json.dumps({"ticker": res["ticker"], "rating": res["rating"], "pt": res["price_target_12m"]}, indent=2))
