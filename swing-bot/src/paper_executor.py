"""Paper trade executor — opens and closes simulated positions.

Hard rules enforced here:
  paper_only: True  — place_real_order() raises RuntimeError, always
  no_real_orders: True
  no_live_pnl_learning: True — trades logged for analysis, never fed back to models

Storage (ringfenced from long-term agent):
  data/swing_paper_positions.yaml   — open positions
  data/swing_paper_trades.jsonl     — immutable closed trade log
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

_POSITIONS_PATH = Path(__file__).parent.parent / "data" / "swing_paper_positions.yaml"
_TRADES_PATH = Path(__file__).parent.parent / "data" / "swing_paper_trades.jsonl"

_CONSTRAINTS = {
    "no_real_orders": True,
    "paper_only": True,
    "no_live_pnl_learning": True,
    "ringfenced": True,
}


# ─── Hard rule enforcement ────────────────────────────────────────────────────

def place_real_order(*args, **kwargs):
    """This function exists to permanently prevent real order placement.

    Hard rule #10 from SWING_BOT_V1_BUILD_SPEC.md.
    """
    raise RuntimeError("Order placement permanently disabled.")


# ─── Position lifecycle ───────────────────────────────────────────────────────

def open_position(
    ticker: str,
    entry_date: str,
    entry_price: float,
    shares: float,
    notional_gbp: float,
    catalyst: dict,
    spy_entry_price: float,
    stop_loss_price: float,
    profit_target_price: float,
    time_exit_date: str,
) -> dict:
    """Build an open position record. Pure — no I/O."""
    return {
        "ticker": ticker,
        "direction": "LONG",
        "entry_date": entry_date,
        "entry_price": float(entry_price),
        "shares": float(shares),
        "notional_gbp": float(notional_gbp),
        "catalyst_type": catalyst.get("catalyst_type", "?"),
        "catalyst_detail": {
            k: v for k, v in catalyst.items()
            if k in ("items", "eps_beat_pct", "volume_ratio", "category", "confidence", "title")
        },
        "spy_entry_price": float(spy_entry_price),
        "stop_loss_price": float(stop_loss_price),
        "profit_target_price": float(profit_target_price),
        "time_exit_date": time_exit_date,
        "constraints": _CONSTRAINTS,
    }


def close_position(
    position: dict,
    exit_date: str,
    exit_price: float,
    exit_reason: str,
    spy_exit_price: float,
) -> dict:
    """Compute return + SPY alpha, return a closed trade record. Pure — no I/O."""
    entry_price = float(position["entry_price"])
    spy_entry = float(position["spy_entry_price"])
    shares = float(position["shares"])
    notional = float(position.get("notional_gbp", 50.0))

    return_pct = float(exit_price) / entry_price - 1.0
    spy_return_pct = float(spy_exit_price) / spy_entry - 1.0
    alpha = return_pct - spy_return_pct
    pnl_gbp = notional * return_pct

    return {
        "ticker": position["ticker"],
        "direction": position["direction"],
        "entry_date": position["entry_date"],
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "shares": shares,
        "notional_gbp": notional,
        "return_pct": round(return_pct, 6),
        "spy_return_pct": round(spy_return_pct, 6),
        "alpha": round(alpha, 6),
        "pnl_gbp": round(pnl_gbp, 4),
        "catalyst_type": position.get("catalyst_type", "?"),
        "catalyst_detail": position.get("catalyst_detail", {}),
        "spy_entry_price": spy_entry,
        "spy_exit_price": float(spy_exit_price),
        "constraints": _CONSTRAINTS,
    }


# ─── I/O helpers ─────────────────────────────────────────────────────────────

def load_positions(path: Optional[Path] = None) -> dict[str, dict]:
    """Load open positions as {ticker: record}. Returns {} if file missing."""
    p = path or _POSITIONS_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    records = raw.get("positions") or []
    return {r["ticker"]: r for r in records if "ticker" in r}


def save_positions(positions: dict[str, dict], path: Optional[Path] = None) -> None:
    """Persist open positions to YAML."""
    p = path or _POSITIONS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    records = sorted(positions.values(), key=lambda r: r["ticker"])
    with open(p, "w") as f:
        yaml.dump({"positions": records}, f, default_flow_style=False, sort_keys=False)


def load_trades(path: Optional[Path] = None) -> list[dict]:
    """Load all closed trade records from the JSONL log."""
    p = path or _TRADES_PATH
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
    """Append one closed trade record to the immutable JSONL log."""
    p = path or _TRADES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(trade, default=str) + "\n")
