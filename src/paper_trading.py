"""Paper trading layer — simulated positions for model calibration.

Hard rules (identical to screener):
  no_real_orders       : True — this module NEVER interacts with a broker
  no_live_pnl_learning : True — returns are logged for future analysis only,
                                 never fed back to the rating model
  human_gated          : True — paper_run.py must be invoked explicitly

Storage:
  data/paper_positions.yaml  — open positions (one entry per held ticker)
  data/paper_trades.jsonl    — immutable append-only log of closed trades
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from src.io_utils import append_jsonl, atomic_write_text

logger = logging.getLogger(__name__)

POSITIONS_PATH = Path(__file__).parent.parent / "data" / "paper_positions.yaml"
TRADES_PATH    = Path(__file__).parent.parent / "data" / "paper_trades.jsonl"

_CONSTRAINTS = {"no_real_orders": True, "no_live_pnl_learning": True}

# Cohort tags. Kept as an open string list (not a closed Enum) so cohort_2, ...
# can be appended without a code migration. Validation rejects anything not here.
VALID_COHORTS = ("legacy_pre_fix", "cohort_1")

# Positions opened under the current (post-fix, locked) ruleset belong to cohort_1.
NEW_POSITION_COHORT = "cohort_1"


# ─── Entry / exit gates ───────────────────────────────────────────────────────

def should_enter(rating: str, confidence: str) -> bool:
    """Enter long only on STRONG_BUY with MED or HIGH confidence.

    STRONG_BUY + LOW is deliberately excluded: low-confidence calls carry
    too much model uncertainty to risk even simulated capital.
    """
    return rating == "STRONG_BUY" and confidence in ("MED", "HIGH")


def should_exit(rating: str) -> bool:
    """Exit when conviction falls below BUY.

    STRONG_BUY and BUY → hold.
    HOLD, SELL, STRONG_SELL, BROKEN, ERROR, unknown → close.
    """
    return rating not in ("STRONG_BUY", "BUY")


# ─── Position lifecycle ───────────────────────────────────────────────────────

def open_position(
    ticker: str,
    entry_date: str,
    entry_price: float,
    entry_rating: str,
    entry_confidence: str,
    price_target: float,
    spy_entry_price: float,
    cohort: str = NEW_POSITION_COHORT,
) -> dict:
    """Build an open position record. Pure — no I/O.

    New positions are tagged cohort_1 by default (opened under the locked
    ruleset); the pre-fix legacy book is tagged separately by the migration.
    """
    return {
        "ticker": ticker,
        "cohort": cohort,
        "direction": "LONG",
        "entry_date": entry_date,
        "entry_price": float(entry_price),
        "entry_rating": entry_rating,
        "entry_confidence": entry_confidence,
        "price_target": float(price_target),
        "spy_entry_price": float(spy_entry_price),
        "constraints": _CONSTRAINTS,
    }


_COST_BPS_CACHE: Optional[float] = None


def _paper_cost_bps() -> float:
    """Round-trip cost per side, in bps, from config/portfolio.yaml (single source
    of truth, shared with the NAV ledger). Cached; falls back to 20 on any error."""
    global _COST_BPS_CACHE
    if _COST_BPS_CACHE is None:
        try:
            cfg = yaml.safe_load(
                (Path(__file__).parent.parent / "config" / "portfolio.yaml").read_text()
            ) or {}
            _COST_BPS_CACHE = float(cfg.get("paper_cost_bps", 20))
        except Exception:
            _COST_BPS_CACHE = 20.0
    return _COST_BPS_CACHE


def _r6(x):
    return round(x, 6) if x is not None else None


def tr_fields(entry_adj, exit_adj, spy_entry_adj, spy_exit_adj, cost_bps) -> dict:
    """Dividend-adjusted total-return fields from aligned auto_adjust closes. Pure.
    Shared by close_position and paper_run so the math has one home."""
    rt_cost = 2 * cost_bps / 1e4
    rt_tr = float(exit_adj) / float(entry_adj) - 1.0
    spy_tr = float(spy_exit_adj) / float(spy_entry_adj) - 1.0
    return {
        "return_pct_tr": _r6(rt_tr),
        "spy_return_tr": _r6(spy_tr),
        "alpha_tr": _r6(rt_tr - spy_tr),
        "return_pct_tr_net": _r6(rt_tr - rt_cost),
        "alpha_tr_net": _r6(rt_tr - rt_cost - spy_tr),   # PRIMARY: net total-return alpha
        "capture_basis": "adjusted",
    }


def close_position(
    position: dict,
    exit_date: str,
    exit_price: float,
    exit_rating: str,
    spy_exit_price: float,
    cost_bps: Optional[float] = None,
    entry_price_adj: Optional[float] = None,
    exit_price_adj: Optional[float] = None,
    spy_entry_adj: Optional[float] = None,
    spy_exit_adj: Optional[float] = None,
) -> dict:
    """Compute returns + SPY alpha, return a closed trade record. Pure (only a
    cached config read for the default cost).

    Honest accounting — all ADDITIVE; the original gross-spot fields are kept
    unchanged for continuity:
      return_pct / spy_return_pct / alpha  — gross, spot (unchanged)
      return_pct_net / alpha_net           — gross minus 2×cost_bps/1e4 (round trip)
      return_pct_tr / spy_return_tr / alpha_tr        — dividend-adjusted total return
      return_pct_tr_net / alpha_tr_net                — TR minus round-trip cost (PRIMARY)
    cost_bps reuses config/portfolio.yaml paper_cost_bps. TR fields require the four
    aligned *_adj closes (captured together in paper_run); None when unavailable.
    """
    entry_price    = position["entry_price"]
    spy_entry      = position["spy_entry_price"]
    if cost_bps is None:
        cost_bps = _paper_cost_bps()
    rt_cost = 2 * cost_bps / 1e4

    return_pct     = float(exit_price) / entry_price - 1.0
    spy_return_pct = float(spy_exit_price) / spy_entry - 1.0
    alpha          = return_pct - spy_return_pct

    tr = None
    if None not in (entry_price_adj, exit_price_adj, spy_entry_adj, spy_exit_adj):
        tr = tr_fields(entry_price_adj, exit_price_adj, spy_entry_adj, spy_exit_adj, cost_bps)

    record = {
        "ticker":          position["ticker"],
        "cohort":          position.get("cohort"),   # inherit the position's cohort
        "direction":       position["direction"],
        "entry_date":      position["entry_date"],
        "entry_price":     entry_price,
        "entry_rating":    position["entry_rating"],
        "entry_confidence":position["entry_confidence"],
        "price_target":    position["price_target"],
        "spy_entry_price": spy_entry,
        "exit_date":       exit_date,
        "exit_price":      float(exit_price),
        "exit_rating":     exit_rating,
        "return_pct":      round(return_pct, 6),
        "spy_return_pct":  round(spy_return_pct, 6),
        "alpha":           round(alpha, 6),
        # ── honest accounting (additive) ──
        "cost_bps":        cost_bps,
        "return_pct_net":  round(return_pct - rt_cost, 6),
        "alpha_net":       round(alpha - rt_cost, 6),
        "return_pct_tr":     (tr or {}).get("return_pct_tr"),
        "spy_return_tr":     (tr or {}).get("spy_return_tr"),
        "alpha_tr":          (tr or {}).get("alpha_tr"),
        "return_pct_tr_net": (tr or {}).get("return_pct_tr_net"),
        "alpha_tr_net":      (tr or {}).get("alpha_tr_net"),
        "capture_basis":     (tr or {}).get("capture_basis", "spot_only"),
        "constraints":     _CONSTRAINTS,
    }
    return record


# ─── Core processing (pure — no I/O) ─────────────────────────────────────────

def process_screener_results(
    screener_results: list[dict],
    current_positions: dict[str, dict],
    spy_price: float,
    today: str,
) -> tuple[dict[str, dict], list[dict], list[str], list[str]]:
    """Apply entry/exit rules to fresh screener output.

    Only acts on tickers with status != SKIPPED and ok=True (freshly screened).
    Skipped tickers leave existing positions undisturbed — we wait for the
    next screen before deciding to close.

    Returns (new_positions, closed_trades, opened_tickers, closed_tickers).
    """
    positions = dict(current_positions)
    closed_trades: list[dict] = []
    opened: list[str] = []
    closed: list[str] = []

    for r in screener_results:
        if not r.get("ok") or r.get("status") in ("SKIPPED", "ERROR"):
            continue
        ticker     = r["ticker"]
        rating     = r.get("rating", "?")
        confidence = r.get("confidence", "?")
        price      = r.get("current_price")
        pt         = r.get("price_target") or 0.0

        if price is None or math.isnan(float(price)):
            continue

        if ticker in positions:
            if should_exit(rating):
                trade = close_position(
                    positions[ticker],
                    exit_date=today,
                    exit_price=price,
                    exit_rating=rating,
                    spy_exit_price=spy_price,
                )
                closed_trades.append(trade)
                closed.append(ticker)
                del positions[ticker]
            # else: still STRONG_BUY/BUY → hold, no action (idempotent)
        else:
            if should_enter(rating, confidence):
                positions[ticker] = open_position(
                    ticker=ticker,
                    entry_date=today,
                    entry_price=price,
                    entry_rating=rating,
                    entry_confidence=confidence,
                    price_target=pt,
                    spy_entry_price=spy_price,
                )
                opened.append(ticker)

    return positions, closed_trades, opened, closed


# ─── Schema validation (lightweight — plain functions, no deps) ──────────────

_NUMBER = (int, float)

# key -> accepted python type(s). Required keys only; extra keys are allowed.
_POSITION_SCHEMA: dict[str, object] = {
    "ticker": str,
    "cohort": str,
    "entry_date": str,
    "entry_price": _NUMBER,
    "entry_rating": str,
    "entry_confidence": str,
    "price_target": _NUMBER,
    "spy_entry_price": _NUMBER,
}

_TRADE_SCHEMA: dict[str, object] = {
    "ticker": str,
    "cohort": str,
    "entry_date": str,
    "entry_price": _NUMBER,
    "exit_date": str,
    "exit_price": _NUMBER,
    "exit_rating": str,
    "return_pct": _NUMBER,
    "spy_return_pct": _NUMBER,
    "alpha": _NUMBER,
}


def _validate(record: object, schema: dict[str, object], kind: str) -> None:
    """Raise ValueError if `record` is missing a required key or has a wrong type."""
    if not isinstance(record, dict):
        raise ValueError(f"{kind} record is not a mapping (got {type(record).__name__})")
    for key, types in schema.items():
        if key not in record:
            raise ValueError(f"{kind} record missing required key '{key}'")
        value = record[key]
        # bool is a subclass of int; reject it where a number is expected.
        if types is _NUMBER and isinstance(value, bool):
            raise ValueError(f"{kind} key '{key}' is a bool, expected a number")
        if not isinstance(value, types):
            expected = getattr(types, "__name__", str(types))
            raise ValueError(
                f"{kind} key '{key}' has type {type(value).__name__}, expected {expected}"
            )


def _validate_cohort(record: dict, kind: str) -> None:
    """Reject a record whose cohort is not one of VALID_COHORTS.

    Presence + str-type are already guaranteed by the schema, so an untagged
    record fails on the missing key; here we reject an unknown tag value. There
    is deliberately no default — an unrecognised cohort is an error, not a
    record to silently re-home into a valid cohort.
    """
    value = record["cohort"]
    if value not in VALID_COHORTS:
        raise ValueError(
            f"{kind} record has invalid cohort {value!r}; expected one of {VALID_COHORTS}"
        )


def validate_position(record: object) -> None:
    """Assert `record` has the required position keys/types and a valid cohort."""
    _validate(record, _POSITION_SCHEMA, "position")
    _validate_cohort(record, "position")


def validate_trade(record: object) -> None:
    """Assert `record` has the required closed-trade keys/types and a valid cohort."""
    _validate(record, _TRADE_SCHEMA, "trade")
    _validate_cohort(record, "trade")


# ─── I/O helpers ─────────────────────────────────────────────────────────────

def load_positions(path: Optional[Path] = None, *, strict: bool = False) -> dict[str, dict]:
    """Load open positions as {ticker: record}. Empty dict if file missing.

    Records that fail schema validation are logged (WARN) and skipped rather than
    crashing the caller. With ``strict=True`` an invalid record raises instead of
    being skipped — used by the report build to enforce the cohort gate.
    """
    p = path or POSITIONS_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    records = raw.get("positions") or []
    positions: dict[str, dict] = {}
    for i, r in enumerate(records):
        try:
            validate_position(r)
        except ValueError as e:
            if strict:
                raise ValueError(f"invalid position (index {i}) in {p}: {e}") from e
            logger.warning("skipping invalid position (index %d) in %s: %s", i, p, e)
            continue
        positions[r["ticker"]] = r
    return positions


def save_positions(positions: dict[str, dict], path: Optional[Path] = None) -> None:
    """Persist open positions to YAML atomically (tmp + os.replace)."""
    p = path or POSITIONS_PATH
    records = sorted(positions.values(), key=lambda r: r["ticker"])
    text = yaml.dump({"positions": records}, default_flow_style=False, sort_keys=False)
    atomic_write_text(p, text)


def load_trades(path: Optional[Path] = None, *, strict: bool = False) -> list[dict]:
    """Load all closed trade records from the JSONL log.

    Malformed lines (bad JSON or failing schema/cohort validation) are logged
    (WARN) and skipped. With ``strict=True`` the first bad line raises instead —
    used by the report build to enforce the cohort gate.
    """
    p = path or TRADES_PATH
    if not p.exists():
        return []
    trades = []
    with open(p) as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                validate_trade(record)
            except (ValueError, json.JSONDecodeError) as e:
                if strict:
                    raise ValueError(f"malformed trade at {p} line {lineno}: {e}") from e
                logger.warning("skipping malformed trade at %s line %d: %s", p, lineno, e)
                continue
            trades.append(record)
    return trades


def append_trade(trade: dict, path: Optional[Path] = None) -> None:
    """Append one closed trade to the JSONL log, fsync'd before returning."""
    p = path or TRADES_PATH
    append_jsonl(p, trade, default=str)


def fetch_spy_price() -> Optional[float]:
    """Fetch current SPY price via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker("SPY").info
        for key in ("regularMarketPrice", "currentPrice", "previousClose"):
            v = info.get(key)
            if v is not None and float(v) > 0:
                return float(v)
    except Exception:
        return None
    return None
