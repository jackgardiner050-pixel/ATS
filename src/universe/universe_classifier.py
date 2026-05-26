"""Universe Classifier — economic behavior classification for every ticker.

Classifies tickers by economic archetype, NOT GICS sector. Two companies in
different sectors may behave identically. Two companies in the same sector
may be nearly uncorrelated. The classifier surfaces that.

Derived scores (cyclicality, defensiveness, etc.) are averages across a
ticker's archetype memberships — a ticker in many cyclical archetypes gets
a high cyclicality score regardless of what sector it's in.

No LLM calls. No network access. Fully deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_TAXONOMY_PATH = Path(__file__).parent.parent.parent / "config" / "universe_taxonomy.yaml"
_UNIVERSE_PATH = Path(__file__).parent.parent.parent / "config" / "universe.yaml"

# ─── Archetype base characteristic scores ────────────────────────────────────
# Each archetype has inherent characteristic scores that inform per-ticker
# derived scores when a ticker belongs to multiple archetypes.
# (cyclicality, defensiveness, recession_sensitivity, policy_sensitivity,
#  leverage_sensitivity, capital_intensity)

ARCHETYPE_CHARACTERISTICS: dict[str, dict[str, float]] = {
    "defensive_compounder":  {
        "cyclicality": 0.15, "defensiveness": 0.85, "recession_sensitivity": 0.10,
        "policy_sensitivity": 0.10, "leverage_sensitivity": 0.20, "capital_intensity": 0.20,
    },
    "cyclical_industrial":   {
        "cyclicality": 0.85, "defensiveness": 0.10, "recession_sensitivity": 0.80,
        "policy_sensitivity": 0.25, "leverage_sensitivity": 0.35, "capital_intensity": 0.75,
    },
    "AI_capex":              {
        "cyclicality": 0.90, "defensiveness": 0.05, "recession_sensitivity": 0.85,
        "policy_sensitivity": 0.15, "leverage_sensitivity": 0.20, "capital_intensity": 0.60,
    },
    "infrastructure":        {
        "cyclicality": 0.65, "defensiveness": 0.25, "recession_sensitivity": 0.50,
        "policy_sensitivity": 0.50, "leverage_sensitivity": 0.40, "capital_intensity": 0.80,
    },
    "government_spending":   {
        "cyclicality": 0.40, "defensiveness": 0.55, "recession_sensitivity": 0.20,
        "policy_sensitivity": 0.90, "leverage_sensitivity": 0.30, "capital_intensity": 0.40,
    },
    "defense":               {
        "cyclicality": 0.20, "defensiveness": 0.80, "recession_sensitivity": 0.10,
        "policy_sensitivity": 0.85, "leverage_sensitivity": 0.30, "capital_intensity": 0.50,
    },
    "energy_infrastructure": {
        "cyclicality": 0.25, "defensiveness": 0.65, "recession_sensitivity": 0.20,
        "policy_sensitivity": 0.40, "leverage_sensitivity": 0.75, "capital_intensity": 0.85,
    },
    "regulated_utility":     {
        "cyclicality": 0.05, "defensiveness": 0.95, "recession_sensitivity": 0.05,
        "policy_sensitivity": 0.50, "leverage_sensitivity": 0.65, "capital_intensity": 0.90,
    },
    "healthcare_stable":     {
        "cyclicality": 0.15, "defensiveness": 0.85, "recession_sensitivity": 0.10,
        "policy_sensitivity": 0.20, "leverage_sensitivity": 0.20, "capital_intensity": 0.35,
    },
    "healthcare_cyclical":   {
        "cyclicality": 0.45, "defensiveness": 0.50, "recession_sensitivity": 0.40,
        "policy_sensitivity": 0.55, "leverage_sensitivity": 0.35, "capital_intensity": 0.40,
    },
    "software_platform":     {
        "cyclicality": 0.30, "defensiveness": 0.65, "recession_sensitivity": 0.30,
        "policy_sensitivity": 0.20, "leverage_sensitivity": 0.15, "capital_intensity": 0.15,
    },
    "financial_data":        {
        "cyclicality": 0.35, "defensiveness": 0.60, "recession_sensitivity": 0.25,
        "policy_sensitivity": 0.30, "leverage_sensitivity": 0.35, "capital_intensity": 0.15,
    },
    "payments_network":      {
        "cyclicality": 0.30, "defensiveness": 0.65, "recession_sensitivity": 0.25,
        "policy_sensitivity": 0.15, "leverage_sensitivity": 0.10, "capital_intensity": 0.10,
    },
    "consumer_staples":      {
        "cyclicality": 0.10, "defensiveness": 0.90, "recession_sensitivity": 0.05,
        "policy_sensitivity": 0.10, "leverage_sensitivity": 0.25, "capital_intensity": 0.30,
    },
    "recession_resilient":   {
        "cyclicality": 0.20, "defensiveness": 0.80, "recession_sensitivity": 0.10,
        "policy_sensitivity": 0.25, "leverage_sensitivity": 0.30, "capital_intensity": 0.35,
    },
    "housing_sensitive":     {
        "cyclicality": 0.75, "defensiveness": 0.10, "recession_sensitivity": 0.70,
        "policy_sensitivity": 0.20, "leverage_sensitivity": 0.40, "capital_intensity": 0.55,
    },
    "leverage_sensitive":    {
        "cyclicality": 0.45, "defensiveness": 0.35, "recession_sensitivity": 0.40,
        "policy_sensitivity": 0.30, "leverage_sensitivity": 0.90, "capital_intensity": 0.70,
    },
    "capital_light":         {
        "cyclicality": 0.25, "defensiveness": 0.70, "recession_sensitivity": 0.20,
        "policy_sensitivity": 0.15, "leverage_sensitivity": 0.10, "capital_intensity": 0.05,
    },
    "capital_intensive":     {
        "cyclicality": 0.65, "defensiveness": 0.20, "recession_sensitivity": 0.55,
        "policy_sensitivity": 0.25, "leverage_sensitivity": 0.45, "capital_intensity": 0.90,
    },
    "commodity_sensitive":   {
        "cyclicality": 0.70, "defensiveness": 0.15, "recession_sensitivity": 0.65,
        "policy_sensitivity": 0.20, "leverage_sensitivity": 0.40, "capital_intensity": 0.80,
    },
    "telecom_infrastructure":{
        "cyclicality": 0.35, "defensiveness": 0.55, "recession_sensitivity": 0.30,
        "policy_sensitivity": 0.35, "leverage_sensitivity": 0.55, "capital_intensity": 0.80,
    },
    "asset_manager":         {
        "cyclicality": 0.50, "defensiveness": 0.45, "recession_sensitivity": 0.45,
        "policy_sensitivity": 0.25, "leverage_sensitivity": 0.30, "capital_intensity": 0.10,
    },
    "quality_compounder":    {
        "cyclicality": 0.25, "defensiveness": 0.70, "recession_sensitivity": 0.20,
        "policy_sensitivity": 0.15, "leverage_sensitivity": 0.20, "capital_intensity": 0.20,
    },
    "global_diversifier":    {
        "cyclicality": 0.40, "defensiveness": 0.50, "recession_sensitivity": 0.35,
        "policy_sensitivity": 0.25, "leverage_sensitivity": 0.30, "capital_intensity": 0.40,
    },
    "policy_sensitive":      {
        "cyclicality": 0.45, "defensiveness": 0.40, "recession_sensitivity": 0.30,
        "policy_sensitivity": 0.85, "leverage_sensitivity": 0.35, "capital_intensity": 0.50,
    },
}

# Neutral defaults for tickers with no archetype classification
_DEFAULT_CHARACTERISTICS: dict[str, float] = {k: 0.50 for k in [
    "cyclicality", "defensiveness", "recession_sensitivity",
    "policy_sensitivity", "leverage_sensitivity", "capital_intensity",
]}

CHARACTERISTIC_NAMES = list(_DEFAULT_CHARACTERISTICS.keys())


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class TickerClassification:
    """Economic behavior classification for one ticker."""
    ticker: str
    archetype_memberships: list[str]
    cyclicality_score: float        # 0.0 = non-cyclical, 1.0 = max cyclical
    defensiveness_score: float      # 0.0 = no defense, 1.0 = max defensive
    recession_sensitivity: float    # 0.0 = immune, 1.0 = severe impact
    policy_sensitivity: float       # 0.0 = policy-independent, 1.0 = fully dependent
    leverage_sensitivity: float     # 0.0 = no leverage risk, 1.0 = max leverage risk
    capital_intensity: float        # 0.0 = capital-light, 1.0 = highly capital-intensive
    diversification_contribution: float  # 0.0 = redundant, 1.0 = highly unique
    in_current_universe: bool       # True if in universe.yaml
    characteristics: dict = field(default_factory=dict)


# ─── Config loading ───────────────────────────────────────────────────────────

def load_taxonomy(path: Path | None = None) -> dict:
    p = path or _TAXONOMY_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def load_current_universe(path: Path | None = None) -> list[str]:
    p = path or _UNIVERSE_PATH
    if not p.exists():
        return []
    with open(p) as f:
        cfg = yaml.safe_load(f) or {}
    return [t.upper() for t in cfg.get("universe", [])]


def build_ticker_archetype_map(taxonomy_cfg: dict) -> dict[str, list[str]]:
    """Return {ticker_upper: [archetype_name, ...]} from taxonomy."""
    membership: dict[str, list[str]] = {}
    for archetype, data in taxonomy_cfg.get("archetypes", {}).items():
        for ticker in data.get("tickers", []):
            upper = ticker.upper()
            membership.setdefault(upper, []).append(archetype)
    return membership


def get_taxonomy_limits(taxonomy_cfg: dict) -> dict:
    return taxonomy_cfg.get("limits", {
        "max_archetype_fraction": 0.20,
        "max_cyclical_fraction": 0.30,
        "max_policy_fraction": 0.20,
        "max_leverage_fraction": 0.15,
        "max_macro_dependency": 0.25,
        "min_defensive_fraction": 0.15,
        "min_recession_resilient_fraction": 0.10,
        "overrepresented_threshold": 0.25,
    })


# ─── Characteristic derivation ───────────────────────────────────────────────

def _derive_characteristics(archetypes: list[str]) -> dict[str, float]:
    """Average archetype base scores across all of a ticker's archetypes."""
    if not archetypes:
        return dict(_DEFAULT_CHARACTERISTICS)
    result = {k: 0.0 for k in CHARACTERISTIC_NAMES}
    for archetype in archetypes:
        scores = ARCHETYPE_CHARACTERISTICS.get(archetype, _DEFAULT_CHARACTERISTICS)
        for k in CHARACTERISTIC_NAMES:
            result[k] += scores.get(k, 0.50)
    n = len(archetypes)
    return {k: round(v / n, 4) for k, v in result.items()}


def _compute_diversification_contribution(
    ticker: str,
    archetypes: list[str],
    ticker_archetype_map: dict[str, list[str]],
    current_universe: list[str],
) -> float:
    """Estimate how unique this ticker's behavior is relative to existing universe.

    High score = brings archetypes underrepresented in the universe.
    Low score = highly redundant with existing universe members.
    """
    if not archetypes or not current_universe:
        return 0.5

    # For each archetype, how many other universe tickers share it?
    n_universe = len(current_universe)
    uniqueness_scores = []
    for archetype in archetypes:
        sharing_count = sum(
            1 for t in current_universe
            if archetype in ticker_archetype_map.get(t, [])
        )
        # Fewer sharers → higher uniqueness
        sharing_fraction = sharing_count / n_universe
        uniqueness_scores.append(max(0.0, 1.0 - sharing_fraction * 2))

    return round(sum(uniqueness_scores) / len(uniqueness_scores), 4) if uniqueness_scores else 0.5


# ─── Classification ───────────────────────────────────────────────────────────

def classify_ticker(
    ticker: str,
    ticker_archetype_map: dict[str, list[str]],
    taxonomy_cfg: dict,
    current_universe: list[str] | None = None,
) -> TickerClassification:
    """Classify a single ticker by economic behavior archetypes."""
    upper = ticker.upper()
    archetypes = ticker_archetype_map.get(upper, [])
    chars = _derive_characteristics(archetypes)
    universe = current_universe or []

    div_contrib = _compute_diversification_contribution(
        upper, archetypes, ticker_archetype_map, universe
    )

    return TickerClassification(
        ticker=upper,
        archetype_memberships=sorted(archetypes),
        cyclicality_score=chars["cyclicality"],
        defensiveness_score=chars["defensiveness"],
        recession_sensitivity=chars["recession_sensitivity"],
        policy_sensitivity=chars["policy_sensitivity"],
        leverage_sensitivity=chars["leverage_sensitivity"],
        capital_intensity=chars["capital_intensity"],
        diversification_contribution=div_contrib,
        in_current_universe=upper in [t.upper() for t in universe],
        characteristics=chars,
    )


def classify_universe(
    tickers: list[str],
    taxonomy_path: Path | None = None,
    universe_path: Path | None = None,
) -> dict[str, TickerClassification]:
    """Classify all tickers. Returns {ticker: TickerClassification}."""
    taxonomy_cfg = load_taxonomy(taxonomy_path)
    archetype_map = build_ticker_archetype_map(taxonomy_cfg)
    current_universe = load_current_universe(universe_path)

    return {
        t.upper(): classify_ticker(t, archetype_map, taxonomy_cfg, current_universe)
        for t in tickers
    }
