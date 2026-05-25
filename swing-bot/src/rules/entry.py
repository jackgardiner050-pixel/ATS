"""Entry rule evaluation. Pure functions — no I/O, no LLM calls.

ALL four conditions must be True to open a paper position:
  1. Catalyst trigger (passes filters.py)
  2. Momentum: stock up ≥ 3% on the day AND 5-day trend ≥ -1%
  3. Liquidity: avg daily volume ≥ £5M notional (≈ $6.35M at 1.27 GBPUSD)
  4. Concurrency: fewer than 10 open positions

Hard rule: position sizing is fixed at £50 / position. No LLM sizing decisions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class EntrySignal:
    ticker: str
    entry_price: float
    catalyst: dict
    shares: float           # £50 / entry_price (fractional OK)
    notional_gbp: float     # always 50.0
    stop_loss_price: float  # entry * 0.95
    profit_target_price: float  # entry * 1.10


@dataclass
class EntryCheckResult:
    passed: bool
    ticker: str
    reason: str             # why it passed or which condition failed
    catalyst_type: str
    price_change_pct: Optional[float] = None
    trend_5d_pct: Optional[float] = None
    avg_daily_volume_usd: Optional[float] = None
    n_open_positions: Optional[int] = None


def check_entry(
    ticker: str,
    catalyst: dict,
    market_data: dict,
    n_open_positions: int,
    position_size_gbp: float = 50.0,
    min_price_change_pct: float = 3.0,
    min_liquidity_usd: float = 6_350_000,
    five_day_trend_floor_pct: float = -1.0,
    max_positions: int = 10,
) -> EntryCheckResult:
    """Evaluate all entry conditions for a single ticker + catalyst.

    Args:
        ticker:              Ticker symbol.
        catalyst:            Catalyst dict (already passed filters.py).
        market_data:         Dict with keys: current_price, price_change_pct,
                             trend_5d_pct, avg_daily_volume_usd.
        n_open_positions:    Current number of open paper positions.
        position_size_gbp:   Fixed position size in GBP (default £50).
        min_price_change_pct: Minimum intraday price change (default 3%).
        min_liquidity_usd:   Minimum avg daily volume in USD (default $6.35M).
        five_day_trend_floor_pct: Minimum 5-day trend (default -1%).
        max_positions:       Maximum concurrent positions (default 10).

    Returns:
        EntryCheckResult with passed=True/False and the reason.
    """
    base = EntryCheckResult(
        passed=False,
        ticker=ticker,
        reason="",
        catalyst_type=catalyst.get("catalyst_type", "?"),
        price_change_pct=market_data.get("price_change_pct"),
        trend_5d_pct=market_data.get("trend_5d_pct"),
        avg_daily_volume_usd=market_data.get("avg_daily_volume_usd"),
        n_open_positions=n_open_positions,
    )

    # Condition 4: concurrency
    if n_open_positions >= max_positions:
        base.reason = f"concurrency_limit ({n_open_positions}/{max_positions} positions open)"
        return base

    # Condition 2: momentum — price change on the day
    price_change = market_data.get("price_change_pct", 0.0)
    if price_change < min_price_change_pct:
        base.reason = f"momentum_fail (price_change={price_change:.1f}% < {min_price_change_pct}%)"
        return base

    # Condition 2: momentum — 5-day trend
    trend_5d = market_data.get("trend_5d_pct", 0.0)
    if trend_5d < five_day_trend_floor_pct:
        base.reason = f"trend_fail (5d_trend={trend_5d:.1f}% < {five_day_trend_floor_pct}%)"
        return base

    # Condition 3: liquidity
    avg_vol_usd = market_data.get("avg_daily_volume_usd", 0.0)
    if avg_vol_usd < min_liquidity_usd:
        base.reason = (
            f"liquidity_fail (avg_daily_vol=${avg_vol_usd:,.0f} < ${min_liquidity_usd:,.0f})"
        )
        return base

    # All conditions passed
    current_price = market_data.get("current_price", 0.0)
    if current_price <= 0:
        base.reason = "invalid_price"
        return base

    base.passed = True
    base.reason = "all_conditions_passed"
    return base


def build_entry_signal(
    ticker: str,
    catalyst: dict,
    current_price: float,
    position_size_gbp: float = 50.0,
    profit_target_pct: float = 10.0,
    stop_loss_pct: float = -5.0,
) -> EntrySignal:
    """Build the entry signal record after all conditions pass.

    Never invents numbers — price comes from market data, targets are fixed %.
    """
    shares = position_size_gbp / current_price  # fractional shares
    return EntrySignal(
        ticker=ticker,
        entry_price=current_price,
        catalyst=catalyst,
        shares=round(shares, 6),
        notional_gbp=position_size_gbp,
        stop_loss_price=round(current_price * (1 + stop_loss_pct / 100), 4),
        profit_target_price=round(current_price * (1 + profit_target_pct / 100), 4),
    )


def fetch_market_data(ticker: str) -> dict:
    """Fetch current price, intraday change, 5-day trend, and liquidity.

    Returns dict with: current_price, price_change_pct, trend_5d_pct,
                       avg_daily_volume_usd. Returns empty dict on failure.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="35d")
        if hist is None or (hasattr(hist, "empty") and hist.empty) or len(hist) < 5:
            return {}

        today = hist.iloc[-1]
        current_price = float(today["Close"])
        open_price = float(today.get("Open", current_price))
        price_change_pct = (current_price - open_price) / open_price * 100 if open_price > 0 else 0

        # 5-day trend: close 5 days ago vs today
        day_5_ago = float(hist.iloc[-6]["Close"]) if len(hist) >= 6 else float(hist.iloc[0]["Close"])
        trend_5d_pct = (current_price - day_5_ago) / day_5_ago * 100 if day_5_ago > 0 else 0

        # 30-day avg daily volume in USD
        avg_vol_shares = float(hist["Volume"].tail(30).mean())
        avg_price = float(hist["Close"].tail(30).mean())
        avg_daily_volume_usd = avg_vol_shares * avg_price

        return {
            "current_price": current_price,
            "price_change_pct": round(price_change_pct, 2),
            "trend_5d_pct": round(trend_5d_pct, 2),
            "avg_daily_volume_usd": round(avg_daily_volume_usd, 0),
        }
    except Exception as exc:
        log.debug("Market data fetch failed for %s: %s", ticker, exc)
        return {}
