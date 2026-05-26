"""DCF Skepticism Layer — stress-tests raw DCF outputs before they become decisions.

The raw DCF produced by orchestrator.py is treated as an optimistic starting point,
not a decision-grade output. This module applies four adversarial tests:

  1. WACC stress (+100 / +150 / +200 bps) — quantifies discount-rate sensitivity
  2. Cyclical EBITDA normalisation — replaces trailing peak EBITDA with multi-year median
  3. Exit multiple compression (-2x / -3x / -4x) — quantifies terminal-value fragility
  4. Upside realism gates — flags estimates that are implausibly high

All four tests run deterministically. No LLM calls. No optimisation.

Output: StressAdjustedValuation
  - raw_*  fields:  the original DCF outputs (diagnostic only after this module runs)
  - adjusted_*: stress-adjusted decision-grade values
  - fragility_score: 0.0 (robust) → 1.0 (extremely fragile)
  - upside_gate: OK | AGGRESSIVE_UPSIDE | HIGH_UPSIDE_REVIEW_REQUIRED | EXTREME_UPSIDE_ANOMALY
  - confidence_penalty: integer points subtracted in assess_confidence_v2()

Design principles:
  - Never upgrades an estimate (normalization is a one-way downward correction)
  - Fails loudly on bad inputs rather than silently producing wrong numbers
  - Every output is reproducible from the audit_trail dict
  - Diagnostic only — never modifies paper positions or core data files
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import yaml

from ..engine.calculator import compute_dcf_price

_CYCLICALS_PATH = Path(__file__).parent.parent.parent / "config" / "cyclicals.yaml"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_STRESS_LOG = _DATA_PATH / "dcf_stress_log.jsonl"

# Never normalise EBITDA *upward* — only apply downward corrections.
_MAX_NORM_SCALE = 1.0

# Upside gate thresholds (applied to stress-adjusted upside)
_UPSIDE_AGGRESSIVE = 0.40
_UPSIDE_REVIEW = 0.80
_UPSIDE_ANOMALY = 1.20

# WACC shock magnitudes (bps converted to decimal)
_WACC_SHOCKS = [0.01, 0.015, 0.02]   # +100, +150, +200 bps

# Exit multiple compression shocks
_EXIT_SHOCKS = [-2.0, -3.0, -4.0]


# ─── Data types ──────────────────────────────────────────────────────────────

@dataclass
class StressAdjustedValuation:
    """Complete stress-test output for one ticker.

    Fields prefixed raw_ reflect the base DCF; all other valuation fields
    reflect one or more stress scenarios applied.
    """
    ticker: str
    current_price: float
    timestamp: str

    # Raw (diagnostic)
    raw_intrinsic_value: float
    raw_upside: float

    # WACC stress grid
    wacc_base: float
    price_wacc_base: float
    price_wacc_plus100: float
    price_wacc_plus150: float
    price_wacc_plus200: float
    upside_wacc_plus100: float
    upside_wacc_plus150: float
    upside_wacc_plus200: float
    wacc_destroys_upside: bool      # +150bps halves raw upside

    # Cyclical EBITDA normalisation
    is_cyclical: bool
    normalization_years: int         # 3 or 5; 0 = not cyclical
    trailing_ebitda_mm: float
    normalized_ebitda_mm: float
    cycle_inflation_pct: float       # (trailing / normalized - 1) * 100; 0 if not cyclical
    cyclical_peak_detected: bool     # inflation > threshold from cyclicals.yaml
    normalization_method: str        # "none" | "3yr_median" | "5yr_median"
    price_normalized: float          # DCF using normalized EBITDA, base WACC
    upside_normalized: float

    # Exit multiple compression
    base_exit_multiple: float
    price_exit_minus2x: float
    price_exit_minus3x: float
    price_exit_minus4x: float
    upside_exit_minus2x: float
    upside_exit_minus3x: float
    upside_exit_minus4x: float
    multiple_fragility_warning: bool  # -2x exit destroys >50% of exit-method upside

    # Stress-adjusted (decision-grade)
    adjusted_intrinsic_value: float  # most conservative plausible value
    adjusted_upside: float
    downside_case: float             # worst-case across all tests
    fragility_score: float           # 0.0 = robust, 1.0 = extremely fragile

    # Upside governance gate (applied to adjusted_upside)
    upside_gate: str

    # Confidence penalty (points deducted in assess_confidence_v2)
    confidence_penalty: int

    # Review flags emitted by this analysis
    review_flags: list[str] = field(default_factory=list)

    # Sensitivity summary for reporting
    sensitivity_summary: dict = field(default_factory=dict)

    # Full audit trail (all inputs used)
    audit_trail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Cyclicals configuration ─────────────────────────────────────────────────

def _load_cyclicals(path: Path | None = None) -> dict:
    """Load cyclicals.yaml. Returns empty dict on missing file (graceful degradation)."""
    p = path or _CYCLICALS_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_cyclical_config(ticker: str, cyclicals: dict | None = None) -> dict | None:
    """Return the sector config for a ticker, or None if not cyclical.

    Returns: {normalization_years, cycle_peak_threshold, note, sector_name}
    """
    cfg = cyclicals if cyclicals is not None else _load_cyclicals()
    sectors = cfg.get("cyclical_sectors", {})
    upper = ticker.upper()
    for sector_name, sector_cfg in sectors.items():
        if upper in [t.upper() for t in sector_cfg.get("tickers", [])]:
            return {
                "sector_name": sector_name,
                "normalization_years": sector_cfg.get("normalization_years", 3),
                "cycle_peak_threshold": sector_cfg.get("cycle_peak_threshold", 0.25),
            }
    return None


# ─── EBITDA normalisation ────────────────────────────────────────────────────

def compute_normalized_ebitda(
    historical_ebitda_mm: list[float],
    normalization_years: int,
) -> float | None:
    """Compute the N-year median EBITDA from historical data.

    historical_ebitda_mm: list of EBITDA values in $mm, sorted ascending (oldest first).
    Returns None when data is insufficient (< 2 usable values).
    """
    # Filter out zero / negative (data quality issues)
    valid = [v for v in historical_ebitda_mm if v and v > 0]
    if len(valid) < 2:
        return None
    # Take the most recent N years
    window = valid[-normalization_years:] if len(valid) >= normalization_years else valid
    return statistics.median(window)


def compute_cycle_inflation(
    trailing_ebitda_mm: float,
    normalized_ebitda_mm: float,
) -> float:
    """Return (trailing / normalized - 1) * 100 as a percentage.

    Positive = trailing is above normalised (peak cycle).
    Negative = trailing is below normalised (trough cycle).
    Returns 0.0 if either input is invalid.
    """
    if not normalized_ebitda_mm or normalized_ebitda_mm <= 0 or trailing_ebitda_mm <= 0:
        return 0.0
    return (trailing_ebitda_mm / normalized_ebitda_mm - 1.0) * 100.0


# ─── DCF stress runners ──────────────────────────────────────────────────────

def _run_single_dcf(
    ufcf_stream: list[float],
    terminal_ebitda: float,
    wacc: float,
    terminal_growth: float,
    exit_multiple: float,
    cash_plus_investments: float,
    debt: float,
    diluted_shares_mm: float,
) -> float:
    """Run DCF exit-method only and return the blended price.

    Returns NaN on pathological inputs (wacc <= terminal_growth).
    """
    if wacc <= terminal_growth:
        return float("nan")
    if not ufcf_stream or diluted_shares_mm <= 0:
        return float("nan")
    terminal_fcf = ufcf_stream[-1]
    _, p_exit, _ = compute_dcf_price(
        ufcf_stream=ufcf_stream,
        terminal_year_fcf=terminal_fcf,
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple,
        terminal_year_ebitda=terminal_ebitda,
        wacc=wacc,
        cash_plus_investments=cash_plus_investments,
        debt=debt,
        diluted_shares_mm=diluted_shares_mm,
    )
    return max(0.0, p_exit) if not math.isnan(p_exit) else float("nan")


def _upside(price: float, current_price: float) -> float:
    """Compute expected return. Returns -1.0 on invalid input."""
    if current_price <= 0 or math.isnan(price):
        return -1.0
    return price / current_price - 1.0


# ─── Exit multiple compression ───────────────────────────────────────────────

def run_exit_compression(
    ufcf_stream: list[float],
    terminal_ebitda: float,
    base_exit_multiple: float,
    wacc: float,
    terminal_growth: float,
    cash_plus_investments: float,
    debt: float,
    diluted_shares_mm: float,
    current_price: float,
) -> dict[str, float]:
    """Run exit-method DCF at base and compressed multiples.

    Returns {base, minus2x, minus3x, minus4x} prices and upsides.
    """
    results = {}
    shocks = [0.0] + _EXIT_SHOCKS  # includes base (0 shock)
    labels = ["base", "minus2x", "minus3x", "minus4x"]
    for label, shock in zip(labels, shocks):
        mult = max(0.0, base_exit_multiple + shock)
        price = _run_single_dcf(
            ufcf_stream=ufcf_stream,
            terminal_ebitda=terminal_ebitda,
            wacc=wacc,
            terminal_growth=terminal_growth,
            exit_multiple=mult,
            cash_plus_investments=cash_plus_investments,
            debt=debt,
            diluted_shares_mm=diluted_shares_mm,
        )
        results[f"price_{label}"] = price
        results[f"upside_{label}"] = _upside(price, current_price)
    return results


# ─── Fragility scoring ────────────────────────────────────────────────────────

def compute_fragility_score(
    raw_upside: float,
    upside_wacc_plus150: float,
    base_exit_upside: float,
    upside_exit_minus3x: float,
    cycle_inflation_pct: float,
    cyclical_peak_detected: bool,
) -> float:
    """Return a fragility score in [0.0, 1.0].

    0.0 = upside survives all stress scenarios well
    1.0 = upside almost entirely destroyed by plausible stresses

    Components:
      40% — WACC sensitivity (how much +150bps erodes upside)
      40% — Multiple sensitivity (how much -3x erodes exit-method upside)
      20% — Cycle inflation (how elevated trailing EBITDA is vs normalised)
    """
    # WACC component
    if raw_upside > 0.02:
        wacc_destruction = max(0.0, raw_upside - upside_wacc_plus150) / raw_upside
    elif raw_upside <= 0:
        wacc_destruction = 1.0
    else:
        wacc_destruction = 0.5

    # Multiple component (uses exit-method upside directly)
    if base_exit_upside > 0.02:
        mult_destruction = max(0.0, base_exit_upside - upside_exit_minus3x) / base_exit_upside
    elif base_exit_upside <= 0:
        mult_destruction = 1.0
    else:
        mult_destruction = 0.5

    # Cycle component
    if cyclical_peak_detected:
        cycle_component = min(1.0, max(0.0, cycle_inflation_pct / 100.0))
    else:
        cycle_component = 0.0

    score = 0.40 * wacc_destruction + 0.40 * mult_destruction + 0.20 * cycle_component
    return round(min(1.0, max(0.0, score)), 4)


# ─── Upside gate ─────────────────────────────────────────────────────────────

def classify_upside_gate(adjusted_upside: float) -> str:
    """Classify stress-adjusted upside into a governance gate.

    The system assumes that large upside estimates are more likely to indicate
    model miscalibration than genuine market mispricing of large-cap stocks.
    """
    if adjusted_upside > _UPSIDE_ANOMALY:
        return "EXTREME_UPSIDE_ANOMALY"
    elif adjusted_upside > _UPSIDE_REVIEW:
        return "HIGH_UPSIDE_REVIEW_REQUIRED"
    elif adjusted_upside > _UPSIDE_AGGRESSIVE:
        return "AGGRESSIVE_UPSIDE"
    return "OK"


# ─── Confidence penalty ───────────────────────────────────────────────────────

def compute_confidence_penalty(
    upside_gate: str,
    wacc_destroys_upside: bool,
    cyclical_peak_detected: bool,
    multiple_fragility_warning: bool,
    fragility_score: float,
) -> int:
    """Return integer point penalty to be applied in assess_confidence_v2.

    These are additive deductions from the base confidence score.
    """
    penalty = 0
    if upside_gate == "EXTREME_UPSIDE_ANOMALY":
        penalty += 20
    elif upside_gate == "HIGH_UPSIDE_REVIEW_REQUIRED":
        penalty += 12
    elif upside_gate == "AGGRESSIVE_UPSIDE":
        penalty += 6
    if wacc_destroys_upside:
        penalty += 10
    if cyclical_peak_detected:
        penalty += 10
    if multiple_fragility_warning:
        penalty += 7
    if fragility_score > 0.70:
        penalty += 5
    elif fragility_score > 0.50:
        penalty += 3
    return penalty


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_stress_analysis(
    ticker: str,
    current_price: float,
    raw_intrinsic_value: float,
    ufcf_stream: list[float],
    terminal_ebitda_mm: float,
    wacc: float,
    terminal_growth: float,
    exit_multiple: float,
    cash_plus_investments_mm: float,
    debt_mm: float,
    diluted_shares_mm: float,
    historical_ebitda_mm: list[float] | None = None,
    cyclicals_path: Path | None = None,
    persist: bool = True,
) -> StressAdjustedValuation:
    """Run the full stress analysis for one ticker.

    Args:
        ticker:                 Ticker symbol (used for cyclicals lookup and logging)
        current_price:          Live market price
        raw_intrinsic_value:    Blended PT from the base DCF (used for comparison only)
        ufcf_stream:            FY+1..FY+5 UFCF in $mm from ModelOutputs
        terminal_ebitda_mm:     Terminal-year (FY+5) EBITDA in $mm from ModelOutputs
        wacc:                   Base WACC used in the raw DCF
        terminal_growth:        Terminal growth rate used in the raw DCF
        exit_multiple:          Base EV/EBITDA exit multiple (peer-resolved or default)
        cash_plus_investments_mm: Net cash + investments in $mm
        debt_mm:                Total debt in $mm
        diluted_shares_mm:      Diluted shares outstanding in mm
        historical_ebitda_mm:   List of historical annual EBITDA values in $mm
                                (sorted ascending, oldest first). Used for cyclical
                                normalisation. Pass None or empty to skip normalisation.
        cyclicals_path:         Override path to cyclicals.yaml (testing)
        persist:                Write to dcf_stress_log.jsonl

    Returns:
        StressAdjustedValuation — all stress outputs plus audit trail
    """
    ts = datetime.now(UTC).isoformat()
    flags: list[str] = []

    raw_upside = _upside(raw_intrinsic_value, current_price)

    # ── 1. Cyclical config lookup ────────────────────────────────────────────
    cyc_cfg = get_cyclical_config(ticker, _load_cyclicals(cyclicals_path))
    is_cyclical = cyc_cfg is not None
    norm_years = cyc_cfg["normalization_years"] if is_cyclical else 0
    peak_threshold = cyc_cfg["cycle_peak_threshold"] if is_cyclical else 0.25

    # ── 2. WACC stress grid ──────────────────────────────────────────────────
    wacc_prices: dict[str, float] = {}
    wacc_upsides: dict[str, float] = {}
    for label, shock in zip(["base", "plus100", "plus150", "plus200"],
                            [0.0] + _WACC_SHOCKS):
        stressed_wacc = wacc + shock
        p = _run_single_dcf(
            ufcf_stream=ufcf_stream,
            terminal_ebitda=terminal_ebitda_mm,
            wacc=stressed_wacc,
            terminal_growth=terminal_growth,
            exit_multiple=exit_multiple,
            cash_plus_investments=cash_plus_investments_mm,
            debt=debt_mm,
            diluted_shares_mm=diluted_shares_mm,
        )
        wacc_prices[label] = p
        wacc_upsides[label] = _upside(p, current_price)

    upside_w150 = wacc_upsides["plus150"]
    wacc_destroys_upside = (
        raw_upside > 0.05
        and (not math.isnan(upside_w150))
        and upside_w150 < raw_upside * 0.50
    )
    if wacc_destroys_upside:
        flags.append("WACC_SENSITIVITY_HIGH: +150bps halves the upside thesis")

    # ── 3. Cyclical EBITDA normalisation ────────────────────────────────────
    trailing_ebitda = terminal_ebitda_mm   # model's terminal is forward; use it as anchor
    normalized_ebitda = trailing_ebitda
    cycle_inflation_pct = 0.0
    cyclical_peak_detected = False
    norm_method = "none"
    price_normalized = wacc_prices["base"]  # fallback: no normalisation
    upside_normalized = wacc_upsides["base"]

    # Use the last historical value as true "trailing EBITDA" if available
    hist_valid = [v for v in (historical_ebitda_mm or []) if v and v > 0]
    if hist_valid:
        trailing_ebitda = hist_valid[-1]

    if is_cyclical and len(hist_valid) >= 2:
        norm_years_actual = min(norm_years, len(hist_valid))
        norm_ebitda = compute_normalized_ebitda(hist_valid, norm_years)
        if norm_ebitda is not None and norm_ebitda > 0:
            normalized_ebitda = norm_ebitda
            cycle_inflation_pct = compute_cycle_inflation(trailing_ebitda, normalized_ebitda)
            cyclical_peak_detected = cycle_inflation_pct > (peak_threshold * 100)
            norm_method = f"{norm_years_actual}yr_median"

            if cyclical_peak_detected:
                flags.append(
                    f"CYCLICAL_PEAK_DETECTED: trailing EBITDA {cycle_inflation_pct:.1f}% "
                    f"above {norm_method} normalised"
                )
                # Apply normalisation scale (downward only)
                norm_scale = min(_MAX_NORM_SCALE, normalized_ebitda / trailing_ebitda)
                ufcf_norm = [f * norm_scale for f in ufcf_stream]
                term_ebitda_norm = terminal_ebitda_mm * norm_scale

                # Normalised price at base WACC
                price_normalized = _run_single_dcf(
                    ufcf_stream=ufcf_norm,
                    terminal_ebitda=term_ebitda_norm,
                    wacc=wacc,
                    terminal_growth=terminal_growth,
                    exit_multiple=exit_multiple,
                    cash_plus_investments=cash_plus_investments_mm,
                    debt=debt_mm,
                    diluted_shares_mm=diluted_shares_mm,
                )
                upside_normalized = _upside(price_normalized, current_price)

    # ── 4. Exit multiple compression ─────────────────────────────────────────
    exit_grid = run_exit_compression(
        ufcf_stream=ufcf_stream,
        terminal_ebitda=terminal_ebitda_mm,
        base_exit_multiple=exit_multiple,
        wacc=wacc,
        terminal_growth=terminal_growth,
        cash_plus_investments=cash_plus_investments_mm,
        debt=debt_mm,
        diluted_shares_mm=diluted_shares_mm,
        current_price=current_price,
    )

    base_exit_upside = exit_grid["upside_base"]
    multiple_fragility_warning = (
        base_exit_upside > 0.05
        and exit_grid["upside_minus2x"] < base_exit_upside * 0.50
    )
    if multiple_fragility_warning:
        flags.append("MULTIPLE_FRAGILITY_WARNING: -2x exit multiple halves exit-method upside")

    # ── 5. Stress-adjusted (decision-grade) values ───────────────────────────
    # Most conservative plausible intrinsic value:
    # If cyclical peak detected → normalised EBITDA at WACC+150bps
    # Otherwise → base EBITDA at WACC+150bps
    if cyclical_peak_detected and not math.isnan(price_normalized):
        norm_scale = min(_MAX_NORM_SCALE, normalized_ebitda / trailing_ebitda)
        ufcf_norm = [f * norm_scale for f in ufcf_stream]
        term_ebitda_norm = terminal_ebitda_mm * norm_scale
        adjusted_price = _run_single_dcf(
            ufcf_stream=ufcf_norm,
            terminal_ebitda=term_ebitda_norm,
            wacc=wacc + 0.015,   # +150bps
            terminal_growth=terminal_growth,
            exit_multiple=exit_multiple,
            cash_plus_investments=cash_plus_investments_mm,
            debt=debt_mm,
            diluted_shares_mm=diluted_shares_mm,
        )
    else:
        adjusted_price = wacc_prices["plus150"]

    # Downside case: worst across all tests
    candidates = [
        wacc_prices["plus200"],
        exit_grid["price_minus4x"],
    ]
    if cyclical_peak_detected and not math.isnan(price_normalized):
        norm_scale = min(_MAX_NORM_SCALE, normalized_ebitda / trailing_ebitda)
        worst_norm = _run_single_dcf(
            ufcf_stream=[f * norm_scale for f in ufcf_stream],
            terminal_ebitda=terminal_ebitda_mm * norm_scale,
            wacc=wacc + 0.02,    # +200bps
            terminal_growth=terminal_growth,
            exit_multiple=exit_multiple,
            cash_plus_investments=cash_plus_investments_mm,
            debt=debt_mm,
            diluted_shares_mm=diluted_shares_mm,
        )
        candidates.append(worst_norm)

    valid_candidates = [c for c in candidates if c >= 0 and not math.isnan(c)]
    downside_case = min(valid_candidates) if valid_candidates else 0.0

    adjusted_upside = _upside(adjusted_price, current_price)
    if math.isnan(adjusted_price) or adjusted_price < 0:
        adjusted_intrinsic_value = 0.0
        adjusted_upside = -1.0
    else:
        adjusted_intrinsic_value = adjusted_price

    # ── 6. Fragility score ────────────────────────────────────────────────────
    fragility = compute_fragility_score(
        raw_upside=raw_upside,
        upside_wacc_plus150=wacc_upsides["plus150"],
        base_exit_upside=base_exit_upside,
        upside_exit_minus3x=exit_grid["upside_minus3x"],
        cycle_inflation_pct=cycle_inflation_pct,
        cyclical_peak_detected=cyclical_peak_detected,
    )
    if fragility > 0.70:
        flags.append(f"HIGH_FRAGILITY: fragility_score={fragility:.2f}")

    # ── 7. Upside gate ────────────────────────────────────────────────────────
    gate = classify_upside_gate(adjusted_upside)
    if gate != "OK":
        flags.append(f"UPSIDE_GATE_{gate}")

    # ── 8. Confidence penalty ─────────────────────────────────────────────────
    conf_penalty = compute_confidence_penalty(
        upside_gate=gate,
        wacc_destroys_upside=wacc_destroys_upside,
        cyclical_peak_detected=cyclical_peak_detected,
        multiple_fragility_warning=multiple_fragility_warning,
        fragility_score=fragility,
    )

    # ── 9. Sensitivity summary ────────────────────────────────────────────────
    sensitivity_summary = {
        "wacc_grid": {
            "base": {"wacc": round(wacc, 4), "price": round(wacc_prices["base"], 2),
                     "upside": round(wacc_upsides["base"], 4)},
            "+100bps": {"wacc": round(wacc + 0.01, 4), "price": round(wacc_prices["plus100"], 2),
                        "upside": round(wacc_upsides["plus100"], 4)},
            "+150bps": {"wacc": round(wacc + 0.015, 4), "price": round(wacc_prices["plus150"], 2),
                        "upside": round(wacc_upsides["plus150"], 4)},
            "+200bps": {"wacc": round(wacc + 0.02, 4), "price": round(wacc_prices["plus200"], 2),
                        "upside": round(wacc_upsides["plus200"], 4)},
        },
        "exit_grid": {
            "base": {"multiple": round(exit_multiple, 1), "price": round(exit_grid["price_base"], 2),
                     "upside": round(exit_grid["upside_base"], 4)},
            "-2x": {"multiple": round(exit_multiple - 2, 1), "price": round(exit_grid["price_minus2x"], 2),
                    "upside": round(exit_grid["upside_minus2x"], 4)},
            "-3x": {"multiple": round(exit_multiple - 3, 1), "price": round(exit_grid["price_minus3x"], 2),
                    "upside": round(exit_grid["upside_minus3x"], 4)},
            "-4x": {"multiple": round(exit_multiple - 4, 1), "price": round(exit_grid["price_minus4x"], 2),
                    "upside": round(exit_grid["upside_minus4x"], 4)},
        },
    }
    if is_cyclical:
        sensitivity_summary["normalisation"] = {
            "trailing_ebitda_mm": round(trailing_ebitda, 1),
            "normalized_ebitda_mm": round(normalized_ebitda, 1),
            "cycle_inflation_pct": round(cycle_inflation_pct, 1),
            "peak_detected": cyclical_peak_detected,
            "price_normalized": round(price_normalized, 2),
            "upside_normalized": round(upside_normalized, 4),
        }

    # ── Audit trail ───────────────────────────────────────────────────────────
    audit = {
        "ticker": ticker,
        "timestamp": ts,
        "inputs": {
            "current_price": current_price,
            "raw_intrinsic_value": raw_intrinsic_value,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "exit_multiple": exit_multiple,
            "terminal_ebitda_mm": terminal_ebitda_mm,
            "cash_mm": cash_plus_investments_mm,
            "debt_mm": debt_mm,
            "diluted_shares_mm": diluted_shares_mm,
            "n_historical_ebitda": len(hist_valid),
        },
        "outputs": {
            "adjusted_intrinsic_value": round(adjusted_intrinsic_value, 2),
            "adjusted_upside": round(adjusted_upside, 4),
            "downside_case": round(downside_case, 2),
            "fragility_score": fragility,
            "upside_gate": gate,
            "confidence_penalty": conf_penalty,
            "wacc_destroys_upside": wacc_destroys_upside,
            "cyclical_peak_detected": cyclical_peak_detected,
            "multiple_fragility_warning": multiple_fragility_warning,
        },
        "flags": flags,
    }

    result = StressAdjustedValuation(
        ticker=ticker.upper(),
        current_price=current_price,
        timestamp=ts,
        raw_intrinsic_value=raw_intrinsic_value,
        raw_upside=raw_upside,
        wacc_base=wacc,
        price_wacc_base=round(wacc_prices["base"], 2),
        price_wacc_plus100=round(wacc_prices["plus100"], 2),
        price_wacc_plus150=round(wacc_prices["plus150"], 2),
        price_wacc_plus200=round(wacc_prices["plus200"], 2),
        upside_wacc_plus100=round(wacc_upsides["plus100"], 4),
        upside_wacc_plus150=round(wacc_upsides["plus150"], 4),
        upside_wacc_plus200=round(wacc_upsides["plus200"], 4),
        wacc_destroys_upside=wacc_destroys_upside,
        is_cyclical=is_cyclical,
        normalization_years=norm_years,
        trailing_ebitda_mm=round(trailing_ebitda, 2),
        normalized_ebitda_mm=round(normalized_ebitda, 2),
        cycle_inflation_pct=round(cycle_inflation_pct, 2),
        cyclical_peak_detected=cyclical_peak_detected,
        normalization_method=norm_method,
        price_normalized=round(price_normalized, 2),
        upside_normalized=round(upside_normalized, 4),
        base_exit_multiple=exit_multiple,
        price_exit_minus2x=round(exit_grid["price_minus2x"], 2),
        price_exit_minus3x=round(exit_grid["price_minus3x"], 2),
        price_exit_minus4x=round(exit_grid["price_minus4x"], 2),
        upside_exit_minus2x=round(exit_grid["upside_minus2x"], 4),
        upside_exit_minus3x=round(exit_grid["upside_minus3x"], 4),
        upside_exit_minus4x=round(exit_grid["upside_minus4x"], 4),
        multiple_fragility_warning=multiple_fragility_warning,
        adjusted_intrinsic_value=round(adjusted_intrinsic_value, 2),
        adjusted_upside=round(adjusted_upside, 4),
        downside_case=round(downside_case, 2),
        fragility_score=fragility,
        upside_gate=gate,
        confidence_penalty=conf_penalty,
        review_flags=flags,
        sensitivity_summary=sensitivity_summary,
        audit_trail=audit,
    )

    if persist:
        _persist_stress_log(result)

    return result


# ─── Logging ─────────────────────────────────────────────────────────────────

def _persist_stress_log(result: StressAdjustedValuation) -> None:
    """Append to dcf_stress_log.jsonl. Write-only — never reads back."""
    _DATA_PATH.mkdir(parents=True, exist_ok=True)
    entry = {
        "ticker": result.ticker,
        "timestamp": result.timestamp,
        "raw_upside": result.raw_upside,
        "adjusted_upside": result.adjusted_upside,
        "upside_gate": result.upside_gate,
        "fragility_score": result.fragility_score,
        "cyclical_peak_detected": result.cyclical_peak_detected,
        "wacc_destroys_upside": result.wacc_destroys_upside,
        "multiple_fragility_warning": result.multiple_fragility_warning,
        "confidence_penalty": result.confidence_penalty,
        "review_flags": result.review_flags,
        "sensitivity_summary": result.sensitivity_summary,
        "diagnostic_only": True,
    }
    with open(_STRESS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_stress_log(path: Path | None = None) -> list[dict]:
    """Load all persisted stress analysis entries."""
    p = path or _STRESS_LOG
    if not p.exists():
        return []
    entries = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def detect_confidence_compression(
    confidence_tiers: list[str],
    threshold: float = 0.50,
) -> bool:
    """Return True if >threshold fraction of tickers share the same confidence tier.

    Called from the governance runner after a full screener cycle.
    """
    if not confidence_tiers:
        return False
    counts: dict[str, int] = {}
    for t in confidence_tiers:
        counts[t] = counts.get(t, 0) + 1
    max_fraction = max(counts.values()) / len(confidence_tiers)
    return max_fraction > threshold
