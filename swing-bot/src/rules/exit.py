"""Exit rule evaluation. Pure functions — no I/O.

Exit conditions (first to trigger closes the position):
  1. Profit target: +10% from entry price
  2. Stop loss: -5% from entry price
  3. Time exit: 10 trading days since entry date
  4. Signal reversal: negative 8-K event for the ticker

Hard rule: all thresholds come from config, never invented by LLM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

_TRADING_DAYS_PER_WEEK = 5


@dataclass
class ExitSignal:
    should_exit: bool
    reason: str           # "profit_target" | "stop_loss" | "time_exit" | "signal_reversal" | "hold"
    current_price: float
    return_pct: float


def check_exit(
    position: dict,
    current_price: float,
    today: str,
    negative_catalyst: bool = False,
    profit_target_pct: float = 10.0,
    stop_loss_pct: float = -5.0,
    max_hold_trading_days: int = 10,
) -> ExitSignal:
    """Evaluate exit conditions for an open position.

    Args:
        position:             Open position dict from paper_executor.
        current_price:        Current market price.
        today:                ISO date string "YYYY-MM-DD".
        negative_catalyst:    True if a negative 8-K/event hit this ticker today.
        profit_target_pct:    +10% by default.
        stop_loss_pct:        -5% by default.
        max_hold_trading_days: 10 trading days by default.

    Returns:
        ExitSignal — should_exit=False means "hold".
    """
    entry_price = float(position["entry_price"])
    if entry_price <= 0 or current_price <= 0:
        return ExitSignal(should_exit=False, reason="invalid_price",
                          current_price=current_price, return_pct=0.0)

    return_pct = (current_price - entry_price) / entry_price * 100

    # Condition 4: signal reversal (check first — override everything)
    if negative_catalyst:
        return ExitSignal(
            should_exit=True,
            reason="signal_reversal",
            current_price=current_price,
            return_pct=round(return_pct, 4),
        )

    # Condition 1: profit target
    if return_pct >= profit_target_pct:
        return ExitSignal(
            should_exit=True,
            reason="profit_target",
            current_price=current_price,
            return_pct=round(return_pct, 4),
        )

    # Condition 2: stop loss
    if return_pct <= stop_loss_pct:
        return ExitSignal(
            should_exit=True,
            reason="stop_loss",
            current_price=current_price,
            return_pct=round(return_pct, 4),
        )

    # Condition 3: time exit (count trading days)
    entry_date = position.get("entry_date", today)
    n_trading_days = _count_trading_days(entry_date, today)
    if n_trading_days >= max_hold_trading_days:
        return ExitSignal(
            should_exit=True,
            reason="time_exit",
            current_price=current_price,
            return_pct=round(return_pct, 4),
        )

    return ExitSignal(
        should_exit=False,
        reason="hold",
        current_price=current_price,
        return_pct=round(return_pct, 4),
    )


def _count_trading_days(start_date: str, end_date: str) -> int:
    """Count trading days (Mon-Fri) between two ISO date strings, inclusive of start."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return 0

    if end < start:
        return 0

    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            count += 1
        from datetime import timedelta
        current += timedelta(days=1)
    return count
