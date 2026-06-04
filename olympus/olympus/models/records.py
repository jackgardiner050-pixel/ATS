"""Olympus §11 record types (dataclasses).

Thesis + ForwardOutcome are NOT redefined here — they are owned by the existing Oracle
(`oracle.schema.Rating` + its forward-test ledger). These are the orchestration records that
glue the members together and feed the real decision/override ledgers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Candidate:
    candidate_id: str
    ticker: str
    name: str
    asset_type: str            # single_name | etf | ...
    theme: str
    source: str                # e.g. "oracle:forward_test"
    discovery_date: str
    status: str                # research | watchlist | actionable | decided

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NakedCandidate:
    """A discovery output, deliberately NAKED: ticker + which source surfaced it + date + status.

    NO score, signal, rank or momentum number is carried — the firewall (§B) requires the
    discovery source's signal never reach a decision member. Oracle reasons from scratch.
    """
    ticker: str
    source: str                # momentum | value_quality | context | watchlist (+merged)
    discovery_date: str
    status: str = "discovered"  # discovered | promoted | rejected

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Critique:
    critique_id: str
    thesis_ref: str
    counter_case: str
    hidden_assumptions: List[str]
    evidence_gaps: List[str]
    failure_scenarios: List[str]
    thesis_break_conditions: List[str]
    reduce_confidence: bool
    source: str = "athena_nemesis"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExposureReport:
    exposure_id: str
    candidate_id: str
    candidate_ticker: str
    satellite_theme_weights: dict
    satellite_overlap_warnings: List[str]
    core_overlap_warnings: List[str]
    theme_exposure_status: str          # ok | elevated | breach
    factor_weights: dict
    etf_alternative: dict
    core_supplied: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AllocationProposal:
    allocation_id: str
    candidate_id: str
    band: str
    target_allocation: float
    initial_allocation: float
    max_allocation: float
    cash_impact: float
    limit_breaches: List[str]
    survivability_score: Optional[float]
    override_required: bool
    override_instruction: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ZeusDecision:
    decision_id: str
    candidate_id: str
    thesis_ref: str
    date: str
    decision: str                       # BUY | HOLD | REDUCE | EXIT
    confidence_band: str
    evidence_grade: str
    confidence_constrained_by: List[str]
    thesis_summary: str
    strongest_counter_case: str
    key_risks: List[str]
    current_allocation: float
    target_allocation: float
    max_allocation: float
    benchmark_alternative: dict
    core_overlap_warning: str
    satellite_overlap_warning: str
    factor_exposure: dict
    thesis_break_conditions: List[str]
    review_date: str
    evidence_independence: str          # the correlated-council assessment
    hermes_pathway: str
    human_authorisation_required: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HumanOverride:
    override_id: str
    decision_id: str
    zeus_decision: str
    human_action: str
    rationale: str
    date: str
    outcome_tracking: str = "open"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ForwardOutcome:
    outcome_id: str
    decision_id: str
    measurement_date: str
    asset_return: Optional[float]
    benchmark_return: Optional[float]        # global index (ACWI) over the same window
    etf_alternative_return: Optional[float]  # naive obvious-AI name (NVDA) over the same window
    relative_return: Optional[float]         # asset − benchmark
    skill_luck_beta_classification: str      # skill | luck | beta | factor | unresolved
    conviction: Optional[int] = None         # stated conviction at decision time (for calibration)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
