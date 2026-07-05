"""Portfolio Exposure Intelligence — factor and theme concentration analysis.

Detects hidden concentration risk. The paper portfolio may appear diversified
by ticker count while actually clustering around common macro themes and factors.

Key insight: a portfolio holding ACM (EPC), DY (telecom infra), HUBB (electrical),
GNRC (power gen), and EMR (industrial automation) looks like 5 different sectors
but is really one bet: US power grid and infrastructure buildout.

Theme definitions are static; factor definitions are cross-cutting (one ticker
can appear in multiple factors). Both are needed to surface hidden concentration.

No LLM calls. No paid data. Fully deterministic.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from src.io_utils import append_jsonl
from pathlib import Path
from typing import Optional

import yaml

_POSITIONS_PATH = Path(__file__).parent.parent.parent / "data" / "paper_positions.yaml"
_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "governance"
_EXPOSURE_LOG = _DATA_PATH / "exposure_log.jsonl"

# ─── Static theme and factor mappings ────────────────────────────────────────
# Themes: mutually exclusive primary classification of each ticker.
# A ticker belongs to exactly one theme.
THEME_MEMBERSHIP: dict[str, str] = {
    # Infrastructure / EPC
    "ACM": "infrastructure_epc",
    "J": "infrastructure_epc",
    "FLR": "infrastructure_epc",
    "DY": "infrastructure_epc",
    "PWR": "infrastructure_epc",
    "MTZ": "infrastructure_epc",
    "PRIM": "infrastructure_epc",
    "EME": "infrastructure_epc",
    "FIX": "infrastructure_epc",
    "IESC": "infrastructure_epc",
    "STRL": "infrastructure_epc",
    "AGX": "infrastructure_epc",
    # Electrical / AI-Data Center Industrials
    "ETN": "electrical_industrial",
    "TT": "electrical_industrial",
    "HUBB": "electrical_industrial",
    "AME": "electrical_industrial",
    "ROK": "electrical_industrial",
    # Power Generation / Standby
    "GNRC": "power_generation",
    "VRT": "power_generation",
    "MOD": "power_generation",
    # Defense / Government Services
    "LMT": "defense_government",
    "RTX": "defense_government",
    "NOC": "defense_government",
    "GD": "defense_government",
    "LDOS": "defense_government",
    "HII": "defense_government",
    "KTOS": "defense_government",
    "AVAV": "defense_government",
    # Semicap Equipment
    "AMAT": "semicap_equipment",
    "LRCX": "semicap_equipment",
    "KLAC": "semicap_equipment",
    "ENTG": "semicap_equipment",
    # Healthcare Tools / Large Pharma
    "DHR": "healthcare_tools",
    "TMO": "healthcare_tools",
    "A": "healthcare_tools",
    "LLY": "healthcare_tools",
    "ABBV": "healthcare_tools",
    "ISRG": "healthcare_tools",
    "IDXX": "healthcare_tools",
    "ZTS": "healthcare_tools",
    "MTD": "healthcare_tools",
    # Energy Infrastructure / Midstream
    "WMB": "energy_midstream",
    "KMI": "energy_midstream",
    "OKE": "energy_midstream",
    "TRGP": "energy_midstream",
    # Diversified Industrials
    "HON": "industrial_diversified",
    "GE": "industrial_diversified",
    "ITW": "industrial_diversified",
    "EMR": "industrial_diversified",
    "PH": "industrial_diversified",
    "DOV": "industrial_diversified",
    "CAT": "industrial_diversified",
    # Quality Compounders / Financial Data
    "V": "financial_data",
    "MA": "financial_data",
    "SPGI": "financial_data",
    "MCO": "financial_data",
    "MSCI": "financial_data",
    # Construction Materials
    "MLM": "construction_materials",
    "VMC": "construction_materials",
    "EXP": "construction_materials",
}

# Factors: cross-cutting macro bets. One ticker can appear in multiple factors.
# This is where hidden concentration lives — when multiple themes share a factor.
FACTOR_MEMBERSHIP: dict[str, list[str]] = {
    "power_buildout": [
        "GNRC", "VRT", "MOD",           # generation
        "ETN", "HUBB", "AME", "ROK",     # electrical equipment
        "DY", "MTZ",                      # grid construction
        "EMR",                            # industrial automation for power
        "PWR",                            # electrical EPC
    ],
    "ai_capex_cycle": [
        "AMAT", "LRCX", "KLAC", "ENTG",  # semicap equipment
        "VRT",                            # AI data center power
        "ETN", "HUBB",                   # data center electrical
    ],
    "us_defense_budget": [
        "LMT", "RTX", "NOC", "GD", "LDOS",
        "HII", "KTOS", "AVAV",
    ],
    "us_infrastructure_spending": [
        "ACM", "J", "FLR", "DY", "PWR", "MTZ", "PRIM",
        "EME", "FIX", "IESC", "STRL",
        "MLM", "VMC", "EXP",              # aggregates/materials
    ],
    "energy_transition": [
        "KMI", "WMB", "OKE", "TRGP",     # gas infrastructure
        "GNRC",                           # backup/standby power
        "ETN",                            # grid modernization
    ],
    "industrial_cycle": [
        "CAT", "EMR", "ETN", "HON", "AME",
        "PH", "DOV", "ITW", "GE",
    ],
    "rate_sensitive_growth": [
        "SPGI", "MCO", "MSCI",
        "V", "MA",
        "ISRG", "IDXX",
        "LLY", "ABBV",
    ],
}

THEME_DESCRIPTIONS = {
    "infrastructure_epc": "Infrastructure / EPC contractors",
    "electrical_industrial": "Electrical equipment / AI-datacenter industrials",
    "power_generation": "Power generation & standby (Generac, Vertiv, Modine)",
    "defense_government": "Defense primes & government IT services",
    "semicap_equipment": "Semiconductor capital equipment",
    "healthcare_tools": "Healthcare tools, diagnostics & large pharma",
    "energy_midstream": "Energy infrastructure / midstream gas",
    "industrial_diversified": "Diversified industrials (Emerson, Honeywell, GE…)",
    "financial_data": "Financial data & quality compounders",
    "construction_materials": "Aggregates & building materials",
}

FACTOR_DESCRIPTIONS = {
    "power_buildout": "US power grid & electrification buildout",
    "ai_capex_cycle": "AI / datacenter capex cycle (semicap + infrastructure)",
    "us_defense_budget": "US federal defense appropriations",
    "us_infrastructure_spending": "US bipartisan infrastructure bill spend",
    "energy_transition": "Energy transition & gas infrastructure",
    "industrial_cycle": "Global industrial / manufacturing cycle",
    "rate_sensitive_growth": "Rate-sensitive quality growth (long-duration earnings)",
}


def compute_theme_weights(tickers: list[str]) -> dict[str, float]:
    """Compute portfolio weight per theme assuming equal weighting across tickers.

    Returns {theme: fraction_of_portfolio}. Tickers not in THEME_MEMBERSHIP get
    assigned to 'unknown'. Fractions sum to 1.0.
    """
    if not tickers:
        return {}
    n = len(tickers)
    counts: dict[str, int] = {}
    for t in tickers:
        theme = THEME_MEMBERSHIP.get(t.upper(), "unknown")
        counts[theme] = counts.get(theme, 0) + 1
    return {theme: count / n for theme, count in sorted(counts.items())}


def compute_factor_weights(tickers: list[str]) -> dict[str, float]:
    """Compute portfolio weight per factor (tickers can appear in multiple factors).

    Returns {factor: fraction_of_portfolio} where fraction = (tickers in factor) / total_tickers.
    This deliberately over-counts when a ticker appears in multiple factors —
    that overlap IS the concentration risk we want to surface.
    """
    if not tickers:
        return {}
    n = len(tickers)
    upper_tickers = [t.upper() for t in tickers]
    weights = {}
    for factor, members in FACTOR_MEMBERSHIP.items():
        hits = sum(1 for t in upper_tickers if t in members)
        if hits > 0:
            weights[factor] = hits / n
    return weights


def compute_rolling_correlations(
    tickers: list[str],
    lookback_days: int = 90,
) -> dict[str, float]:
    """Compute pairwise rolling correlations for portfolio tickers.

    Returns {"{ticker_a}_{ticker_b}": correlation} for all unique pairs.
    Requires yfinance. Returns empty dict on failure (data issue, not a crash).
    """
    if len(tickers) < 2:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}

    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days + 10)

    try:
        raw = yf.download(
            [t.upper() for t in tickers],
            start=str(start),
            end=str(end),
            auto_adjust=True,
            progress=False,
        )
        if raw is None or raw.empty:
            return {}

        if hasattr(raw.columns, "levels"):
            close = raw["Close"]
        else:
            close = raw

        returns = close.pct_change().dropna()
        if len(returns) < 20:
            return {}

        results = {}
        ticker_list = [t.upper() for t in tickers]
        for i, t1 in enumerate(ticker_list):
            for t2 in ticker_list[i + 1 :]:
                if t1 in returns.columns and t2 in returns.columns:
                    corr = float(returns[t1].corr(returns[t2]))
                    if not math.isnan(corr):
                        key = f"{t1}_{t2}"
                        results[key] = round(corr, 4)
        return results

    except Exception:
        return {}


def detect_correlation_clusters(
    correlations: dict[str, float],
    threshold: float = 0.70,
) -> list[list[str]]:
    """Identify groups of tickers with pairwise correlation >= threshold.

    Returns list of clusters (each cluster is a list of ticker strings).
    A cluster of 4+ is a hidden concentration risk.
    """
    # Build adjacency from correlated pairs
    adj: dict[str, set[str]] = {}
    for key, corr in correlations.items():
        if corr >= threshold:
            t1, t2 = key.split("_", 1)
            adj.setdefault(t1, set()).add(t2)
            adj.setdefault(t2, set()).add(t1)

    # Simple greedy clustering: BFS
    visited: set[str] = set()
    clusters: list[list[str]] = []
    for seed in sorted(adj.keys()):
        if seed in visited:
            continue
        cluster = set()
        queue = [seed]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(cluster) >= 2:
            clusters.append(sorted(cluster))

    return sorted(clusters, key=len, reverse=True)


def generate_exposure_warnings(
    theme_weights: dict[str, float],
    factor_weights: dict[str, float],
    correlations: dict[str, float],
    constitution: dict | None = None,
) -> list[str]:
    """Generate human-readable concentration warnings without raising exceptions."""
    from .constitution import load_constitution

    cfg = constitution or load_constitution()
    theme_limit = float(cfg.get("MAX_SINGLE_THEME_EXPOSURE", 0.25))
    factor_limit = float(cfg.get("MAX_SINGLE_FACTOR_EXPOSURE", 0.40))
    cluster_warn = int(cfg.get("WARN_CORRELATED_CLUSTER_SIZE", 4))

    warnings = []

    for theme, w in theme_weights.items():
        if theme == "unknown":
            continue
        desc = THEME_DESCRIPTIONS.get(theme, theme)
        if w > theme_limit:
            warnings.append(
                f"[VIOLATION] Theme '{theme}' ({desc}): {w:.1%} exceeds {theme_limit:.1%} limit"
            )
        elif w >= theme_limit * 0.80:
            warnings.append(
                f"[WATCH] Theme '{theme}' ({desc}): {w:.1%} approaching {theme_limit:.1%} limit"
            )

    for factor, w in factor_weights.items():
        desc = FACTOR_DESCRIPTIONS.get(factor, factor)
        if w > factor_limit:
            warnings.append(
                f"[VIOLATION] Factor '{factor}' ({desc}): {w:.1%} exceeds {factor_limit:.1%} limit"
            )
        elif w >= factor_limit * 0.75:
            warnings.append(
                f"[WATCH] Factor '{factor}' ({desc}): {w:.1%} approaching {factor_limit:.1%} limit"
            )

    clusters = detect_correlation_clusters(correlations, threshold=0.70)
    for cluster in clusters:
        if len(cluster) >= cluster_warn:
            warnings.append(
                f"[WATCH] Correlation cluster ({len(cluster)} tickers): "
                f"{', '.join(cluster)} — high co-movement risk"
            )

    return warnings


def run_exposure_analysis(
    positions_path: Path | None = None,
    fetch_correlations: bool = True,
    persist: bool = True,
) -> dict:
    """Load paper positions and run full exposure analysis.

    Returns dict with theme_weights, factor_weights, correlations, warnings.
    """
    path = positions_path or _POSITIONS_PATH
    if not path.exists():
        return {
            "tickers": [],
            "theme_weights": {},
            "factor_weights": {},
            "correlations": {},
            "warnings": ["No paper positions file found"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    with open(path) as f:
        data = yaml.safe_load(f)

    positions = data.get("positions", []) if data else []
    tickers = [p["ticker"] for p in positions if "ticker" in p]

    theme_weights = compute_theme_weights(tickers)
    factor_weights = compute_factor_weights(tickers)
    correlations = compute_rolling_correlations(tickers) if fetch_correlations else {}
    warnings = generate_exposure_warnings(theme_weights, factor_weights, correlations)

    result = {
        "tickers": tickers,
        "n_positions": len(tickers),
        "theme_weights": theme_weights,
        "factor_weights": factor_weights,
        "correlations": correlations,
        "warnings": warnings,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if persist:
        _DATA_PATH.mkdir(parents=True, exist_ok=True)
        append_jsonl(_EXPOSURE_LOG, result)

    return result
