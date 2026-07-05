"""Abstract Sleeve interface + OrderIntentDraft.

A Sleeve turns screen data into DRAFT order intents (never live orders — draft only,
human/pipeline gated downstream). Every draft carries the sleeve's cohort tag
{sleeve_id}_c{n}, validated by the generalized sleeve cohort rule.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.sleeves.cohort import cohort_tag, validate_cohort


@dataclass
class OrderIntentDraft:
    """A drafted order intent — NOT a live order. Carries the sleeve cohort tag."""
    sleeve_id: str
    cohort: str
    ticker: str
    side: str                       # LONG | SHORT
    thesis: str = ""
    conviction: str | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        validate_cohort(self.cohort)
        if self.side not in ("LONG", "SHORT"):
            raise ValueError(f"side must be LONG or SHORT, got {self.side!r}")


class Sleeve(ABC):
    """Base class for a hypothesis-registered strategy sleeve."""

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.sleeve_id = manifest["sleeve_id"]
        self.cohort_n = 1           # advances at each re-registered window (c1, c2, ...)

    def cohort_tag(self, n: int | None = None) -> str:
        return cohort_tag(self.sleeve_id, self.cohort_n if n is None else n)

    def draft(self, ticker: str, side: str, *, thesis: str = "", conviction=None,
              n: int | None = None, **meta) -> OrderIntentDraft:
        """Helper that stamps the correct cohort tag onto a draft."""
        return OrderIntentDraft(sleeve_id=self.sleeve_id, cohort=self.cohort_tag(n),
                                ticker=ticker, side=side, thesis=thesis,
                                conviction=conviction, meta=meta)

    @abstractmethod
    def generate_signals(self, screen_data) -> list[OrderIntentDraft]:
        """Turn screen data into a list of OrderIntentDraft. Implementations MUST tag
        every draft with self.cohort_tag() (use self.draft())."""
        raise NotImplementedError
