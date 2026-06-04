"""Artemis — multi-source candidate discovery (Phase 5). RESEARCH-GRADE / EXPERIMENTAL.

Surfaces candidate tickers from several DELIBERATELY DIFFERENT styles so Olympus isn't a
one-note AI-finder, and emits each as a NAKED candidate — ticker + which source surfaced it +
date, nothing else. No score / signal / rank travels downstream (the firewall, §B): the momentum
screener's raw scored picks stay logged separately and UNCHANGED as the benchmark control; here
only its tickers are taken.

Sources: momentum (benchmark/screener) · value/quality (free fundamentals, fail-loud) ·
context/market-intelligence (free breadth/positioning proxy, Level-0 attention-only, fail-loud) ·
user watchlist (manual). Dedup across sources, cap per run. Fail loud if a data source errors —
never fake.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Optional

import yaml

from olympus.core import config
from olympus.models.records import NakedCandidate

_log = logging.getLogger("olympus.artemis")

WATCHLIST = config.OLYMPUS_REPO / "olympus" / "config" / "artemis_watchlist.yaml"

# decision-independent universe — broadened toward LESS-COVERED mid-caps and special situations
# where a non-consensus view could plausibly exist (not the most-covered mega-caps). Strictly
# within liquidity discipline (the _liquid filter below enforces price/ADV floors at runtime).
UNIVERSE = [
    # industrials / infrastructure / special situations
    "GTLS", "AGX", "BLDR", "FIX", "AAON", "MTZ", "STRL", "PWR", "BWXT",
    # energy / materials
    "AR", "RRC", "CNX", "MP", "CMC", "AA",
    # financials
    "SOFI", "ALLY", "KEY", "JXN",
    # healthcare / biotech (liquid)
    "EXAS", "HALO", "JAZZ", "INCY", "ALKS",
    # tech / semis-adjacent mid-caps
    "AMKR", "COHR", "ONTO", "FORM", "PLAB", "SANM",
    # consumer
    "DECK", "CROX", "BOOT", "PLNT",
]
CAP = 8                # max naked candidates per run (bounds cost + noise)
PRICE_FLOOR = 5.0      # no penny stocks
ADV_FLOOR_USD = 10_000_000   # ≥ $10M average daily $ volume — T212-tradeable, no micro-caps


def _liquid(info: dict):
    """Liquidity discipline: adequate price + ADV. Returns True/False, or None if undecidable."""
    px = info.get("currentPrice") or info.get("regularMarketPrice")
    vol = info.get("averageDailyVolume10Day") or info.get("averageVolume")
    if px is None or vol is None:
        return None
    if px < PRICE_FLOOR or px * vol < ADV_FLOOR_USD:
        return False
    return True


class DiscoveryDataError(RuntimeError):
    """Raised when a discovery data source errors — fail loud, never fake a candidate."""


# ── individual sources (each returns a list of bare tickers) ──────────────────
def _momentum_source(price_fn: Optional[Callable]) -> list[str]:
    from olympus.benchmark import screener     # imported HERE (discovery), never by a decision member
    picks = screener.run_and_record(**({"price_fn": price_fn} if price_fn else {}))
    return [p["ticker"] for p in picks]          # NAKED: tickers only; the scores stay in the screener ledger


def _value_quality_source(universe: list[str], fundamentals_fn: Callable) -> list[str]:
    """Cheap + financially sound names (a counterweight to momentum). Fail loud on data error."""
    out = []
    got_any = False
    for t in universe:
        try:
            info = fundamentals_fn(t)
        except DiscoveryDataError as e:             # fail-loud-SKIP a dead/404 symbol; never abort the run
            _log.warning("value/quality: skipping %s (data error) — %s", t, str(e)[:70])
            continue
        if not info:
            continue
        got_any = True
        if _liquid(info) is False:                  # liquidity discipline — drop penny/micro names
            continue
        fpe, fcf, dte = info.get("forwardPE"), info.get("freeCashflow"), info.get("debtToEquity")
        if isinstance(fpe, (int, float)) and 0 < fpe < 22 and isinstance(fcf, (int, float)) and fcf > 0 \
                and (dte is None or dte < 200):
            out.append(t)
    if not got_any:
        raise DiscoveryDataError("value/quality: no fundamentals available for the universe — failing loud")
    return out


def _context_source(universe: list[str], context_fn: Callable) -> list[str]:
    """Level-0 attention only — free breadth/positioning proxy. (Notable-investor 13F changes are
    NOT freely available, so this uses analyst-coverage breadth + net rating drift as a proxy, and
    surfaces names for ATTENTION only — never a signal.) Fail loud on data error."""
    out, got_any = [], False
    for t in universe:
        try:
            ctx = context_fn(t)
        except DiscoveryDataError as e:           # fail-loud-SKIP a dead/404 symbol; never abort
            _log.warning("context: skipping %s (data error) — %s", t, str(e)[:70])
            continue
        if ctx is None:
            continue
        got_any = True
        if ctx.get("breadth", 0) >= 15 and ctx.get("net_rating_drift", 0) > 0:
            out.append(t)
    if not got_any:
        raise DiscoveryDataError("context: no breadth/positioning data available — failing loud")
    return out


def _watchlist_source() -> list[str]:
    if not WATCHLIST.exists():
        return []
    data = yaml.safe_load(WATCHLIST.read_text()) or {}
    return [str(t).upper() for t in (data.get("tickers") or [])]


# ── default free-data implementations (yfinance) ──────────────────────────────
def _default_fundamentals(t: str) -> dict:
    try:
        import yfinance as yf
        return yf.Ticker(t).info or {}
    except Exception as e:
        raise DiscoveryDataError(f"value/quality fundamentals fetch failed for {t}: {e}") from e


def _default_context(t: str) -> Optional[dict]:
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        rs = yf.Ticker(t).recommendations_summary
        breadth = info.get("numberOfAnalystOpinions") or 0
        drift = 0
        if rs is not None and len(rs) >= 2:
            cur, old = rs.iloc[0], rs.iloc[-1]
            drift = (int(cur["strongBuy"]) + int(cur["buy"])) - (int(old["strongBuy"]) + int(old["buy"]))
        return {"breadth": breadth, "net_rating_drift": drift}
    except Exception as e:
        raise DiscoveryDataError(f"context breadth fetch failed for {t}: {e}") from e


# ── orchestration ─────────────────────────────────────────────────────────────
def discover(*, top_n: int = CAP, universe: list[str] = None,
             price_fn: Callable = None, fundamentals_fn: Callable = _default_fundamentals,
             context_fn: Callable = _default_context) -> list[NakedCandidate]:
    universe = universe or UNIVERSE
    today = date.today().isoformat()
    feeds = {
        "momentum": _momentum_source(price_fn),
        "value_quality": _value_quality_source(universe, fundamentals_fn),
        "context": _context_source(universe, context_fn),
        "watchlist": _watchlist_source(),
    }
    # dedup (first source wins, but record all surfacing sources in the tag); round-robin for diversity
    first_source, merged = {}, {}
    for src, tickers in feeds.items():
        for t in tickers:
            t = t.upper()
            merged.setdefault(t, []).append(src)
            first_source.setdefault(t, src)
    # round-robin across sources so the cap isn't all momentum
    ordered, seen = [], set()
    pools = {s: [t for t in feeds[s] if t.upper() not in seen] for s in feeds}
    while len(ordered) < top_n and any(pools.values()):
        for s in feeds:
            while pools[s]:
                t = pools[s].pop(0).upper()
                if t in seen:
                    continue
                seen.add(t)
                ordered.append(t)
                break
            if len(ordered) >= top_n:
                break
    return [NakedCandidate(ticker=t, source="+".join(merged[t]), discovery_date=today) for t in ordered]
