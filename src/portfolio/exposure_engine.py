"""Portfolio Exposure Engine — multi-theme concentration analysis.

Unlike governance/exposure.py (single primary theme per ticker), this engine
assigns tickers to multiple themes simultaneously. Thematic overlap is the
hidden concentration risk the portfolio may not perceive.

Key output: "effective_bets" — how many truly independent macro bets does this
portfolio represent, regardless of how many tickers it holds.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Optional

import yaml

_THEMES_PATH = Path(__file__).parent.parent.parent / "config" / "themes.yaml"


# ─── Config loading ───────────────────────────────────────────────────────────

def load_themes(path: Path | None = None) -> dict:
    """Load themes.yaml. Returns empty dict if file missing (graceful degradation)."""
    p = path or _THEMES_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def build_ticker_theme_map(themes_cfg: dict) -> dict[str, list[str]]:
    """Return {ticker_upper: [theme_name, ...]} from themes.yaml."""
    membership: dict[str, list[str]] = {}
    for theme_name, theme_data in themes_cfg.get("themes", {}).items():
        for ticker in theme_data.get("tickers", []):
            upper = ticker.upper()
            membership.setdefault(upper, []).append(theme_name)
    return membership


def get_theme_limits(themes_cfg: dict) -> dict:
    """Return concentration limits from themes.yaml limits section."""
    return themes_cfg.get("limits", {
        "max_single_theme": 0.25,
        "max_leverage_cluster": 0.20,
        "max_policy_cluster": 0.25,
        "max_cyclical_cluster": 0.35,
        "max_factor_dominance": 0.40,
        "max_single_position": 0.10,
    })


# ─── Exposure computation ─────────────────────────────────────────────────────

def compute_theme_exposure(
    tickers: list[str],
    ticker_theme_map: dict[str, list[str]],
) -> dict[str, float]:
    """Compute per-theme exposure as fraction of portfolio (multi-theme, sums >1.0).

    Each ticker contributes 1/N to each of its themes. A theme with 5 of 12
    tickers shows 41.7% exposure — deliberate overlap is the signal.
    """
    if not tickers:
        return {}
    n = len(tickers)
    counts: dict[str, float] = {}
    for t in tickers:
        for theme in ticker_theme_map.get(t.upper(), ["unclassified"]):
            counts[theme] = counts.get(theme, 0.0) + 1.0 / n
    return {k: round(v, 4) for k, v in sorted(counts.items(), key=lambda x: -x[1])}


def get_cluster_tickers(
    tickers: list[str],
    cluster_theme: str,
    ticker_theme_map: dict[str, list[str]],
) -> list[str]:
    """Return which portfolio tickers are members of a given theme cluster."""
    return [t for t in tickers if cluster_theme in ticker_theme_map.get(t.upper(), [])]


# ─── Effective diversification ────────────────────────────────────────────────

def _cosine_similarity(vec_a: list[str], vec_b: list[str]) -> float:
    """Jaccard similarity of two theme membership lists."""
    set_a, set_b = set(vec_a), set(vec_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _cluster_tickers_by_theme_overlap(
    tickers: list[str],
    ticker_theme_map: dict[str, list[str]],
    similarity_threshold: float = 0.40,
) -> list[list[str]]:
    """Group tickers into clusters where thematic overlap >= threshold.

    Returns list of clusters (each cluster = list of tickers).
    Tickers with no theme overlap are their own cluster.
    """
    upper = [t.upper() for t in tickers]
    themes_by_ticker = {t: ticker_theme_map.get(t, []) for t in upper}

    # Build adjacency
    adj: dict[str, set[str]] = {t: set() for t in upper}
    for i, t1 in enumerate(upper):
        for t2 in upper[i + 1:]:
            sim = _cosine_similarity(themes_by_ticker[t1], themes_by_ticker[t2])
            if sim >= similarity_threshold:
                adj[t1].add(t2)
                adj[t2].add(t1)

    # BFS clustering
    visited: set[str] = set()
    clusters: list[list[str]] = []
    for seed in upper:
        if seed in visited:
            continue
        cluster = []
        queue = [seed]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            cluster.append(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        clusters.append(sorted(cluster))

    return sorted(clusters, key=lambda c: (-len(c), c[0]))


def estimate_effective_bets(
    tickers: list[str],
    ticker_theme_map: dict[str, list[str]],
    similarity_threshold: float = 0.40,
) -> tuple[float, list[list[str]]]:
    """Estimate the number of independent macro bets in the portfolio.

    Returns (effective_n, clusters) where effective_n is continuous
    (accounting for partial within-cluster diversification).

    A portfolio with 12 tickers but 5 clusters has ~5 effective bets.
    """
    if not tickers:
        return 0.0, []

    clusters = _cluster_tickers_by_theme_overlap(tickers, ticker_theme_map, similarity_threshold)
    n = len(tickers)

    # Continuous adjustment: each cluster of k tickers counts as 1 + log2(k)/4 bets
    # — allows partial credit for within-cluster diversification
    effective = sum(1.0 + math.log2(len(c)) / 4.0 for c in clusters)
    return round(effective, 1), clusters


# ─── Cluster analysis ─────────────────────────────────────────────────────────

def analyze_clusters(
    tickers: list[str],
    ticker_theme_map: dict[str, list[str]],
    limits: dict,
) -> dict:
    """Compute leverage, policy, and cyclical cluster exposures."""
    n = len(tickers) if tickers else 1

    leverage = get_cluster_tickers(tickers, "leverage_sensitive", ticker_theme_map)
    policy = get_cluster_tickers(tickers, "policy_sensitive", ticker_theme_map)
    cyclical = get_cluster_tickers(tickers, "cyclical_industrial", ticker_theme_map)
    semicap = get_cluster_tickers(tickers, "semiconductor_cycle", ticker_theme_map)
    cyclical_all = sorted(set(cyclical + semicap))

    return {
        "leverage_cluster": {
            "tickers": leverage,
            "exposure": round(len(leverage) / n, 4),
            "limit": limits.get("max_leverage_cluster", 0.20),
            "breached": len(leverage) / n > limits.get("max_leverage_cluster", 0.20),
        },
        "policy_cluster": {
            "tickers": policy,
            "exposure": round(len(policy) / n, 4),
            "limit": limits.get("max_policy_cluster", 0.25),
            "breached": len(policy) / n > limits.get("max_policy_cluster", 0.25),
        },
        "cyclical_cluster": {
            "tickers": cyclical_all,
            "exposure": round(len(cyclical_all) / n, 4),
            "limit": limits.get("max_cyclical_cluster", 0.35),
            "breached": len(cyclical_all) / n > limits.get("max_cyclical_cluster", 0.35),
        },
    }


# ─── Hidden dependency analysis ───────────────────────────────────────────────

def identify_hidden_dependencies(
    tickers: list[str],
    theme_exposure: dict[str, float],
    clusters: list[list[str]],
) -> list[str]:
    """Surface non-obvious portfolio-level risks from theme overlap patterns."""
    deps = []
    n = len(tickers)

    # Find themes where ≥3 tickers are in a theme but in 2+ different primary sectors
    high_exposure = [(t, w) for t, w in theme_exposure.items() if w > 0.25]
    if high_exposure:
        theme_list = ", ".join(f"{t} ({w:.0%})" for t, w in high_exposure[:5])
        deps.append(
            f"Sector diversification is illusory: themes {theme_list} each exceed 25% — "
            f"apparent sector diversity masks shared macro dependencies"
        )

    # Cluster warning
    large_clusters = [c for c in clusters if len(c) >= 3]
    for c in large_clusters:
        deps.append(
            f"Thematic cluster [{', '.join(c)}]: {len(c)}/{n} positions share "
            f"≥40% of theme membership — synchronized drawdown risk"
        )

    # Policy/government dependency
    policy_themes = {t: w for t, w in theme_exposure.items()
                     if t in ("government_spending", "policy_sensitive", "defense")}
    total_policy = sum(w for w in policy_themes.values() if w > 0)
    if total_policy > 0.50:
        deps.append(
            f"Government dependency: combined government_spending + policy_sensitive + defense = "
            f"{total_policy:.0%} — single appropriations or policy shift is a portfolio-wide event"
        )

    return deps


# ─── Warning generation ───────────────────────────────────────────────────────

def generate_exposure_warnings(
    theme_exposure: dict[str, float],
    clusters: dict,
    limits: dict,
) -> list[str]:
    """Generate prioritized concentration warnings."""
    warnings = []

    theme_limit = limits.get("max_single_theme", 0.25)
    for theme, w in theme_exposure.items():
        if theme == "unclassified":
            continue
        if w > theme_limit:
            warnings.append(
                f"[BLOCK] Theme '{theme}': {w:.1%} exceeds {theme_limit:.1%} hard limit"
            )
        elif w >= theme_limit * 0.80:
            warnings.append(
                f"[WATCH] Theme '{theme}': {w:.1%} approaching {theme_limit:.1%} limit"
            )

    for cluster_key, cluster_data in clusters.items():
        if cluster_data["breached"]:
            warnings.append(
                f"[BLOCK] {cluster_key.replace('_', ' ').title()}: "
                f"{cluster_data['exposure']:.1%} of portfolio "
                f"({', '.join(cluster_data['tickers'])}) "
                f"exceeds {cluster_data['limit']:.1%} hard limit"
            )

    return warnings


# ─── Portfolio narrative ──────────────────────────────────────────────────────

def build_portfolio_narrative(
    n_positions: int,
    effective_bets: float,
    clusters: list[list[str]],
    theme_exposure: dict[str, float],
) -> str:
    """Produce a one-paragraph plain-language portfolio characterization."""
    top_themes = [t for t, _ in list(theme_exposure.items())[:3]]
    cluster_descs = [f"[{', '.join(c)}]" for c in clusters[:4]]

    return (
        f"This portfolio holds {n_positions} positions but represents approximately "
        f"{effective_bets:.0f} effective macro bets. "
        f"Primary thematic concentrations: {', '.join(top_themes)}. "
        f"Economic clusters: {'; '.join(cluster_descs)}. "
        f"The apparent sector diversification masks correlated macro exposures — "
        f"a single adverse regime shift could impair multiple clusters simultaneously."
    )


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_portfolio_exposure(
    tickers: list[str],
    themes_path: Path | None = None,
    position_weights: Optional[dict[str, float]] = None,
) -> dict:
    """Run full portfolio exposure analysis.

    Args:
        tickers: portfolio ticker list
        themes_path: override path to themes.yaml
        position_weights: {ticker: fraction} — if None, assumes equal weighting

    Returns dict with theme_exposure, clusters, effective_bets, warnings, narrative, etc.
    """
    themes_cfg = load_themes(themes_path)
    ticker_theme_map = build_ticker_theme_map(themes_cfg)
    limits = get_theme_limits(themes_cfg)

    n = len(tickers)
    weights = position_weights or {t: 1.0 / n for t in tickers} if n > 0 else {}

    theme_exposure = compute_theme_exposure(tickers, ticker_theme_map)
    cluster_analysis = analyze_clusters(tickers, ticker_theme_map, limits)
    effective_bets, clusters = estimate_effective_bets(tickers, ticker_theme_map)
    hidden_deps = identify_hidden_dependencies(tickers, theme_exposure, clusters)
    warnings = generate_exposure_warnings(theme_exposure, cluster_analysis, limits)
    narrative = build_portfolio_narrative(n, effective_bets, clusters, theme_exposure)

    # Per-ticker theme membership for transparency
    memberships = {
        t.upper(): ticker_theme_map.get(t.upper(), ["unclassified"])
        for t in tickers
    }

    # Unclassified tickers
    unclassified = [t for t in tickers if not ticker_theme_map.get(t.upper())]

    return {
        "tickers": [t.upper() for t in tickers],
        "n_positions": n,
        "effective_bets": effective_bets,
        "effective_diversification_ratio": round(effective_bets / n, 3) if n > 0 else 0.0,
        "theme_exposure": theme_exposure,
        "theme_memberships": memberships,
        "leverage_cluster": cluster_analysis["leverage_cluster"],
        "policy_cluster": cluster_analysis["policy_cluster"],
        "cyclical_cluster": cluster_analysis["cyclical_cluster"],
        "macro_clusters": [[t for t in c] for c in clusters],
        "hidden_dependencies": hidden_deps,
        "warnings": warnings,
        "unclassified_tickers": unclassified,
        "narrative": narrative,
    }
