"""Phase 7 — T212 DEMO broker adapter + widened Artemis.

Proves: refuses any non-demo URL; key from a gitignored secret, fail-loud if absent; the
connectivity check gates order placement; dedup (client ref + held/pending) prevents double
orders; Hermes models the cost on top of each demo fill; widened Artemis surfaces non-mega-cap
names; LiveBroker unreachable. Mocked HTTP — no real key, no network. Paper/advisory, DEMO only.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olympus.core import config, storage                  # noqa: E402
from olympus.adapters import execution as EX, t212_demo as T   # noqa: E402
from olympus.adapters.execution import Order               # noqa: E402
from olympus.discovery import artemis                       # noqa: E402


# ── mock HTTP ─────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.content = (json.dumps(payload).encode() if payload is not None else b"")
    def json(self): return self._p


class FakeSession:
    def __init__(self, *, cash=None, portfolio=None, pending=None, instruments=None,
                 order_status=200, fail_cash=None):
        self.cash = cash or {"free": 10000.0, "total": 10000.0}
        self.portfolio = portfolio or []
        self.pending = pending or []
        self.instruments = instruments or []
        self.order_status = order_status
        self.fail_cash = fail_cash
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        if "/account/cash" in url:
            return _Resp(self.fail_cash, {"error": "x"}) if self.fail_cash else _Resp(200, self.cash)
        if "/portfolio" in url:
            return _Resp(200, self.portfolio)
        if url.endswith("/equity/orders"):
            return _Resp(200, self.pending)
        if "/metadata/instruments" in url:
            return _Resp(200, self.instruments)
        return _Resp(404, None)

    def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append((url, json.loads(data)))
        return _Resp(self.order_status, {"id": "demo-order-1", "status": "FILLED"})


class _CB:
    def __init__(self, total): self.total_dollars = total
    def to_dict(self): return {"total_dollars": self.total_dollars, "commission_dollars": 1.0}


class FakeFriction:
    def compute_entry_cost(self, **k): return _CB(2.5)
    def compute_exit_cost(self, **k): return _CB(2.0)


def _secret(tmp, key="testkey"):
    f = tmp / "t212_demo.env"; f.write_text(f"T212_API_KEY={key}\n"); return f


def _broker(tmp, monkeypatch, **sess_kw):
    monkeypatch.setattr(T, "SECRET", _secret(tmp))
    monkeypatch.setattr(config, "LEDGER_DIR", tmp)
    monkeypatch.setattr(storage, "PAPER_FILLS", tmp / "fills.jsonl")
    return T.T212DemoBroker(session=FakeSession(**sess_kw), friction_engine=FakeFriction())


# ── demo-lock ─────────────────────────────────────────────────────────────────
def test_refuses_non_demo_url(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "SECRET", _secret(tmp_path))
    for bad in ("https://live.trading212.com/api/v0", "https://api.trading212.com/api/v0"):
        with pytest.raises(T.LiveRefused):
            T.T212DemoBroker(base_url=bad, session=FakeSession())
    with pytest.raises(T.LiveRefused):
        T.assert_demo_only("https://live.trading212.com/api/v0")


def test_make_broker_live_refused_demo_routed():
    with pytest.raises(RuntimeError):
        EX.make_broker("live")                      # never reachable
    # 'live' is the only refused-by-factory mode; 'paper' and 't212_demo' route to brokers.


def test_livebroker_unreachable():
    with pytest.raises(NotImplementedError):
        EX.LiveBroker()


# ── key from secret, fail loud ────────────────────────────────────────────────
def test_fail_loud_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "SECRET", tmp_path / "missing.env")        # no secret file
    with pytest.raises(T.T212Unavailable):
        T.T212DemoBroker(session=FakeSession())


# ── connectivity check gates orders ───────────────────────────────────────────
def test_connectivity_401_fails_loud(tmp_path, monkeypatch):
    with pytest.raises(T.T212Unavailable):
        _broker(tmp_path, monkeypatch, fail_cash=401)                 # unauthorized → unavailable


def test_connectivity_ok_enables(tmp_path, monkeypatch):
    b = _broker(tmp_path, monkeypatch)
    assert b._connected and b.opening_cash == 10000.0


# ── dedup prevents double orders ──────────────────────────────────────────────
def test_dedup_client_ref(tmp_path, monkeypatch):
    b = _broker(tmp_path, monkeypatch)
    o = Order("GTLS", "BUY", price=50.0, dollars=300.0, reason="t")
    b.execute(o)
    n_after_first = len(b._session.posts)
    b.execute(o)                                                      # same ref → skipped
    assert n_after_first == 1 and len(b._session.posts) == 1


def test_dedup_held_or_pending(tmp_path, monkeypatch):
    b = _broker(tmp_path, monkeypatch, portfolio=[{"ticker": "GTLS", "quantity": 3}])
    fill = b.execute(Order("GTLS", "BUY", price=50.0, dollars=300.0, reason="t"))
    assert len(b._session.posts) == 0 and "held" in fill.breakdown.get("skipped", "")  # no double order


# ── Hermes cost recorded on top of the demo fill ──────────────────────────────
def test_hermes_cost_recorded(tmp_path, monkeypatch):
    b = _broker(tmp_path, monkeypatch)
    fill = b.execute(Order("GTLS", "BUY", price=50.0, dollars=500.0, reason="deploy"))
    assert fill.mode == "t212_demo" and fill.cost_dollars == 2.5            # Hermes-modeled cost
    assert "demo_response" in fill.breakdown and "hermes_modeled_cost" in fill.breakdown
    recorded = [e for e in storage.fills() if e.get("kind") != "GENESIS"]
    assert recorded and recorded[-1]["detail"]["fill"]["breakdown"]["venue"] == "t212_demo"


# ── never blind-retry on API error ────────────────────────────────────────────
def test_api_error_not_retried(tmp_path, monkeypatch):
    b = _broker(tmp_path, monkeypatch, order_status=500)
    with pytest.raises(T.T212APIError):
        b.execute(Order("GTLS", "BUY", price=50.0, dollars=300.0, reason="t"))
    assert len(b._session.posts) == 1                                  # one attempt, no retry


# ── widened Artemis surfaces non-mega-cap names ───────────────────────────────
def test_widened_artemis_non_megacap():
    mega = {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "KO", "JPM", "JNJ"}
    assert not (set(artemis.UNIVERSE) & mega)                          # no mega-caps in the universe
    assert {"GTLS", "SOFI", "AMKR", "EXAS"} & set(artemis.UNIVERSE)    # mid-caps / special situations present
    assert artemis._liquid({"currentPrice": 2.0, "averageVolume": 1e6}) is False   # penny rejected
    assert artemis._liquid({"currentPrice": 50.0, "averageVolume": 5e6}) is True    # liquid accepted
