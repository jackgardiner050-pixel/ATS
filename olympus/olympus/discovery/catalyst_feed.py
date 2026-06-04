"""Catalyst / IPO-beneficiary feed (v2) — AWARENESS ONLY. RESEARCH-GRADE / OBSERVATIONAL.

Tracks upcoming catalysts (IPOs, government funding, launches) and surfaces the publicly-tradeable
BENEFICIARIES — companies/funds that publicly hold a stake in, supply, or partner with the catalyst
(e.g. an Anthropic IPO → public holders AMZN/GOOGL; SpaceX → its listed stakeholders). It NEVER
surfaces the catalyst's private company itself: you can't 'buy the IPO', so a private company is
emitted only as the `catalyst` label on its public beneficiaries, never as a tradeable ticker.
"""
from __future__ import annotations

import logging
from datetime import date

from olympus.discovery.hephaestus import load_themes
from olympus.models.records import GrowthCandidate

_log = logging.getLogger("olympus.catalyst")


class CatalystFeedError(RuntimeError):
    """Malformed catalyst data — fail loud rather than surface a private company as buyable."""


def _private_names(data: dict) -> set[str]:
    names = set()
    for c in data.get("global_catalysts", []) or []:
        if c.get("private_company"):
            names.add(str(c["private_company"]).upper())
    for spec in (data.get("themes") or {}).values():
        for c in spec.get("catalysts", []) or []:
            if c.get("private_company"):
                names.add(str(c["private_company"]).upper())
    return names


def beneficiaries() -> list[GrowthCandidate]:
    """Public beneficiaries of every tracked catalyst — attention-tagged GrowthCandidates.

    A beneficiary inherits its value-chain role if Hephaestus knows it (so a beneficiary that is
    also a real theme leader/bottleneck can flow into the arms), else it is flagged role='leader'
    + status='attention' (awareness only). The catalyst's PRIVATE company is never a ticker.
    """
    data = load_themes()
    today = date.today().isoformat()
    private = _private_names(data)

    # build a quick (ticker→(theme,role,enabler,stage)) index from the value chain
    role_idx: dict[str, GrowthCandidate] = {}
    for theme, spec in (data.get("themes") or {}).items():
        stage = spec.get("stage", "mid")
        for t in spec.get("leaders", []) or []:
            role_idx.setdefault(str(t).upper(), GrowthCandidate(str(t).upper(), theme, "leader", "", stage, "hephaestus"))
        for b in spec.get("bottlenecks", []) or []:
            if isinstance(b, dict) and b.get("ticker"):
                role_idx.setdefault(str(b["ticker"]).upper(),
                                    GrowthCandidate(str(b["ticker"]).upper(), theme, "bottleneck",
                                                    str(b.get("enabler", "")), stage, "hephaestus"))

    def gather(catalysts, default_theme):
        for c in catalysts or []:
            name = c.get("name")
            if not name:
                raise CatalystFeedError(f"catalyst with no name in {default_theme!r}")
            for ticker in c.get("public_beneficiaries", []) or []:
                tk = str(ticker).upper()
                if tk in private:                       # never surface the private company as a ticker
                    raise CatalystFeedError(f"private company {tk} listed as a beneficiary ticker — refused")
                known = role_idx.get(tk)
                yield GrowthCandidate(
                    ticker=tk, theme=(known.theme if known else default_theme),
                    role=(known.role if known else "leader"),
                    enabler=(known.enabler if known else ""),
                    stage=(known.stage if known else "mid"),
                    source=f"catalyst:{name}", obviousness="unknown",
                    catalyst=name, discovery_date=today, status="attention")

    out: list[GrowthCandidate] = []
    out += list(gather(data.get("global_catalysts"), "cross_theme"))
    for theme, spec in (data.get("themes") or {}).items():
        out += list(gather(spec.get("catalysts"), theme))
    _log.info("catalyst feed surfaced %d public beneficiary tag(s); %d private co(s) withheld",
              len(out), len(private))
    return out


def upcoming() -> list[dict]:
    """Human-readable catalyst list (incl. the private company NAME for context) — awareness only."""
    data = load_themes()
    rows = []
    for c in data.get("global_catalysts", []) or []:
        rows.append({"catalyst": c.get("name"), "type": c.get("type"),
                     "private_company": c.get("private_company"),
                     "public_beneficiaries": c.get("public_beneficiaries", []),
                     "note": c.get("note", "")})
    for theme, spec in (data.get("themes") or {}).items():
        for c in spec.get("catalysts", []) or []:
            rows.append({"catalyst": c.get("name"), "type": c.get("type"), "theme": theme,
                         "private_company": c.get("private_company"),
                         "public_beneficiaries": c.get("public_beneficiaries", []),
                         "note": c.get("note", "")})
    return rows
