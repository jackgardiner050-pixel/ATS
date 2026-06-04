"""Growth discovery orchestrator (v2) — combines the discovery brain into one tagged candidate set.

Hephaestus maps the value chain (leaders + bottlenecks); Chronos flags frothy themes; the catalyst
feed surfaces public beneficiaries for AWARENESS (logged, never auto-bought — you can't buy the IPO).
The three arms partition the value-chain candidates by ROLE. Firewall preserved: only ticker + role
+ theme context leaves discovery, never a price/momentum signal.
"""
from __future__ import annotations

from typing import Callable, Optional

from olympus.discovery import hephaestus, chronos, catalyst_feed
from olympus.models.records import GrowthCandidate

CAP_PER_ARM = 8       # bound cost + noise per arm per run (mirrors the pre-registration)


def discover(*, enrich: bool = True,
             coverage_fn: Optional[Callable] = hephaestus._default_coverage) -> list[GrowthCandidate]:
    """The buyable value-chain universe (leaders + bottlenecks), role-tagged. Deduped by
    (ticker, theme, role)."""
    seen, out = set(), []
    for c in hephaestus.map_value_chain(enrich=enrich, coverage_fn=coverage_fn):
        k = (c.ticker, c.theme, c.role)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def awareness() -> list[GrowthCandidate]:
    """Catalyst/IPO public beneficiaries — surfaced for AWARENESS only (logged, never auto-bought)."""
    return catalyst_feed.beneficiaries()


def for_arm(cands: list[GrowthCandidate], allowed_roles, *, cap: int = CAP_PER_ARM,
            skip_frothy: bool = True, extension_fn: Optional[Callable] = None) -> list[GrowthCandidate]:
    """Filter to an arm's allowed roles, drop frothy-top themes (Chronos), dedup by ticker (prefer
    the LEADER role), then cap. When an arm allows BOTH roles (arm B), the cap is split by
    ROUND-ROBIN across roles so B is a genuine leaders+bottlenecks MIX — not just the leaders that
    happen to sort first."""
    allowed = list(dict.fromkeys(allowed_roles))            # preserve order, e.g. [leader, bottleneck]
    pool = [c for c in cands if c.role in allowed]
    if skip_frothy:
        pool = [c for c in pool if not chronos.is_frothy(c.theme, extension_fn=extension_fn)]

    # dedup by ticker: prefer a 'leader' tag over 'bottleneck' so a name isn't bought twice
    best: dict[str, GrowthCandidate] = {}
    for c in pool:
        cur = best.get(c.ticker)
        if cur is None or (cur.role == "bottleneck" and c.role == "leader"):
            best[c.ticker] = c

    by_role = {r: sorted([c for c in best.values() if c.role == r], key=lambda c: (c.theme, c.ticker))
               for r in allowed}
    out, i = [], 0
    while len(out) < cap and any(by_role[r] for r in allowed):
        r = allowed[i % len(allowed)]
        if by_role[r]:
            out.append(by_role[r].pop(0))
        i += 1
    return out
