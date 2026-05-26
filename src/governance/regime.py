"""Regime Intelligence Engine — probabilistic market environment classification.

Classifies the current market into soft-probability regimes using free yfinance
data only. All calculation is deterministic and reproducible. Zero LLM calls.

Regimes:
  risk_on_growth          — low VIX, SPY trending up, wide breadth, tight credit
  risk_off_defensive      — high VIX, SPY falling, narrow breadth, credit widening
  inflationary_cyclical   — yields rising fast, energy/materials leading, dollar weak
  disinflationary_expansion — yields falling, growth/tech leading, low volatility
  high_volatility_stress  — VIX > 30, rapid drawdown, credit spreading fast
  liquidity_panic         — VIX > 40, all assets selling, dollar spike
  mean_reverting_chop     — VIX 15–25, no trend, flat breadth, no sector leadership

Output example:
  {
    "probabilities": {"risk_on_growth": 0.48, ...},
    "leading_regime": "risk_on_growth",
    "confidence": 0.48,
    "conditions": {"spy_above_50d": 1.0, "vix_below_20": 1.0, ...},
    "indicators": {"vix_current": 18.2, ...},
    "timestamp": "2026-05-26T10:00:00"
  }

Confidence = max(probabilities). Higher = clearer environment. Below 0.25 = ambiguous.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_REGIMES = [
    "risk_on_growth",
    "risk_off_defensive",
    "inflationary_cyclical",
    "disinflationary_expansion",
    "high_volatility_stress",
    "liquidity_panic",
    "mean_reverting_chop",
]

_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_REGIME_LOG = _DATA_PATH / "regime_log.jsonl"

_FETCH_SYMBOLS = [
    "^VIX", "SPY", "RSP", "TLT", "HYG", "UUP",
    "XLE", "XLK", "XLU", "XLB", "XLY", "XLP",
]

# Scoring matrix: {regime: {condition: weight}}
# Positive weight = condition supports this regime.
# Each regime score = sum(weight × condition_value) for active conditions.
_REGIME_PROFILES: dict[str, dict[str, float]] = {
    "risk_on_growth": {
        "vix_below_20": 3.0,
        "vix_below_15": 2.0,
        "vix_above_30": -5.0,
        "spy_above_50d": 3.0,
        "spy_above_200d": 2.0,
        "vix_trending_up": -3.0,
        "vix_trending_down": 2.0,
        "breadth_positive": 2.0,
        "credit_stress": -4.0,
        "high_realized_vol": -3.0,
        "yields_rising_fast": -1.0,
        "dollar_strong": -1.0,
        "energy_leading": -1.0,
        "credit_tight": 2.0,
    },
    "risk_off_defensive": {
        "vix_above_25": 3.0,
        "vix_above_30": 2.0,
        "vix_trending_up": 3.0,
        "spy_below_50d": 3.0,
        "spy_below_200d": 2.0,
        "breadth_negative": 2.0,
        "credit_stress": 4.0,
        "high_realized_vol": 3.0,
        "vix_below_20": -3.0,
        "utilities_leading": 2.0,
        "tech_lagging": 2.0,
        "dollar_strong": 1.0,
        "yields_falling": 1.0,  # flight to bonds
    },
    "inflationary_cyclical": {
        "yields_rising_fast": 4.0,
        "energy_leading": 3.0,
        "materials_leading": 2.0,
        "dollar_weak": 2.0,
        "vix_below_25": 1.0,
        "spy_above_50d": 1.0,
        "tech_lagging": 2.0,
        "utilities_lagging": 2.0,
        "vix_above_30": -2.0,
        "credit_stress": -1.0,
    },
    "disinflationary_expansion": {
        "yields_falling": 3.0,
        "vix_below_20": 2.0,
        "spy_above_50d": 3.0,
        "spy_above_200d": 2.0,
        "tech_leading": 2.0,
        "breadth_positive": 2.0,
        "credit_tight": 2.0,
        "high_realized_vol": -2.0,
        "energy_leading": -2.0,
        "vix_above_25": -3.0,
    },
    "high_volatility_stress": {
        "vix_above_30": 5.0,
        "vix_trending_up": 3.0,
        "high_realized_vol": 4.0,
        "spy_below_200d": 3.0,
        "credit_stress": 4.0,
        "breadth_negative": 3.0,
        "vix_below_20": -5.0,
        "credit_tight": -3.0,
        "vix_above_40": -2.0,  # if above 40 it's panic, not just stress
    },
    "liquidity_panic": {
        "vix_above_40": 6.0,
        "vix_above_30": 3.0,
        "vix_trending_up": 2.0,
        "high_realized_vol": 4.0,
        "spy_below_200d": 3.0,
        "credit_stress": 5.0,
        "breadth_negative": 3.0,
        "dollar_strong": 2.0,
        "vix_below_25": -5.0,
        "spy_above_200d": -4.0,
        "credit_tight": -4.0,
    },
    "mean_reverting_chop": {
        "vix_between_15_25": 3.0,
        "spy_near_50d": 3.0,
        "breadth_neutral": 2.0,
        "no_trend_strength": 3.0,
        "vix_above_30": -3.0,
        "vix_below_15": -2.0,
        "high_realized_vol": -2.0,
        "spy_far_from_200d": -2.0,
        "credit_stress": -2.0,
    },
}


def _softmax(scores: dict[str, float], temperature: float = 2.0) -> dict[str, float]:
    """Convert raw scores to probabilities via temperature-scaled softmax."""
    adjusted = {k: v / temperature for k, v in scores.items()}
    max_v = max(adjusted.values())
    exps = {k: math.exp(v - max_v) for k, v in adjusted.items()}
    total = sum(exps.values())
    return {k: round(v / total, 4) for k, v in exps.items()}


def compute_conditions(indicators: dict[str, float]) -> dict[str, float]:
    """Convert raw indicator values to binary conditions used in regime scoring.

    Returns {condition_name: 0.0 or 1.0}. Only conditions = 1.0 are active.
    Exposed publicly for testing and transparency.
    """
    c: dict[str, float] = {}

    vix = indicators.get("vix_current", 20.0)
    vix_5d = indicators.get("vix_5d_ago", vix)
    spy_now = indicators.get("spy_current", 100.0)
    spy_50d = indicators.get("spy_50d_avg", spy_now)
    spy_200d = indicators.get("spy_200d_avg", spy_now)
    realized_vol = indicators.get("spy_realized_vol_20d", 0.15)
    breadth = indicators.get("rsp_vs_spy_30d", 0.0)
    yields_delta = indicators.get("tlt_30d_return", 0.0)
    credit = indicators.get("hyg_vs_tlt_30d", 0.0)
    dollar = indicators.get("uup_30d_return", 0.0)
    energy_rel = indicators.get("xle_vs_spy_30d", 0.0)
    tech_rel = indicators.get("xlk_vs_spy_30d", 0.0)
    util_rel = indicators.get("xlu_vs_spy_30d", 0.0)
    mat_rel = indicators.get("xlb_vs_spy_30d", 0.0)

    # VIX level
    c["vix_below_15"] = 1.0 if vix < 15 else 0.0
    c["vix_below_20"] = 1.0 if vix < 20 else 0.0
    c["vix_below_25"] = 1.0 if vix < 25 else 0.0
    c["vix_between_15_25"] = 1.0 if 15 <= vix <= 25 else 0.0
    c["vix_above_25"] = 1.0 if vix > 25 else 0.0
    c["vix_above_30"] = 1.0 if vix > 30 else 0.0
    c["vix_above_40"] = 1.0 if vix > 40 else 0.0
    c["high_realized_vol"] = 1.0 if realized_vol > 0.20 else 0.0

    # VIX trend (5-day change)
    vix_chg = (vix - vix_5d) / vix_5d if vix_5d > 0 else 0.0
    c["vix_trending_up"] = 1.0 if vix_chg > 0.05 else 0.0
    c["vix_trending_down"] = 1.0 if vix_chg < -0.05 else 0.0

    # SPY vs moving averages
    spy_vs_50d = (spy_now - spy_50d) / spy_50d if spy_50d > 0 else 0.0
    spy_vs_200d = (spy_now - spy_200d) / spy_200d if spy_200d > 0 else 0.0
    c["spy_above_50d"] = 1.0 if spy_vs_50d > 0.01 else 0.0
    c["spy_above_200d"] = 1.0 if spy_vs_200d > 0.02 else 0.0
    c["spy_below_50d"] = 1.0 if spy_vs_50d < -0.01 else 0.0
    c["spy_below_200d"] = 1.0 if spy_vs_200d < -0.02 else 0.0
    c["spy_near_50d"] = 1.0 if abs(spy_vs_50d) < 0.02 else 0.0
    c["spy_far_from_200d"] = 1.0 if abs(spy_vs_200d) > 0.10 else 0.0
    c["no_trend_strength"] = 1.0 if abs(spy_vs_50d) < 0.03 else 0.0

    # Breadth (RSP vs SPY 30d relative return)
    c["breadth_positive"] = 1.0 if breadth > 0.01 else 0.0
    c["breadth_negative"] = 1.0 if breadth < -0.01 else 0.0
    c["breadth_neutral"] = 1.0 if abs(breadth) < 0.02 else 0.0

    # Yields (TLT 30d return proxy — TLT falling = yields rising)
    c["yields_rising_fast"] = 1.0 if yields_delta < -0.03 else 0.0
    c["yields_falling"] = 1.0 if yields_delta > 0.02 else 0.0

    # Credit (HYG relative to TLT — negative = stress)
    c["credit_stress"] = 1.0 if credit < -0.02 else 0.0
    c["credit_tight"] = 1.0 if credit > 0.01 else 0.0

    # Dollar (UUP 30d)
    c["dollar_strong"] = 1.0 if dollar > 0.01 else 0.0
    c["dollar_weak"] = 1.0 if dollar < -0.01 else 0.0

    # Sector leadership (30d vs SPY)
    c["energy_leading"] = 1.0 if energy_rel > 0.03 else 0.0
    c["tech_leading"] = 1.0 if tech_rel > 0.02 else 0.0
    c["tech_lagging"] = 1.0 if tech_rel < -0.02 else 0.0
    c["utilities_leading"] = 1.0 if util_rel > 0.02 else 0.0
    c["utilities_lagging"] = 1.0 if util_rel < -0.02 else 0.0
    c["materials_leading"] = 1.0 if mat_rel > 0.02 else 0.0

    return c


def _score_regimes(conditions: dict[str, float]) -> dict[str, float]:
    """Apply regime profiles to active conditions. Returns raw scores per regime."""
    return {
        regime: sum(
            weight * conditions.get(cond, 0.0)
            for cond, weight in profile.items()
        )
        for regime, profile in _REGIME_PROFILES.items()
    }


def fetch_indicators(lookback_days: int = 320) -> dict[str, float]:
    """Fetch market data and compute regime indicators via yfinance.

    Returns dict of raw indicator values.
    Raises RuntimeError if data is unavailable or insufficient — fails loudly.
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError(f"yfinance required for regime engine: {e}") from e

    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days)

    raw = yf.download(
        _FETCH_SYMBOLS,
        start=str(start),
        end=str(end),
        auto_adjust=True,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned empty data for regime indicators")

    # Handle multi-level columns from multi-ticker download
    if hasattr(raw.columns, "levels"):
        close = raw["Close"]
    else:
        close = raw

    def _series(sym: str):
        if sym in close.columns:
            s = close[sym].dropna()
            return s if len(s) > 0 else None
        return None

    result: dict[str, float] = {}

    vix = _series("^VIX")
    if vix is None or len(vix) < 10:
        raise RuntimeError("Insufficient VIX data for regime classification")
    result["vix_current"] = float(vix.iloc[-1])
    result["vix_5d_ago"] = float(vix.iloc[-6]) if len(vix) >= 6 else float(vix.iloc[0])

    spy = _series("SPY")
    if spy is None or len(spy) < 55:
        raise RuntimeError(
            f"Insufficient SPY data: need ≥55 days, got {len(spy) if spy is not None else 0}"
        )
    result["spy_current"] = float(spy.iloc[-1])
    result["spy_50d_avg"] = float(spy.iloc[-50:].mean())
    # Use all available history for the long-term MA (up to 200 days)
    long_window = min(len(spy), 200)
    result["spy_200d_avg"] = float(spy.iloc[-long_window:].mean())
    if long_window < 200:
        result["spy_200d_avg_note"] = f"using_{long_window}d_avg_only"

    spy_rets = spy.pct_change().dropna()
    result["spy_realized_vol_20d"] = (
        float(spy_rets.iloc[-20:].std() * math.sqrt(252))
        if len(spy_rets) >= 20
        else 0.15
    )

    def _30d_return(sym: str) -> Optional[float]:
        s = _series(sym)
        if s is not None and len(s) >= 30:
            return float(s.iloc[-1] / s.iloc[-30] - 1)
        return None

    spy_30d = _30d_return("SPY")
    rsp_30d = _30d_return("RSP")
    result["rsp_vs_spy_30d"] = (
        rsp_30d - spy_30d if (rsp_30d is not None and spy_30d is not None) else 0.0
    )

    result["tlt_30d_return"] = _30d_return("TLT") or 0.0

    hyg_30d = _30d_return("HYG")
    tlt_30d = _30d_return("TLT")
    result["hyg_vs_tlt_30d"] = (
        (hyg_30d - tlt_30d) if (hyg_30d is not None and tlt_30d is not None) else 0.0
    )

    result["uup_30d_return"] = _30d_return("UUP") or 0.0

    for tag, sym in [("xle", "XLE"), ("xlk", "XLK"), ("xlu", "XLU"), ("xlb", "XLB")]:
        sect_30d = _30d_return(sym)
        result[f"{tag}_vs_spy_30d"] = (
            (sect_30d - spy_30d) if (sect_30d is not None and spy_30d is not None) else 0.0
        )

    return result


def classify_regime(
    indicators: dict[str, float] | None = None,
    temperature: float = 2.0,
) -> dict:
    """Classify current market regime into soft probabilities.

    Pass indicators dict to bypass network fetch (useful for testing).
    Raises RuntimeError if live fetch fails.

    Returns:
        probabilities   — {regime: probability} summing to ~1.0
        leading_regime  — highest-probability regime name
        confidence      — probability of leading regime (low = ambiguous environment)
        conditions      — active boolean conditions (for explainability)
        indicators      — raw numeric indicator values
        timestamp       — ISO 8601 UTC
    """
    if indicators is None:
        indicators = fetch_indicators()

    conditions = compute_conditions(indicators)
    raw_scores = _score_regimes(conditions)
    probabilities = _softmax(raw_scores, temperature=temperature)

    leading = max(probabilities, key=lambda k: probabilities[k])

    return {
        "probabilities": probabilities,
        "leading_regime": leading,
        "confidence": probabilities[leading],
        "indicators": {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in indicators.items()
        },
        "conditions": {k: v for k, v in conditions.items() if v > 0.0},
        "timestamp": datetime.utcnow().isoformat(),
    }


def log_regime(result: dict, path: Path | None = None) -> None:
    """Append one regime classification result to regime_log.jsonl."""
    log_path = path or _REGIME_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(result) + "\n")


def run_regime_engine(persist: bool = True) -> dict:
    """Run the regime engine end-to-end: fetch → classify → optionally persist."""
    result = classify_regime()
    if persist:
        log_regime(result)
    return result


def load_regime_history(path: Path | None = None) -> list[dict]:
    """Load all persisted regime classifications from regime_log.jsonl."""
    log_path = path or _REGIME_LOG
    if not log_path.exists():
        return []
    results = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return results
