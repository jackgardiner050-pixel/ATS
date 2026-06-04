"""Chronos (v2) — theme lifecycle clock. RESEARCH-GRADE / OBSERVATIONAL.

Tags each theme's stage — early_accelerating | mid | late_frothy — so the arms can avoid buying a
FROTHY TOP. Stage is read from the curated themes file (authoritative human read); an optional free
price-extension proxy (how far above its 200-day average a representative name trades) can CONFIRM
froth, never silently override the human stage to LESS frothy.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from olympus.discovery.hephaestus import load_themes

_log = logging.getLogger("olympus.chronos")

STAGES = ("early_accelerating", "mid", "late_frothy")
_FROTH_EXTENSION_PCT = 60.0       # >60% above the 200d average = stretched → can escalate to frothy


def stage_for(theme: str) -> str:
    spec = (load_themes().get("themes") or {}).get(theme)
    if spec is None:
        return "mid"
    s = spec.get("stage", "mid")
    return s if s in STAGES else "mid"


def is_frothy(theme: str, *, extension_fn: Optional[Callable] = None) -> bool:
    """Frothy if the curated stage says late_frothy, OR (optionally) the price-extension proxy is
    stretched. The proxy can only ESCALATE to frothy — it never downgrades the human read."""
    if stage_for(theme) == "late_frothy":
        return True
    if extension_fn is not None:
        try:
            ext = extension_fn(theme)
            if isinstance(ext, (int, float)) and ext >= _FROTH_EXTENSION_PCT:
                _log.info("chronos: %s escalated to frothy by price-extension proxy (+%.0f%%)", theme, ext)
                return True
        except Exception as e:
            _log.warning("chronos: extension proxy unavailable for %s — %s", theme, str(e)[:60])
    return False


def froth_penalty(theme: str, **kw) -> float:
    """A multiplicative conviction haircut for buying into a late/frothy theme (1.0 = no haircut)."""
    return 0.7 if is_frothy(theme, **kw) else 1.0
