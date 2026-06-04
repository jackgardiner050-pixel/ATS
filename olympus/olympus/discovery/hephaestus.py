"""Hephaestus (v2) — value-chain cartographer. RESEARCH-GRADE / OBSERVATIONAL.

For each live high-growth theme, Hephaestus maps the value chain and tags every name LEADER (the
obvious primary) vs SECOND-ORDER / BOTTLENECK (the enabler at scale or with new enabling tech —
power, cooling, packaging, fabs, launch, materials, memory, optics, fuel). An obviousness proxy
(analyst-coverage breadth + market-cap size) labels obvious-vs-less-obvious for awareness.

Roles come from the curated `growth_themes.yaml` (authoritative). The obviousness proxy is a free
ENRICHMENT — if its data is unavailable for a name it is left 'unknown' (fail-loud-SKIP that one
name, never abort the map). No price/momentum signal is emitted (firewall): only ticker+role+theme.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Optional

import yaml

from olympus.core import config
from olympus.models.records import GrowthCandidate

_log = logging.getLogger("olympus.hephaestus")

THEMES = config.OLYMPUS_REPO / "olympus" / "config" / "growth_themes.yaml"

# obviousness buckets — large-cap + heavily-covered = OBVIOUS; smaller/thinly-covered = LESS_OBVIOUS
_OBVIOUS_COVERAGE = 25            # >= this many analyst opinions → well-covered
_OBVIOUS_MKTCAP_USD = 200e9      # >= $200B → mega-cap obvious


class ThemeMapError(RuntimeError):
    """The themes file is missing or malformed — fail loud, never silently map nothing."""


def load_themes() -> dict:
    if not THEMES.exists():
        raise ThemeMapError(f"growth themes file missing: {THEMES}")
    data = yaml.safe_load(THEMES.read_text()) or {}
    if not data.get("themes"):
        raise ThemeMapError("growth_themes.yaml has no 'themes' — refusing to map an empty value chain")
    return data


def _obviousness(ticker: str, coverage_fn: Optional[Callable]) -> str:
    """Coverage/size proxy → obvious | less_obvious | unknown. Fail-loud-SKIP to 'unknown'."""
    if coverage_fn is None:
        return "unknown"
    try:
        info = coverage_fn(ticker) or {}
    except Exception as e:                          # one name's data hiccup must not abort the map
        _log.warning("hephaestus: obviousness proxy unavailable for %s — %s", ticker, str(e)[:60])
        return "unknown"
    cov = info.get("numberOfAnalystOpinions") or 0
    cap = info.get("marketCap") or 0
    if cov >= _OBVIOUS_COVERAGE or cap >= _OBVIOUS_MKTCAP_USD:
        return "obvious"
    return "less_obvious"


def _default_coverage(ticker: str) -> dict:
    import yfinance as yf
    return yf.Ticker(ticker).info or {}


def map_value_chain(*, coverage_fn: Optional[Callable] = _default_coverage,
                    enrich: bool = True) -> list[GrowthCandidate]:
    """Flatten every theme into role-tagged GrowthCandidates (leaders + bottlenecks).

    A ticker may appear under more than one theme/role (e.g. a name that is a leader in one chain
    and a bottleneck in another) — each (ticker, theme, role) is its own tagged entry; the arms
    partition on role.
    """
    data = load_themes()
    today = date.today().isoformat()
    cov = _default_coverage if (enrich and coverage_fn is _default_coverage) else (coverage_fn if enrich else None)
    out: list[GrowthCandidate] = []
    for theme, spec in data["themes"].items():
        stage = spec.get("stage", "mid")
        for t in spec.get("leaders", []) or []:
            t = str(t).upper()
            out.append(GrowthCandidate(ticker=t, theme=theme, role="leader", enabler="",
                                       stage=stage, source="hephaestus",
                                       obviousness=_obviousness(t, cov), discovery_date=today))
        for b in spec.get("bottlenecks", []) or []:
            if not isinstance(b, dict) or "ticker" not in b:
                _log.warning("hephaestus: skipping malformed bottleneck in %s: %r", theme, b)
                continue
            t = str(b["ticker"]).upper()
            out.append(GrowthCandidate(ticker=t, theme=theme, role="bottleneck",
                                       enabler=str(b.get("enabler", "")), stage=stage,
                                       source="hephaestus", obviousness=_obviousness(t, cov),
                                       discovery_date=today))
    return out


def role_of(ticker: str, *, theme: str | None = None) -> Optional[str]:
    """Best-known role for a ticker (optionally within a theme). leader > bottleneck if ambiguous."""
    roles = {c.role for c in map_value_chain(enrich=False)
             if c.ticker == ticker.upper() and (theme is None or c.theme == theme)}
    if "leader" in roles:
        return "leader"
    if "bottleneck" in roles:
        return "bottleneck"
    return None
