"""Execution layer — one interface, two implementations.

PaperBroker (BUILD): simulated fills through Hermes v3's REAL friction/cost model, writing paper
positions + fills to the paper ledger. This is what the autonomous loop fires into.

LiveBroker (DO NOT BUILD): a placeholder that raises on construction AND execution. There is no
broker API, no credentials, no real-order path. The loop never imports or constructs it; the
factory refuses mode="live". A real order would require human authorisation + a passed kill-check.

Everything here is tagged paper/simulated.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from olympus.core import config, storage

PAPER_MODE = "paper/simulated"

# ── load the REAL Hermes v3 friction model by file path (avoids the `src` package clash with
#    ~/agent/src). Fail loud if it is missing — no stub, no silent fallback. ──────────────────
_FRICTION_PATH = config.TRADING_ROOT / "hermes_v3_lab" / "src" / "execution" / "friction.py"


def _load_friction():
    if not _FRICTION_PATH.exists():
        raise ImportError(f"Hermes v3 friction model not found at {_FRICTION_PATH} — "
                          f"PaperBroker requires the real cost model, not a stub.")
    spec = importlib.util.spec_from_file_location("hermes_v3_friction", _FRICTION_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # register so @dataclass introspection (cls.__module__) works
    spec.loader.exec_module(mod)
    return mod


_friction = _load_friction()


def friction_engine(tier_name: str = "retail_5k"):
    """A real Hermes v3 FillEngine — shared by PaperBroker and the T212 demo broker (which models
    cost on top of the venue's frictionless demo fill)."""
    return _friction.FillEngine(_friction.load_friction_tier(tier_name), _friction.ADVCache())


@dataclass
class Order:
    ticker: str
    side: str                 # BUY | SELL
    price: float              # fill reference price (paper)
    dollars: Optional[float] = None    # for BUY
    shares: Optional[float] = None     # for SELL
    reason: str = ""


@dataclass
class Fill:
    ticker: str
    side: str
    shares: float
    fill_price: float
    cost_dollars: float
    net_dollars: float        # signed cash impact (− on buy, + on sell, net of cost)
    date: str
    reason: str
    mode: str = PAPER_MODE
    breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class PaperBroker:
    """Simulated execution via the real Hermes v3 FillEngine. No real orders, ever."""
    mode = PAPER_MODE

    def __init__(self, tier_name: str = "retail_5k"):
        self._tier = _friction.load_friction_tier(tier_name)
        self._engine = _friction.FillEngine(self._tier, _friction.ADVCache())

    def execute(self, order: Order) -> Fill:
        today = date.today()
        if order.side == "BUY":
            dollars = float(order.dollars or 0.0)
            cb = self._engine.compute_entry_cost(
                signal_date=today, fill_date=today, signal_close_price=order.price,
                fill_open_price=order.price, position_dollars=dollars, ticker=order.ticker)
            shares = dollars / order.price if order.price > 0 else 0.0
            net = -(dollars + cb.total_dollars)
        elif order.side == "SELL":
            shares = float(order.shares or 0.0)
            cb = self._engine.compute_exit_cost(
                fill_date=today, fill_price=order.price, shares=shares, ticker=order.ticker,
                signal_close_price=order.price)
            net = shares * order.price - cb.total_dollars
        else:
            raise ValueError(f"unknown side {order.side!r}")

        fill = Fill(ticker=order.ticker, side=order.side, shares=round(shares, 6),
                    fill_price=order.price, cost_dollars=round(cb.total_dollars, 4),
                    net_dollars=round(net, 2), date=today.isoformat(), reason=order.reason,
                    breakdown=cb.to_dict())
        storage.append_fill(fill.to_dict(), ticker=order.ticker)   # paper ledger (hash-chained)
        return fill


class LiveBroker:
    """PLACEHOLDER — not built. Real orders require human authorisation + a passed kill-check."""
    mode = "live"
    _MSG = "real orders require human authorisation + a passed kill-check"

    def __init__(self, *a, **k):
        raise NotImplementedError(self._MSG)

    def execute(self, order):   # pragma: no cover — unreachable
        raise NotImplementedError(self._MSG)


def make_broker(mode: str = "paper"):
    """Factory the loop uses. Returns the internal PaperBroker or the T212 DEMO broker. The live
    path is NEVER reachable here — make_broker('live') is refused before any construction."""
    if mode == "paper":
        return PaperBroker()
    if mode == "t212_demo":
        from olympus.adapters.t212_demo import T212DemoBroker   # lazy (avoids import cycle)
        return T212DemoBroker()                                  # connectivity-checks; fails loud if no key
    raise RuntimeError(f"refusing to build a non-paper/non-demo broker (mode={mode!r}): {LiveBroker._MSG}")
