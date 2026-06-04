"""T212 DEMO broker adapter (Phase 7) — behind the same execution interface. DEMO ONLY.

Hard-locked to demo.trading212.com/api/v0: the demo guard runs at construction AND before every
order; the live host is never reachable from here (and make_broker('live') is refused). The API
key is read from a gitignored secret (~/labs/.secrets/t212_demo.env), never printed or committed.

FAIL LOUD: if the key is missing, or the connectivity check (account + positions) fails, this
raises T212Unavailable — it does NOT silently fall back to the internal sim. The demo account
fills frictionlessly, so the realistic cost is modelled on top via Hermes and recorded alongside
each demo fill, keeping the scorecard honest.

Idempotency: the T212 order API is beta and NOT idempotent. Before any buy we check positions +
pending orders AND an in-run client-order-ref set, and never double-fire. API errors fail loud —
never blind-retried. Pattern adapted from the proven caerus_engine T212 demo client.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date
from urllib.parse import urlparse

from olympus.core import config, storage

DEMO_HOST = "demo.trading212.com"
LIVE_HOST = "live.trading212.com"
DEMO_BASE = "https://demo.trading212.com/api/v0"
SECRET = config.LABS_ROOT / ".secrets" / "t212_demo.env"
_TIMEOUT = 20
MODE = "t212_demo"


class T212Unavailable(RuntimeError):
    """Key missing / unauthorized / connectivity failed → fail loud, never fall back to the sim."""


class LiveRefused(RuntimeError):
    """Anything but the demo host (or an explicit live override) → refused."""


class T212APIError(RuntimeError):
    """A demo API error — surfaced loudly, never blind-retried (the API is not idempotent)."""


def assert_demo_only(base_url: str) -> None:
    if os.environ.get("OLYMPUS_ALLOW_LIVE"):
        raise LiveRefused("OLYMPUS_ALLOW_LIVE is set — refused. Olympus trades the Trading 212 DEMO only.")
    host = urlparse(base_url).hostname or ""
    if LIVE_HOST in base_url or host != DEMO_HOST:
        raise LiveRefused(f"non-demo host {host!r} in base URL {base_url!r} — refused. Demo-only.")


def _load_secret() -> tuple[str, str]:
    if not SECRET.exists():
        raise T212Unavailable(f"T212 demo execution unavailable — secret {SECRET} missing. "
                              "Put T212_API_KEY (gitignored) there to enable demo execution.")
    key = sec = ""
    for raw in SECRET.read_text().splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if line.startswith("T212_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("T212_API_SECRET="):
            sec = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise T212Unavailable("T212 demo execution unavailable — no T212_API_KEY in the secret file.")
    return key, sec


class T212DemoBroker:
    mode = MODE

    def __init__(self, base_url: str = DEMO_BASE, *, session=None, friction_engine=None):
        assert_demo_only(base_url)                      # ── construction guard: refuse non-demo ──
        self.base = base_url.rstrip("/")
        self._key, self._secret = _load_secret()        # fail loud if absent (never printed)
        self._session = session                         # injectable for tests
        self._intent = config.LEDGER_DIR / "t212_intent_log.jsonl"
        self._placed_refs: set[str] = set()             # in-run dedup by client order ref
        self._instruments = None
        from olympus.adapters.execution import friction_engine as _fe
        self._friction = friction_engine or _fe()       # Hermes cost model on top of the demo fill
        self.opening_cash = None
        self._connected = False
        self._connect()                                 # connectivity check GATES order placement

    # ── auth (never logged) ──────────────────────────────────────────────────
    def _headers(self) -> dict:
        if self._secret:
            tok = base64.b64encode(f"{self._key}:{self._secret}".encode()).decode()
            auth = f"Basic {tok}"
        else:
            auth = self._key
        return {"Authorization": auth, "Content-Type": "application/json"}

    def _sess(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _log_intent(self, rec: dict) -> None:
        self._intent.parent.mkdir(parents=True, exist_ok=True)
        with self._intent.open("a") as f:
            f.write(json.dumps({**rec, "date": date.today().isoformat(), "venue": MODE}) + "\n")

    def _get(self, path: str):
        assert_demo_only(self.base)
        r = self._sess().get(self.base + path, headers=self._headers(), timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (401, 403):
            raise T212Unavailable(
                f"T212 demo execution unavailable — auth {r.status_code} on {path}. The configured "
                "key is invalid/forbidden for the equity demo API (need a valid Invest-API demo key). "
                "Not falling back to the sim.")
        raise T212APIError(f"GET {path} → HTTP {r.status_code}")

    def _post(self, path: str, body: dict, *, kind: str):
        assert_demo_only(self.base)                     # ── per-order guard ──
        self._log_intent({"stage": "intended", "kind": kind, "path": path, "body": body})
        try:
            r = self._sess().post(self.base + path, headers=self._headers(),
                                  data=json.dumps(body), timeout=_TIMEOUT)
        except Exception as exc:                        # NEVER blind-retry (API not idempotent)
            self._log_intent({"stage": "error_no_retry", "kind": kind, "error": str(exc)[:120]})
            raise T212APIError(f"POST {path} failed — NOT retried; reconcile via a state read") from exc
        if r.status_code not in (200, 201):
            self._log_intent({"stage": "rejected", "kind": kind, "status": r.status_code})
            raise T212APIError(f"POST {path} → HTTP {r.status_code} — not retried")
        resp = r.json() if r.content else {}
        self._log_intent({"stage": "placed", "kind": kind, "response": resp})
        return resp

    # ── reads ────────────────────────────────────────────────────────────────
    def _connect(self) -> None:
        cash = self._get("/equity/account/cash")        # raises T212Unavailable on 401/403
        port = self._get("/equity/portfolio")
        self.opening_cash = (cash.get("free") if isinstance(cash, dict) else None) or \
            (cash.get("total") if isinstance(cash, dict) else None)
        self._connected = True
        self._log_intent({"stage": "connected", "opening_cash": self.opening_cash,
                          "n_positions": len(port or [])})

    def positions(self) -> list:
        return self._get("/equity/portfolio") or []

    def pending(self) -> list:
        return self._get("/equity/orders") or []

    def instrument_for(self, ticker: str) -> str:
        if self._instruments is None:
            self._instruments = {}
            for inst in (self._get("/equity/metadata/instruments") or []):
                code = inst.get("ticker", "")
                short = (inst.get("shortName") or code.split("_")[0]).upper()
                self._instruments.setdefault(short, code)
        return self._instruments.get(ticker.upper(), ticker)

    def held_or_pending(self, t212_ticker: str) -> bool:
        return any(p.get("ticker") == t212_ticker for p in self.positions()) or \
               any(o.get("ticker") == t212_ticker for o in self.pending())

    def reset_to_cash(self) -> dict:
        """Close any pre-existing demo positions so the account starts clean, and report opening
        cash as the notional. Fails loud if connectivity didn't pass (never fakes a reset)."""
        if not self._connected:
            raise T212Unavailable("T212 demo execution unavailable — cannot reset to cash.")
        closed = []
        for p in self.positions():
            qty = p.get("quantity") or p.get("shares") or 0
            if qty and qty > 0:
                self._post("/equity/orders/market", {"ticker": p["ticker"], "quantity": -abs(float(qty))},
                           kind="reset_close")
                closed.append(p["ticker"])
        self._log_intent({"stage": "reset_to_cash", "closed": closed, "opening_cash": self.opening_cash})
        return {"closed_positions": closed, "opening_cash": self.opening_cash}

    # ── execute (paper/advisory; demo venue) ──────────────────────────────────
    def execute(self, order):
        from olympus.adapters.execution import Fill
        if not self._connected:
            raise T212Unavailable("T212 demo execution unavailable — connectivity check did not pass.")
        today = date.today()
        t212 = self.instrument_for(order.ticker)
        ref = f"{order.ticker}|{order.side}|{today.isoformat()}"          # client order ref (dedup)
        if ref in self._placed_refs:
            self._log_intent({"stage": "skipped_dup_ref", "ref": ref})
            return Fill(order.ticker, order.side, 0.0, order.price, 0.0, 0.0, today.isoformat(),
                        "dedup: client ref already placed", mode=MODE, breakdown={"skipped": "duplicate_ref"})
        if order.side == "BUY" and self.held_or_pending(t212):
            self._log_intent({"stage": "skipped_held_or_pending", "ticker": t212})
            return Fill(order.ticker, order.side, 0.0, order.price, 0.0, 0.0, today.isoformat(),
                        "dedup: already held/pending", mode=MODE, breakdown={"skipped": "held_or_pending"})

        shares = (order.dollars / order.price) if order.side == "BUY" else float(order.shares or 0.0)
        qty = shares if order.side == "BUY" else -abs(shares)
        resp = self._post("/equity/orders/market", {"ticker": t212, "quantity": qty},
                          kind=f"market_{order.side.lower()}")
        self._placed_refs.add(ref)

        # Hermes models the realistic cost on top of the frictionless demo fill (scorecard honesty).
        if order.side == "BUY":
            cb = self._friction.compute_entry_cost(signal_date=today, fill_date=today,
                    signal_close_price=order.price, fill_open_price=order.price,
                    position_dollars=shares * order.price, ticker=order.ticker)
            net = -(shares * order.price + cb.total_dollars)
        else:
            cb = self._friction.compute_exit_cost(fill_date=today, fill_price=order.price,
                    shares=shares, ticker=order.ticker, signal_close_price=order.price)
            net = shares * order.price - cb.total_dollars

        fill = Fill(order.ticker, order.side, round(shares, 6), order.price, round(cb.total_dollars, 4),
                    round(net, 2), today.isoformat(), order.reason, mode=MODE,
                    breakdown={"venue": MODE, "t212_instrument": t212, "demo_response": resp,
                               "hermes_modeled_cost": cb.to_dict()})
        storage.append_fill(fill.to_dict(), ticker=order.ticker)
        return fill
