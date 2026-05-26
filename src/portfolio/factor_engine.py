"""Factor Engine — portfolio-level factor exposure scoring.

Estimates how concentrated the portfolio is in specific economic factors
(growth, leverage, cyclicality, AI-capex beta, etc.). Factors are cross-cutting:
a ticker can score high on multiple factors simultaneously.

Factor scores (0.0–1.0) are static, derived from fundamental knowledge of each
business model. Portfolio factor exposure = weighted average of ticker scores.

When any single factor exceeds the dominance threshold, a WARNING is generated.
This catches hidden tilts that sector analysis misses entirely.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ─── Factor definitions ───────────────────────────────────────────────────────

FACTORS = [
    "growth",           # expected revenue/earnings growth rate
    "value",            # valuation cheapness vs history
    "quality",          # ROIC, FCF conversion, balance sheet strength
    "leverage",         # net_debt/EBITDA and debt load
    "cyclicality",      # revenue correlation with capex/industrial cycle
    "duration_sensitivity",  # sensitivity to long-end rates
    "industrial_beta",  # correlation with US industrial activity index
    "ai_capex_beta",    # revenue sensitivity to AI/data center capex
    "rates_sensitivity", # direct interest rate sensitivity
    "recession_sensitivity",  # revenue impact in recessions
]

FACTOR_DESCRIPTIONS = {
    "growth": "Expected revenue / earnings growth rate",
    "value": "Valuation cheapness relative to history and peers",
    "quality": "ROIC, FCF conversion strength, balance sheet quality",
    "leverage": "Net debt / EBITDA and total debt load",
    "cyclicality": "Revenue correlation with industrial capex cycle",
    "duration_sensitivity": "Sensitivity to long-end interest rates",
    "industrial_beta": "Correlation with US industrial production",
    "ai_capex_beta": "Revenue sensitivity to AI / data center capex spend",
    "rates_sensitivity": "Direct interest rate sensitivity (financing cost + valuation)",
    "recession_sensitivity": "Revenue erosion in a recession scenario",
}

# Concentration warning threshold — if portfolio avg on any factor exceeds this,
# generate FACTOR_CONCENTRATION_WARNING.
_FACTOR_WARN_THRESHOLD = 0.55
_FACTOR_HIGH_THRESHOLD = 0.70

# ─── Static ticker factor scores (0.0 = none, 1.0 = maximum) ─────────────────
# Scores reflect fundamental business model characteristics, not trailing price action.
# Each score is the author's calibrated estimate — inherently qualitative.
# Update as business models change (new products, leverage events, etc.)

TICKER_FACTOR_SCORES: dict[str, dict[str, float]] = {
    # ── Current paper portfolio ─────────────────────────────────────────────
    "ACM": {
        "growth": 0.45, "value": 0.50, "quality": 0.55, "leverage": 0.30,
        "cyclicality": 0.65, "duration_sensitivity": 0.40, "industrial_beta": 0.70,
        "ai_capex_beta": 0.40, "rates_sensitivity": 0.38, "recession_sensitivity": 0.60,
    },
    "AMAT": {
        "growth": 0.70, "value": 0.45, "quality": 0.75, "leverage": 0.15,
        "cyclicality": 0.90, "duration_sensitivity": 0.60, "industrial_beta": 0.75,
        "ai_capex_beta": 0.95, "rates_sensitivity": 0.55, "recession_sensitivity": 0.85,
    },
    "DY": {
        "growth": 0.45, "value": 0.50, "quality": 0.55, "leverage": 0.35,
        "cyclicality": 0.60, "duration_sensitivity": 0.45, "industrial_beta": 0.65,
        "ai_capex_beta": 0.45, "rates_sensitivity": 0.42, "recession_sensitivity": 0.55,
    },
    "EMR": {
        "growth": 0.45, "value": 0.50, "quality": 0.65, "leverage": 0.35,
        "cyclicality": 0.65, "duration_sensitivity": 0.50, "industrial_beta": 0.75,
        "ai_capex_beta": 0.50, "rates_sensitivity": 0.45, "recession_sensitivity": 0.60,
    },
    "GD": {
        "growth": 0.35, "value": 0.55, "quality": 0.75, "leverage": 0.30,
        "cyclicality": 0.20, "duration_sensitivity": 0.40, "industrial_beta": 0.25,
        "ai_capex_beta": 0.10, "rates_sensitivity": 0.35, "recession_sensitivity": 0.15,
    },
    "GNRC": {
        "growth": 0.55, "value": 0.50, "quality": 0.60, "leverage": 0.65,
        "cyclicality": 0.55, "duration_sensitivity": 0.58, "industrial_beta": 0.60,
        "ai_capex_beta": 0.55, "rates_sensitivity": 0.65, "recession_sensitivity": 0.50,
    },
    "HUBB": {
        "growth": 0.55, "value": 0.45, "quality": 0.70, "leverage": 0.30,
        "cyclicality": 0.60, "duration_sensitivity": 0.55, "industrial_beta": 0.70,
        "ai_capex_beta": 0.65, "rates_sensitivity": 0.50, "recession_sensitivity": 0.55,
    },
    "J": {
        "growth": 0.40, "value": 0.50, "quality": 0.55, "leverage": 0.25,
        "cyclicality": 0.60, "duration_sensitivity": 0.40, "industrial_beta": 0.65,
        "ai_capex_beta": 0.35, "rates_sensitivity": 0.38, "recession_sensitivity": 0.58,
    },
    "KMI": {
        "growth": 0.25, "value": 0.60, "quality": 0.55, "leverage": 0.85,
        "cyclicality": 0.30, "duration_sensitivity": 0.72, "industrial_beta": 0.35,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.80, "recession_sensitivity": 0.25,
    },
    "LDOS": {
        "growth": 0.35, "value": 0.50, "quality": 0.70, "leverage": 0.25,
        "cyclicality": 0.20, "duration_sensitivity": 0.35, "industrial_beta": 0.20,
        "ai_capex_beta": 0.15, "rates_sensitivity": 0.30, "recession_sensitivity": 0.15,
    },
    "SPGI": {
        "growth": 0.60, "value": 0.35, "quality": 0.90, "leverage": 0.35,
        "cyclicality": 0.30, "duration_sensitivity": 0.60, "industrial_beta": 0.30,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.55, "recession_sensitivity": 0.30,
    },
    "TRGP": {
        "growth": 0.30, "value": 0.55, "quality": 0.50, "leverage": 0.80,
        "cyclicality": 0.30, "duration_sensitivity": 0.65, "industrial_beta": 0.35,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.75, "recession_sensitivity": 0.28,
    },
    # ── Universe tickers (for concentration_governor prospective checks) ────
    "ETN": {
        "growth": 0.55, "value": 0.40, "quality": 0.75, "leverage": 0.25,
        "cyclicality": 0.65, "duration_sensitivity": 0.55, "industrial_beta": 0.75,
        "ai_capex_beta": 0.70, "rates_sensitivity": 0.50, "recession_sensitivity": 0.60,
    },
    "VRT": {
        "growth": 0.70, "value": 0.40, "quality": 0.65, "leverage": 0.35,
        "cyclicality": 0.65, "duration_sensitivity": 0.55, "industrial_beta": 0.65,
        "ai_capex_beta": 0.90, "rates_sensitivity": 0.50, "recession_sensitivity": 0.60,
    },
    "LRCX": {
        "growth": 0.65, "value": 0.45, "quality": 0.75, "leverage": 0.15,
        "cyclicality": 0.90, "duration_sensitivity": 0.60, "industrial_beta": 0.70,
        "ai_capex_beta": 0.90, "rates_sensitivity": 0.55, "recession_sensitivity": 0.85,
    },
    "KLAC": {
        "growth": 0.65, "value": 0.45, "quality": 0.80, "leverage": 0.10,
        "cyclicality": 0.85, "duration_sensitivity": 0.58, "industrial_beta": 0.70,
        "ai_capex_beta": 0.88, "rates_sensitivity": 0.53, "recession_sensitivity": 0.82,
    },
    "LMT": {
        "growth": 0.30, "value": 0.55, "quality": 0.70, "leverage": 0.35,
        "cyclicality": 0.20, "duration_sensitivity": 0.40, "industrial_beta": 0.25,
        "ai_capex_beta": 0.10, "rates_sensitivity": 0.35, "recession_sensitivity": 0.12,
    },
    "RTX": {
        "growth": 0.35, "value": 0.50, "quality": 0.65, "leverage": 0.30,
        "cyclicality": 0.25, "duration_sensitivity": 0.42, "industrial_beta": 0.30,
        "ai_capex_beta": 0.12, "rates_sensitivity": 0.38, "recession_sensitivity": 0.15,
    },
    "HON": {
        "growth": 0.40, "value": 0.50, "quality": 0.70, "leverage": 0.35,
        "cyclicality": 0.60, "duration_sensitivity": 0.55, "industrial_beta": 0.70,
        "ai_capex_beta": 0.45, "rates_sensitivity": 0.50, "recession_sensitivity": 0.55,
    },
    "CAT": {
        "growth": 0.40, "value": 0.50, "quality": 0.65, "leverage": 0.30,
        "cyclicality": 0.80, "duration_sensitivity": 0.50, "industrial_beta": 0.85,
        "ai_capex_beta": 0.20, "rates_sensitivity": 0.45, "recession_sensitivity": 0.75,
    },
    "WMB": {
        "growth": 0.25, "value": 0.60, "quality": 0.55, "leverage": 0.80,
        "cyclicality": 0.30, "duration_sensitivity": 0.70, "industrial_beta": 0.35,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.78, "recession_sensitivity": 0.25,
    },
    "SPGI": {
        "growth": 0.60, "value": 0.35, "quality": 0.90, "leverage": 0.35,
        "cyclicality": 0.30, "duration_sensitivity": 0.60, "industrial_beta": 0.30,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.55, "recession_sensitivity": 0.30,
    },
    "MCO": {
        "growth": 0.58, "value": 0.35, "quality": 0.88, "leverage": 0.40,
        "cyclicality": 0.30, "duration_sensitivity": 0.60, "industrial_beta": 0.28,
        "ai_capex_beta": 0.05, "rates_sensitivity": 0.55, "recession_sensitivity": 0.30,
    },
    "AGX": {
        "growth": 0.50, "value": 0.50, "quality": 0.65, "leverage": 0.10,
        "cyclicality": 0.70, "duration_sensitivity": 0.40, "industrial_beta": 0.75,
        "ai_capex_beta": 0.35, "rates_sensitivity": 0.35, "recession_sensitivity": 0.65,
    },
    "PWR": {
        "growth": 0.50, "value": 0.45, "quality": 0.60, "leverage": 0.30,
        "cyclicality": 0.65, "duration_sensitivity": 0.45, "industrial_beta": 0.70,
        "ai_capex_beta": 0.55, "rates_sensitivity": 0.40, "recession_sensitivity": 0.60,
    },
}

# Default factor scores for unknown tickers — neutral/mid-range
_DEFAULT_FACTOR_SCORES: dict[str, float] = {f: 0.40 for f in FACTORS}


# ─── Portfolio factor computation ─────────────────────────────────────────────

def get_ticker_factors(ticker: str) -> dict[str, float]:
    """Return factor scores for one ticker. Falls back to defaults for unknowns."""
    return TICKER_FACTOR_SCORES.get(ticker.upper(), dict(_DEFAULT_FACTOR_SCORES))


def compute_portfolio_factors(
    tickers: list[str],
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute weighted-average factor vector for the portfolio.

    weights: {ticker: fraction}. If None, assumes equal weighting.
    """
    if not tickers:
        return {f: 0.0 for f in FACTORS}

    n = len(tickers)
    w = weights or {t.upper(): 1.0 / n for t in tickers}

    result: dict[str, float] = {f: 0.0 for f in FACTORS}
    total_weight = sum(w.get(t.upper(), 1.0 / n) for t in tickers)

    for ticker in tickers:
        ticker_w = w.get(ticker.upper(), 1.0 / n) / total_weight
        scores = get_ticker_factors(ticker)
        for factor in FACTORS:
            result[factor] += scores.get(factor, 0.40) * ticker_w

    return {f: round(v, 4) for f, v in result.items()}


def compute_factor_dominance_score(portfolio_factors: dict[str, float]) -> float:
    """Single summary score of factor imbalance (0.0 = perfectly balanced, 1.0 = totally dominated).

    Uses Herfindahl-like measure on factor scores weighted by their distance from neutral (0.50).
    """
    if not portfolio_factors:
        return 0.0
    deviations = [abs(v - 0.50) for v in portfolio_factors.values()]
    return round(sum(d ** 2 for d in deviations) / len(deviations), 4)


def detect_factor_concentrations(
    portfolio_factors: dict[str, float],
    warn_threshold: float = _FACTOR_WARN_THRESHOLD,
    high_threshold: float = _FACTOR_HIGH_THRESHOLD,
) -> list[str]:
    """Return list of FACTOR_CONCENTRATION_WARNING strings for elevated factors."""
    warnings = []
    for factor, score in portfolio_factors.items():
        desc = FACTOR_DESCRIPTIONS.get(factor, factor)
        if score >= high_threshold:
            warnings.append(
                f"FACTOR_CONCENTRATION_WARNING [HIGH]: {factor} = {score:.2f} — "
                f"{desc} is elevated well above neutral"
            )
        elif score >= warn_threshold:
            warnings.append(
                f"FACTOR_CONCENTRATION_WARNING [ELEVATED]: {factor} = {score:.2f} — "
                f"{desc} is approaching concentration threshold"
            )
    return warnings


# ─── Main entry point ─────────────────────────────────────────────────────────

@dataclass
class FactorAnalysis:
    portfolio_factors: dict[str, float]
    factor_dominance_score: float
    warnings: list[str]
    most_concentrated_factor: str
    most_concentrated_score: float
    ticker_factor_matrix: dict[str, dict[str, float]]


def run_factor_analysis(
    tickers: list[str],
    weights: dict[str, float] | None = None,
) -> FactorAnalysis:
    """Run full factor analysis for a portfolio."""
    portfolio_factors = compute_portfolio_factors(tickers, weights)
    dominance = compute_factor_dominance_score(portfolio_factors)
    warnings = detect_factor_concentrations(portfolio_factors)

    top_factor = max(portfolio_factors.items(), key=lambda x: x[1]) if portfolio_factors else ("none", 0.0)

    ticker_matrix = {
        t.upper(): get_ticker_factors(t) for t in tickers
    }

    return FactorAnalysis(
        portfolio_factors=portfolio_factors,
        factor_dominance_score=dominance,
        warnings=warnings,
        most_concentrated_factor=top_factor[0],
        most_concentrated_score=top_factor[1],
        ticker_factor_matrix=ticker_matrix,
    )
