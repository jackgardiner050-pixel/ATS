"""Path B: peer cohort resolution + multiples."""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_PEER_CACHE: dict[str, Optional[dict]] = {}


@dataclass
class PeerMultiples:
    median_ev_ebitda: float
    p75_ev_ebitda: float
    median_pe: float
    n_peers_resolved: int = 0
    peer_tickers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def fetch_peer_market_data(ticker: str) -> Optional[dict]:
    t = ticker.upper()
    if t in _PEER_CACHE:
        return _PEER_CACHE[t]
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        market_cap = info.get("marketCap")
        if not market_cap or market_cap <= 0:
            _PEER_CACHE[t] = None
            return None
        total_debt = info.get("totalDebt") or 0
        total_cash = info.get("totalCash") or 0
        ebitda = info.get("ebitda") or 0
        forward_pe = info.get("forwardPE")
        trailing_pe = info.get("trailingPE")
        ev = market_cap + total_debt - total_cash
        ev_ebitda = (ev / ebitda) if ebitda and ebitda > 0 else None
        pe = None
        for c in (forward_pe, trailing_pe):
            if c is not None and 0 < c < 200:
                pe = float(c); break
        data = {"ticker": t, "market_cap": market_cap, "ev": ev,
                "ebitda": ebitda, "ev_ebitda": ev_ebitda, "pe": pe}
        _PEER_CACHE[t] = data
        return data
    except Exception:
        _PEER_CACHE[t] = None
        return None


def compute_peer_multiples(peer_tickers: list[str]) -> PeerMultiples:
    notes, ev_ebitdas, pes, resolved = [], [], [], []
    for t in peer_tickers:
        data = fetch_peer_market_data(t)
        if data is None:
            notes.append(f"{t}: data unavailable")
            continue
        resolved.append(t)
        if data["ev_ebitda"] is not None and 0 < data["ev_ebitda"] < 100:
            ev_ebitdas.append(data["ev_ebitda"])
        if data["pe"] is not None and 0 < data["pe"] < 200:
            pes.append(data["pe"])
    if ev_ebitdas:
        ev_ebitdas.sort()
        median_ev_ebitda = statistics.median(ev_ebitdas)
        idx = int(0.75 * (len(ev_ebitdas) - 1))
        p75_ev_ebitda = ev_ebitdas[idx]
    else:
        notes.append("no_ev_ebitda_peers — default 18x")
        median_ev_ebitda, p75_ev_ebitda = 18.0, 22.0
    if pes:
        median_pe = statistics.median(pes)
    else:
        notes.append("no_pe_peers — default 25x")
        median_pe = 25.0
    return PeerMultiples(median_ev_ebitda, p75_ev_ebitda, median_pe,
                         len(resolved), resolved, notes)


def get_peer_multiples_for_ticker(ticker, peer_config_path=None, defaults=None):
    defaults = defaults or {"median_ev_ebitda": 18.0, "p75_ev_ebitda": 22.0, "median_pe": 25.0}
    if peer_config_path is None:
        peer_config_path = Path(__file__).parent.parent.parent / "config" / "peer_groups.yaml"
    if not peer_config_path.exists():
        return PeerMultiples(defaults["median_ev_ebitda"], defaults["p75_ev_ebitda"],
                             defaults["median_pe"], notes=["peer_config_not_found"])
    with open(peer_config_path) as f:
        cfg = yaml.safe_load(f) or {}
    peer_groups = cfg.get("peer_groups", {})
    peers = []
    for key, vals in peer_groups.items():
        if str(key).upper() == ticker.upper():
            peers = list(vals); break
    if not peers:
        return PeerMultiples(defaults["median_ev_ebitda"], defaults["p75_ev_ebitda"],
                             defaults["median_pe"], notes=[f"no_peer_group_for_{ticker.upper()}"])
    return compute_peer_multiples(peers)
