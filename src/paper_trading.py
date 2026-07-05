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
import math
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from src.io_utils import append_jsonl, atomic_write_text

POSITIONS_PATH = Path(__file__).parent.parent / "data" / "paper_positions.yaml"
TRADES_PATH    = Path(__file__).parent.parent / "data" / "paper_trades.jsonl"

_CONSTRAINTS = {"no_real_orders": True, "no_live_pnl_learning": True}


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
) -> dict:
    """Build an open position record. Pure — no I/O."""
    return {
        "ticker": ticker,
        "direction": "LONG",
        "entry_date": entry_date,
        "entry_price": float(entry_price),
        "entry_rating": entry_rating,
        "entry_confidence": entry_confidence,
        "price_target": float(price_target),
        "spy_entry_price": float(spy_entry_price),
        "constraints": _CONSTRAINTS,
    }


def close_position(
    position: dict,
    exit_date: str,
    exit_price: float,
    exit_rating: str,
    spy_exit_price: float,
) -> dict:
    """Compute return and SPY alpha, return a closed trade record. Pure — no I/O."""
    entry_price    = position["entry_price"]
    spy_entry      = position["spy_entry_price"]
    return_pct     = float(exit_price) / entry_price - 1.0
    spy_return_pct = float(spy_exit_price) / spy_entry - 1.0
    alpha          = return_pct - spy_return_pct

    return {
        "ticker":          position["ticker"],
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
        "constraints":     _CONSTRAINTS,
    }


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


# ─── I/O helpers ─────────────────────────────────────────────────────────────

def load_positions(path: Optional[Path] = None) -> dict[str, dict]:
    """Load open positions as {ticker: record}. Empty dict if file missing."""
    p = path or POSITIONS_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    records = raw.get("positions") or []
    return {r["ticker"]: r for r in records if "ticker" in r}


def save_positions(positions: dict[str, dict], path: Optional[Path] = None) -> None:
    """Persist open positions to YAML atomically (tmp + os.replace)."""
    p = path or POSITIONS_PATH
    records = sorted(positions.values(), key=lambda r: r["ticker"])
    text = yaml.dump({"positions": records}, default_flow_style=False, sort_keys=False)
    atomic_write_text(p, text)


def load_trades(path: Optional[Path] = None) -> list[dict]:
    """Load all closed trade records from the JSONL log."""
    p = path or TRADES_PATH
    if not p.exists():
        return []
    trades = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
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
