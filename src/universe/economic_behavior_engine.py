"""Economic Behavior Engine — measures how economically distinct tickers actually are.

Sector labels are insufficient. Two companies in different sectors may be
nearly identical economic bets. Two companies in the same sector may be
uncorrelated. This engine measures behavior overlap, not sector overlap.

Core metric: archetype Jaccard similarity.
  0.0 = completely distinct economic behaviors
  1.0 = identical archetype membership (behavioral clone)

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .universe_classifier import (
    load_taxonomy,
    build_ticker_archetype_map,
    load_current_universe,
    ARCHETYPE_CHARACTERISTICS,
)

# Behavioral clustering threshold — tickers sharing >= this fraction of
# their archetypes are in the same behavioral cluster.
_BEHAVIOR_CLUSTER_THRESHOLD = 0.45

# Regime definitions: which archetypes are stressed / benefited under each regime
_REGIME_ARCHETYPE_SENSITIVITIES: dict[str, dict[str, float]] = {
    "recession": {
        "cyclical_industrial": -0.80, "AI_capex": -0.85, "housing_sensitive": -0.75,
        "commodity_sensitive": -0.60, "healthcare_cyclical": -0.35,
        "leverage_sensitive": -0.50, "capital_intensive": -0.55,
        "consumer_staples": +0.10, "regulated_utility": +0.15,
        "healthcare_stable": +0.10, "defense": +0.05,
        "recession_resilient": +0.05, "defensive_compounder": +0.10,
        "software_platform": -0.15, "financial_data": -0.20,
        "payments_network": -0.15, "quality_compounder": +0.05,
        "infrastructure": -0.40, "government_spending": -0.10,
        "energy_infrastructure": -0.15, "telecom_infrastructure": -0.20,
        "global_diversifier": -0.30, "asset_manager": -0.45,
        "capital_light": -0.10, "policy_sensitive": -0.20,
    },
    "rates_shock": {
        "leverage_sensitive": -0.70, "energy_infrastructure": -0.40,
        "capital_intensive": -0.30, "regulated_utility": -0.35,
        "telecom_infrastructure": -0.30, "housing_sensitive": -0.50,
        "healthcare_cyclical": -0.20, "financial_data": -0.15,
        "consumer_staples": -0.10, "defense": -0.05,
        "payments_network": +0.05, "cyclical_industrial": -0.20,
        "AI_capex": -0.25, "quality_compounder": -0.15,
        "software_platform": -0.10, "capital_light": -0.05,
        "asset_manager": -0.25, "commodity_sensitive": -0.15,
        "recession_resilient": -0.08, "defensive_compounder": -0.08,
    },
    "ai_capex_slowdown": {
        "AI_capex": -0.90, "cyclical_industrial": -0.45,
        "infrastructure": -0.20, "software_platform": -0.10,
        "capital_intensive": -0.25, "energy_infrastructure": -0.05,
        "defense": -0.03, "consumer_staples": 0.0,
        "regulated_utility": 0.0, "healthcare_stable": 0.0,
        "quality_compounder": -0.05, "payments_network": -0.05,
    },
    "policy_austerity": {
        "government_spending": -0.80, "defense": -0.65,
        "policy_sensitive": -0.70, "infrastructure": -0.40,
        "cyclical_industrial": -0.20, "consumer_staples": +0.05,
        "healthcare_stable": +0.05, "regulated_utility": 0.0,
        "quality_compounder": -0.05, "financial_data": -0.10,
        "software_platform": -0.10, "payments_network": -0.05,
    },
    "growth_expansion": {
        "cyclical_industrial": +0.60, "AI_capex": +0.70,
        "housing_sensitive": +0.50, "commodity_sensitive": +0.40,
        "infrastructure": +0.35, "software_platform": +0.30,
        "consumer_staples": -0.05, "regulated_utility": -0.10,
        "defense": +0.05, "quality_compounder": +0.20,
        "healthcare_stable": +0.10, "payments_network": +0.25,
        "financial_data": +0.25, "asset_manager": +0.40,
    },
}


@dataclass
class BehaviorCluster:
    tickers: list[str]
    shared_archetypes: list[str]
    regime_sensitivity: dict[str, float]   # avg sensitivity per regime
    behavioral_label: str                  # dominant archetype description


@dataclass
class BehaviorAnalysis:
    n_tickers: int
    behavior_clusters: list[BehaviorCluster]
    n_behavior_clusters: int
    effective_economic_bets: float         # continuous estimate
    similarity_matrix: dict[str, dict[str, float]]
    most_redundant_pair: tuple[str, str] | None
    most_distinct_pair: tuple[str, str] | None
    max_similarity: float
    min_similarity: float
    avg_pairwise_similarity: float
    regime_diversification_scores: dict[str, float]  # per regime
    overall_regime_diversity: float
    always_vulnerable_archetypes: list[str]  # hurt in recession + rates shock


def _jaccard_similarity(archetypes_a: list[str], archetypes_b: list[str]) -> float:
    """Jaccard similarity between two archetype membership lists."""
    set_a, set_b = set(archetypes_a), set(archetypes_b)
    if not set_a or not set_b:
        return 0.0
    return round(len(set_a & set_b) / len(set_a | set_b), 4)


def _cluster_by_behavior(
    tickers: list[str],
    archetype_map: dict[str, list[str]],
    threshold: float = _BEHAVIOR_CLUSTER_THRESHOLD,
) -> list[list[str]]:
    """Cluster tickers by behavioral similarity using BFS."""
    upper = [t.upper() for t in tickers]
    adj: dict[str, list[str]] = {t: [] for t in upper}

    for i, t1 in enumerate(upper):
        for t2 in upper[i + 1:]:
            sim = _jaccard_similarity(archetype_map.get(t1, []), archetype_map.get(t2, []))
            if sim >= threshold:
                adj[t1].append(t2)
                adj[t2].append(t1)

    visited: set[str] = set()
    clusters: list[list[str]] = []
    for seed in upper:
        if seed in visited:
            continue
        cluster: list[str] = []
        queue = [seed]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            cluster.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    queue.append(neighbor)
        clusters.append(sorted(cluster))

    return sorted(clusters, key=lambda c: (-len(c), c[0]))


def _effective_bets(clusters: list[list[str]]) -> float:
    """Continuous diversification measure (same formula as portfolio exposure engine)."""
    return round(sum(1.0 + math.log2(len(c)) / 4.0 for c in clusters), 1)


def _shared_archetypes(archetypes_a: list[str], archetypes_b: list[str]) -> list[str]:
    return sorted(set(archetypes_a) & set(archetypes_b))


def _cluster_regime_sensitivity(
    cluster_archetypes: list[str],
    regime_sensitivities: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Average regime sensitivity for a cluster's archetype set."""
    result = {}
    for regime, sensitivities in regime_sensitivities.items():
        if cluster_archetypes:
            avg = sum(sensitivities.get(a, 0.0) for a in cluster_archetypes) / len(cluster_archetypes)
        else:
            avg = 0.0
        result[regime] = round(avg, 4)
    return result


def _regime_diversification_score(
    clusters: list[list[str]],
    archetype_map: dict[str, list[str]],
    regime: str,
    regime_sensitivities: dict[str, dict[str, float]],
) -> float:
    """Score how diversified the universe is across a specific regime.

    High = clusters have different regime sensitivities (good diversification).
    Low = all clusters move together in this regime (concentrated risk).
    Returns 0.0–1.0.
    """
    if len(clusters) <= 1:
        return 0.0
    sens_values = []
    for cluster in clusters:
        archetypes = set()
        for t in cluster:
            archetypes.update(archetype_map.get(t, []))
        cluster_sensitivities = regime_sensitivities.get(regime, {})
        avg = (
            sum(cluster_sensitivities.get(a, 0.0) for a in archetypes) / len(archetypes)
            if archetypes else 0.0
        )
        sens_values.append(avg)
    if not sens_values:
        return 0.5
    spread = max(sens_values) - min(sens_values)
    # Normalize: full spread of 2.0 (from -1 to +1) = perfect diversification
    return round(min(1.0, spread / 1.5), 4)


def _dominant_archetype(cluster_tickers: list[str], archetype_map: dict[str, list[str]]) -> str:
    """Find the most commonly shared archetype in a cluster."""
    archetype_counts: dict[str, int] = {}
    for t in cluster_tickers:
        for a in archetype_map.get(t, []):
            archetype_counts[a] = archetype_counts.get(a, 0) + 1
    if not archetype_counts:
        return "unclassified"
    return max(archetype_counts.items(), key=lambda x: x[1])[0]


def run_behavior_analysis(
    tickers: list[str],
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
) -> BehaviorAnalysis:
    """Run full economic behavior analysis on a set of tickers."""
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    archetype_map = build_ticker_archetype_map(taxonomy_cfg)
    upper = [t.upper() for t in tickers]
    n = len(upper)

    if n == 0:
        return BehaviorAnalysis(
            n_tickers=0, behavior_clusters=[], n_behavior_clusters=0,
            effective_economic_bets=0.0, similarity_matrix={},
            most_redundant_pair=None, most_distinct_pair=None,
            max_similarity=0.0, min_similarity=0.0, avg_pairwise_similarity=0.0,
            regime_diversification_scores={}, overall_regime_diversity=0.0,
            always_vulnerable_archetypes=[],
        )

    # Pairwise similarity matrix
    sim_matrix: dict[str, dict[str, float]] = {t: {} for t in upper}
    all_sims: list[float] = []
    max_sim, min_sim = 0.0, 1.0
    most_redundant: tuple[str, str] | None = None
    most_distinct: tuple[str, str] | None = None

    for i, t1 in enumerate(upper):
        for t2 in upper[i + 1:]:
            sim = _jaccard_similarity(archetype_map.get(t1, []), archetype_map.get(t2, []))
            sim_matrix[t1][t2] = sim
            sim_matrix[t2][t1] = sim
            all_sims.append(sim)
            if sim > max_sim:
                max_sim = sim
                most_redundant = (t1, t2)
            if sim < min_sim:
                min_sim = sim
                most_distinct = (t1, t2)

    avg_sim = round(sum(all_sims) / len(all_sims), 4) if all_sims else 0.0

    # Behavioral clusters
    raw_clusters = _cluster_by_behavior(upper, archetype_map)
    eff_bets = _effective_bets(raw_clusters)

    behavior_clusters = []
    for cluster in raw_clusters:
        cluster_archetypes = set()
        for t in cluster:
            cluster_archetypes.update(archetype_map.get(t, []))
        shared = sorted(cluster_archetypes)
        regime_sens = _cluster_regime_sensitivity(
            shared, _REGIME_ARCHETYPE_SENSITIVITIES
        )
        dominant = _dominant_archetype(cluster, archetype_map)
        behavior_clusters.append(BehaviorCluster(
            tickers=cluster,
            shared_archetypes=shared,
            regime_sensitivity=regime_sens,
            behavioral_label=dominant,
        ))

    # Regime diversification
    regime_scores: dict[str, float] = {}
    for regime in _REGIME_ARCHETYPE_SENSITIVITIES:
        regime_scores[regime] = _regime_diversification_score(
            raw_clusters, archetype_map, regime, _REGIME_ARCHETYPE_SENSITIVITIES
        )
    overall_regime_div = round(
        sum(regime_scores.values()) / len(regime_scores), 4
    ) if regime_scores else 0.0

    # Archetypes hurt in both recession AND rates shock → concentrated vulnerability
    recession_sens = _REGIME_ARCHETYPE_SENSITIVITIES.get("recession", {})
    rates_sens = _REGIME_ARCHETYPE_SENSITIVITIES.get("rates_shock", {})
    always_vulnerable = [
        a for a in set(recession_sens) | set(rates_sens)
        if recession_sens.get(a, 0) < -0.30 and rates_sens.get(a, 0) < -0.20
    ]

    return BehaviorAnalysis(
        n_tickers=n,
        behavior_clusters=behavior_clusters,
        n_behavior_clusters=len(behavior_clusters),
        effective_economic_bets=eff_bets,
        similarity_matrix=sim_matrix,
        most_redundant_pair=most_redundant,
        most_distinct_pair=most_distinct,
        max_similarity=max_sim,
        min_similarity=min_sim,
        avg_pairwise_similarity=avg_sim,
        regime_diversification_scores=regime_scores,
        overall_regime_diversity=overall_regime_div,
        always_vulnerable_archetypes=sorted(always_vulnerable),
    )
