"""Recommendation calculator — deterministic financial math.

Layer 1 of the 3-layer recommendation engine (VYNN AI pattern):
  Calculator (this file) → Evidence → Validator

This file contains ZERO LLM calls. All math is deterministic and reproducible.
The LLM never invents numbers; it can only narrate around the FixedNumbers
produced here.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
import math


@dataclass(frozen=True)
class FixedNumbers:
    """Immutable container for all computed numbers.

    Once this is built, the values cannot be changed. The validator (layer 3)
    checks every number in LLM-generated narrative against this.
    """
    # Identity
    ticker: str
    current_price: float
    diluted_shares_mm: float

    # Valuation outputs
    dcf_price_gordon: float
    dcf_price_exit: float
    dcf_price_blended: float
    comps_price_median_ev_ebitda: float
    comps_price_75th_ev_ebitda: float
    comps_price_median_pe: float

    # Final outputs
    price_target_12m: float
    expected_return: float        # decimal, e.g. 0.12 = +12%
    rating: str                   # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL

    # Per-method ranges (low / mid / high)
    dcf_gordon_range: tuple[float, float, float]
    dcf_exit_range: tuple[float, float, float]
    comps_range: tuple[float, float, float]
    consensus_range: Optional[tuple[float, float, float]] = None

    # Score components (for transparency)
    valuation_gap: float = 0.0
    catalyst_score: float = 0.0
    risk_score: float = 0.0
    momentum_score: float = 0.0

    # Warnings emitted during construction (e.g. price floors applied)
    notes: tuple[str, ...] = ()

    # Confidence tier and flags
    confidence: str = "UNKNOWN"
    confidence_flags: list = None

    def to_dict(self) -> dict:
        return asdict(self)


def compute_dcf_price(
    ufcf_stream: list[float],          # FY+1 to FY+5 unlevered FCF ($mm)
    terminal_year_fcf: float,
    terminal_growth: float,
    exit_multiple: float,
    terminal_year_ebitda: float,
    wacc: float,
    cash_plus_investments: float,
    debt: float,
    diluted_shares_mm: float,
    mid_year: bool = True,
) -> tuple[float, float, float]:
    """Compute DCF implied price per share.

    Returns: (gordon_price, exit_multiple_price, blended_price)
    """
    # Discount periods — mid-year convention if enabled
    if mid_year:
        periods = [0.5 + i for i in range(len(ufcf_stream))]
    else:
        periods = [1.0 + i for i in range(len(ufcf_stream))]

    # Sum PV of explicit-period UFCF
    pv_explicit = sum(
        fcf / ((1 + wacc) ** p) for fcf, p in zip(ufcf_stream, periods)
    )

    # Terminal — Gordon
    if wacc <= terminal_growth:
        # Pathological case — terminal growth >= WACC
        tv_gordon = float("nan")
        pv_tv_gordon = float("nan")
    else:
        tv_gordon = terminal_year_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_tv_gordon = tv_gordon / ((1 + wacc) ** periods[-1])

    # Terminal — Exit multiple
    tv_exit = terminal_year_ebitda * exit_multiple
    pv_tv_exit = tv_exit / ((1 + wacc) ** periods[-1])

    # Enterprise → Equity
    ev_gordon = pv_explicit + pv_tv_gordon
    ev_exit = pv_explicit + pv_tv_exit

    equity_gordon = ev_gordon + cash_plus_investments - debt
    equity_exit = ev_exit + cash_plus_investments - debt

    price_gordon = equity_gordon / diluted_shares_mm if diluted_shares_mm > 0 else float("nan")
    price_exit = equity_exit / diluted_shares_mm if diluted_shares_mm > 0 else float("nan")

    if math.isnan(price_gordon):
        price_blended = price_exit
    elif math.isnan(price_exit):
        price_blended = price_gordon
    else:
        price_blended = (price_gordon + price_exit) / 2.0

    return price_gordon, price_exit, price_blended


def compute_comps_price(
    target_ebitda: float,                # FY+1 EBITDA ($mm)
    target_net_income: float,            # FY+1 NI ($mm)
    peer_median_ev_ebitda: float,
    peer_75th_ev_ebitda: float,
    peer_median_pe: float,
    cash_plus_investments: float,
    debt: float,
    diluted_shares_mm: float,
) -> tuple[float, float, float]:
    """Compute comps-implied prices.

    Returns: (median_ev_ebitda_price, 75th_pct_ev_ebitda_price, median_pe_price)
    """
    # Method 1: peer median EV/EBITDA × target EBITDA → EV → equity → price
    ev_median = peer_median_ev_ebitda * target_ebitda
    equity_median = ev_median + cash_plus_investments - debt
    price_median = equity_median / diluted_shares_mm if diluted_shares_mm > 0 else float("nan")

    # Method 2: peer 75th pct EV/EBITDA
    ev_75th = peer_75th_ev_ebitda * target_ebitda
    equity_75th = ev_75th + cash_plus_investments - debt
    price_75th = equity_75th / diluted_shares_mm if diluted_shares_mm > 0 else float("nan")

    # Method 3: peer median P/E × target EPS
    target_eps = target_net_income / diluted_shares_mm if diluted_shares_mm > 0 else float("nan")
    price_pe = peer_median_pe * target_eps

    return price_median, price_75th, price_pe


def compute_price_target(
    dcf_gordon: float,
    dcf_exit: float,
    comps_median: float,
    comps_75th: float,
    comps_pe: float,
    consensus_midpoint: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
) -> float:
    """Blend valuation methods into a single 12-month price target.

    Default weighting:
      DCF Gordon: 25%
      DCF Exit: 25%
      Comps median EV/EBITDA: 20%
      Comps 75th pct: 10%
      Comps P/E: 10%
      Consensus (if available): 10%

    If consensus not provided, its weight is redistributed proportionally.
    """
    if weights is None:
        weights = {
            "dcf_gordon": 0.25,
            "dcf_exit": 0.25,
            "comps_median": 0.20,
            "comps_75th": 0.10,
            "comps_pe": 0.10,
            "consensus": 0.10,
        }

    prices = {
        "dcf_gordon": dcf_gordon,
        "dcf_exit": dcf_exit,
        "comps_median": comps_median,
        "comps_75th": comps_75th,
        "comps_pe": comps_pe,
    }
    if consensus_midpoint is not None:
        prices["consensus"] = consensus_midpoint

    # Filter out NaN values; redistribute their weights proportionally
    valid = {k: v for k, v in prices.items() if v is not None and not math.isnan(v)}
    total_weight = sum(weights[k] for k in valid)
    if total_weight == 0:
        return float("nan")

    pt = sum(weights[k] * v for k, v in valid.items()) / total_weight
    return pt


def classify_rating(expected_return: float, bands: dict[str, float]) -> str:
    """Map expected return → rating band.

    bands = {"strong_buy": 0.20, "buy": 0.10, "hold": -0.05, "sell": -0.20}
    """
    if expected_return > bands.get("strong_buy", 0.20):
        return "STRONG_BUY"
    elif expected_return > bands.get("buy", 0.10):
        return "BUY"
    elif expected_return > bands.get("hold", -0.05):
        return "HOLD"
    elif expected_return > bands.get("sell", -0.20):
        return "SELL"
    else:
        return "STRONG_SELL"


def assess_confidence(
    expected_return: float,
    n_peers_resolved: int,
    dcf_gordon: float,
    dcf_exit: float,
    comps_median: float,
    price_target: float,
) -> tuple[str, list[str]]:
    """Return (tier, reasons) — HIGH / MED / LOW / BROKEN."""
    import math
    flags = []

    # BROKEN — unusable output
    if price_target is None or price_target <= 0 or (isinstance(price_target, float) and math.isnan(price_target)):
        flags.append("price_target_non_positive")
        return "BROKEN", flags
    if n_peers_resolved == 0:
        flags.append("no_peers_resolved")

    # Method divergence
    methods = [v for v in [dcf_gordon, dcf_exit, comps_median] if v and v > 0 and not math.isnan(v)]
    cv = 0.0
    if len(methods) >= 2:
        mean = sum(methods) / len(methods)
        if mean > 0:
            var = sum((v - mean) ** 2 for v in methods) / len(methods)
            cv = (var ** 0.5) / mean
            if cv > 0.50:
                flags.append("methods_diverge_widely")
            elif cv > 0.25:
                flags.append("methods_diverge_moderately")

    if n_peers_resolved < 3 and n_peers_resolved > 0:
        flags.append("thin_peer_cohort")

    abs_ret = abs(expected_return) if expected_return is not None else 0
    if abs_ret > 0.50:
        flags.append("extreme_expected_return")
    elif abs_ret > 0.30:
        flags.append("large_expected_return")

    # Classify
    if "no_peers_resolved" in flags or "methods_diverge_widely" in flags:
        return "LOW", flags
    if "extreme_expected_return" in flags and "thin_peer_cohort" in flags:
        return "LOW", flags
    if "extreme_expected_return" in flags:
        return "MED", flags
    if "thin_peer_cohort" in flags or "large_expected_return" in flags or "methods_diverge_moderately" in flags:
        return "MED", flags
    return "HIGH", flags


def build_fixed_numbers(
    ticker: str,
    current_price: float,
    diluted_shares_mm: float,
    # DCF inputs
    ufcf_stream: list[float],
    terminal_year_fcf: float,
    terminal_year_ebitda: float,
    wacc: float,
    terminal_growth: float,
    exit_multiple: float,
    cash_plus_investments: float,
    debt: float,
    # Comps inputs
    target_ebitda: float,
    target_net_income: float,
    peer_median_ev_ebitda: float,
    peer_75th_ev_ebitda: float,
    peer_median_pe: float,
    # Optional
    consensus_low: Optional[float] = None,
    consensus_high: Optional[float] = None,
    # Sensitivity ranges (for the football field)
    dcf_gordon_low: Optional[float] = None,
    dcf_gordon_high: Optional[float] = None,
    dcf_exit_low: Optional[float] = None,
    dcf_exit_high: Optional[float] = None,
    # Rating bands
    rating_bands: Optional[dict[str, float]] = None,
    n_peers_resolved: int = 0,
    cohort_outlier: bool = False,
) -> FixedNumbers:
    """One-shot builder. Computes everything deterministically."""

    # DCF
    p_gordon, p_exit, p_blended = compute_dcf_price(
        ufcf_stream=ufcf_stream,
        terminal_year_fcf=terminal_year_fcf,
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple,
        terminal_year_ebitda=terminal_year_ebitda,
        wacc=wacc,
        cash_plus_investments=cash_plus_investments,
        debt=debt,
        diluted_shares_mm=diluted_shares_mm,
    )

    # Comps
    p_comps_med, p_comps_75th, p_comps_pe = compute_comps_price(
        target_ebitda=target_ebitda,
        target_net_income=target_net_income,
        peer_median_ev_ebitda=peer_median_ev_ebitda,
        peer_75th_ev_ebitda=peer_75th_ev_ebitda,
        peer_median_pe=peer_median_pe,
        cash_plus_investments=cash_plus_investments,
        debt=debt,
        diluted_shares_mm=diluted_shares_mm,
    )

    # Floor individual prices at zero (bandage — cross-cohort calibration is the real fix)
    _floor_notes: list[str] = []
    def _floor(val: float, name: str) -> float:
        if not math.isnan(val) and val < 0:
            _floor_notes.append(f"{name} floored from {val:.2f} to 0.00")
            return 0.0
        return val

    p_gordon = _floor(p_gordon, "dcf_price_gordon")
    p_exit = _floor(p_exit, "dcf_price_exit")
    if math.isnan(p_gordon):
        p_blended = p_exit
    elif math.isnan(p_exit):
        p_blended = p_gordon
    else:
        p_blended = (p_gordon + p_exit) / 2.0
    p_comps_med = _floor(p_comps_med, "comps_price_median_ev_ebitda")
    p_comps_75th = _floor(p_comps_75th, "comps_price_75th_ev_ebitda")
    p_comps_pe = _floor(p_comps_pe, "comps_price_median_pe")

    # Consensus midpoint (if range supplied)
    consensus_mid = None
    consensus_range = None
    if consensus_low is not None and consensus_high is not None:
        consensus_mid = (consensus_low + consensus_high) / 2.0
        consensus_range = (consensus_low, consensus_mid, consensus_high)

    # Price target — blended
    pt = compute_price_target(
        dcf_gordon=p_gordon,
        dcf_exit=p_exit,
        comps_median=p_comps_med,
        comps_75th=p_comps_75th,
        comps_pe=p_comps_pe,
        consensus_midpoint=consensus_mid,
    )

    pt = _floor(pt, "price_target_12m")
    expected_return = pt / current_price - 1.0 if current_price > 0 else float("nan")
    valuation_gap = expected_return

    rating = classify_rating(
        expected_return=expected_return,
        bands=rating_bands or {"strong_buy": 0.20, "buy": 0.10, "hold": -0.05, "sell": -0.20},
    )

    conf, conf_flags = assess_confidence(
        expected_return=expected_return,
        n_peers_resolved=n_peers_resolved,
        dcf_gordon=p_gordon,
        dcf_exit=p_exit,
        comps_median=p_comps_med,
        price_target=pt,
    )

    # Cohort outlier: target's own EV/EBITDA far exceeds peer median — model
    # multiples are not representative, so cap confidence at LOW.
    if cohort_outlier:
        if "target_ev_ebitda_2x_peer_median" not in conf_flags:
            conf_flags.append("target_ev_ebitda_2x_peer_median")
        if conf not in ("BROKEN", "LOW"):
            conf = "LOW"

    # Build ranges for football field
    if dcf_gordon_low is None or dcf_gordon_high is None:
        dcf_gordon_low = p_gordon * 0.85
        dcf_gordon_high = p_gordon * 1.30
    if dcf_exit_low is None or dcf_exit_high is None:
        dcf_exit_low = p_exit * 0.85
        dcf_exit_high = p_exit * 1.20

    dcf_gordon_range = (dcf_gordon_low, p_gordon, dcf_gordon_high)
    dcf_exit_range = (dcf_exit_low, p_exit, dcf_exit_high)
    comps_range = (
        min(p_comps_med, p_comps_pe),
        (p_comps_med + p_comps_75th + p_comps_pe) / 3.0,
        max(p_comps_75th, p_comps_pe),
    )

    return FixedNumbers(
        ticker=ticker,
        current_price=current_price,
        diluted_shares_mm=diluted_shares_mm,
        dcf_price_gordon=p_gordon,
        dcf_price_exit=p_exit,
        dcf_price_blended=p_blended,
        comps_price_median_ev_ebitda=p_comps_med,
        comps_price_75th_ev_ebitda=p_comps_75th,
        comps_price_median_pe=p_comps_pe,
        price_target_12m=pt,
        expected_return=expected_return,
        rating=rating,
        dcf_gordon_range=dcf_gordon_range,
        dcf_exit_range=dcf_exit_range,
        comps_range=comps_range,
        consensus_range=consensus_range,
        valuation_gap=valuation_gap,
        notes=tuple(_floor_notes),
        confidence=conf,
        confidence_flags=conf_flags,
    )


if __name__ == "__main__":
    # Smoke test using the AGX numbers from the prior session
    fixed = build_fixed_numbers(
        ticker="AGX",
        current_price=700.0,
        diluted_shares_mm=14.0,
        ufcf_stream=[95, 123, 129, 133, 133],
        terminal_year_fcf=133,
        terminal_year_ebitda=176,
        wacc=0.11,
        terminal_growth=0.025,
        exit_multiple=15.0,
        cash_plus_investments=895.0,
        debt=0.0,
        target_ebitda=165,
        target_net_income=128,
        peer_median_ev_ebitda=14.8,
        peer_75th_ev_ebitda=21.2,
        peer_median_pe=27.9,
        consensus_low=220,
        consensus_high=321,
    )
    print(f"Ticker: {fixed.ticker}")
    print(f"Current price: ${fixed.current_price:.2f}")
    print(f"DCF Gordon: ${fixed.dcf_price_gordon:.2f}")
    print(f"DCF Exit:   ${fixed.dcf_price_exit:.2f}")
    print(f"Comps med:  ${fixed.comps_price_median_ev_ebitda:.2f}")
    print(f"Comps 75th: ${fixed.comps_price_75th_ev_ebitda:.2f}")
    print(f"Comps P/E:  ${fixed.comps_price_median_pe:.2f}")
    print(f"PT 12m:     ${fixed.price_target_12m:.2f}")
    print(f"Expected return: {fixed.expected_return*100:+.1f}%")
    print(f"Rating:     {fixed.rating}")
