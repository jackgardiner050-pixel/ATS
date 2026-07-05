"""Paper-book NAV ledger — pure performance math over daily NAV snapshots.

No I/O, no broker, no yfinance here (scripts/nav_snapshot.py does that). Every
function is a pure function of its inputs so it can be unit-tested with synthetic
series. Cohorts are kept strictly separate per the observation protocol — a NAV
line and a performance figure are always for exactly one cohort, never blended.

Sizing (fixed at entry):
    units = (nav_start / n_target_positions) / entry_price

NAV accounting (per cohort), with cost = paper_cost_bps / 10_000 applied per side:
    cash = nav_start
           - Σ_open   units·entry_price·(1 + cost)          # capital + entry haircut
           + Σ_closed (units·exit_price·(1 - cost)          # exit proceeds, net haircut
                       - units·entry_price·(1 + cost))      #   minus original cost basis
    nav  = cash + Σ_open units·close
         = nav_start + unrealised P&L (net of entry cost) + realised P&L

Benchmark (total-return): benchmark_nav = nav_start · (spy_tr_index / spy_at_inception).
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

_TRADING_DAYS = 252
_ANN = math.sqrt(_TRADING_DAYS)


# ─── Sizing ──────────────────────────────────────────────────────────────────

def compute_units(nav_start: float, n_target_positions: int, entry_price: float) -> float:
    """Units bought at entry for an equal-weight sleeve. Pure."""
    if entry_price <= 0:
        raise ValueError(f"entry_price must be positive, got {entry_price}")
    if n_target_positions <= 0:
        raise ValueError(f"n_target_positions must be positive, got {n_target_positions}")
    return (nav_start / n_target_positions) / entry_price


# ─── Drawdown ────────────────────────────────────────────────────────────────

def max_drawdown(series: list[float]) -> float:
    """Maximum peak-to-trough decline of a NAV series, as a non-negative fraction."""
    peak = float("-inf")
    mdd = 0.0
    for v in series:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


# ─── Snapshot construction ───────────────────────────────────────────────────

def build_snapshot(
    *,
    date: str,
    cohort: str,
    open_positions: list[dict],
    closed_trades: list[dict],
    prices: dict[str, float],
    spy_tr_index: float,
    spy_inception_price: float,
    nav_start: float,
    n_target_positions: int,
    cost_bps: float,
) -> dict:
    """Build one day's NAV snapshot line for a single cohort. Pure.

    `open_positions` / `closed_trades` are already filtered to this cohort. A
    position may carry a persisted "units"; if absent, units are derived from
    entry_price. A missing price marks the sleeve flat at entry (no fabricated move).
    """
    cost = cost_bps / 10_000.0
    positions_out: dict[str, dict] = {}
    invested = 0.0
    open_cost_basis = 0.0

    for p in open_positions:
        ticker = p["ticker"]
        entry_price = float(p["entry_price"])
        units = p.get("units")
        units = float(units) if units is not None else compute_units(
            nav_start, n_target_positions, entry_price)
        raw_close = prices.get(ticker)
        close = float(raw_close) if raw_close is not None else entry_price  # flat fallback
        value = units * close
        positions_out[ticker] = {"units": units, "close": close, "value": value}
        invested += value
        open_cost_basis += units * entry_price * (1 + cost)

    realized = 0.0
    for t in closed_trades:
        entry_price = float(t["entry_price"])
        exit_price = float(t["exit_price"])
        units = compute_units(nav_start, n_target_positions, entry_price)
        realized += units * exit_price * (1 - cost) - units * entry_price * (1 + cost)

    cash = nav_start - open_cost_basis + realized
    nav = cash + invested
    benchmark_nav = (
        nav_start * (spy_tr_index / spy_inception_price)
        if spy_inception_price else None
    )

    return {
        "date": date,
        "nav": round(nav, 2),
        "cash": round(cash, 2),
        "n_positions": len(open_positions),
        "cohort": cohort,
        "positions": {
            t: {"units": v["units"], "close": v["close"], "value": round(v["value"], 2)}
            for t, v in positions_out.items()
        },
        "spy_tr_index": spy_tr_index,
        "benchmark_nav": round(benchmark_nav, 2) if benchmark_nav is not None else None,
    }


# ─── Idempotent upsert ───────────────────────────────────────────────────────

def upsert_snapshots(existing: list[dict], new: list[dict]) -> list[dict]:
    """Replace any (date, cohort) rows present in `new`, keep the rest; sort stable.

    Makes a same-day re-run idempotent: the day's line for a cohort is replaced,
    never duplicated.
    """
    replace_keys = {(s["date"], s["cohort"]) for s in new}
    kept = [r for r in existing if (r.get("date"), r.get("cohort")) not in replace_keys]
    merged = kept + list(new)
    return sorted(merged, key=lambda r: (r.get("date", ""), r.get("cohort", "")))


# ─── Performance ─────────────────────────────────────────────────────────────

def compute_performance(nav_history: list[dict], cohort: str) -> dict:
    """Performance metrics for one cohort from its NAV history. Pure.

    Returns a dict with keys: twr, spy_twr, excess, max_dd, spy_max_dd, sharpe,
    information_ratio, tracking_error, n_days. Metrics that need more data than is
    available are None (never extrapolated). rf = 0; daily → annualized via √252.
    """
    rows = sorted((r for r in nav_history if r.get("cohort") == cohort),
                  key=lambda r: r["date"])
    n = len(rows)
    navs = [float(r["nav"]) for r in rows]
    has_bench = all(r.get("benchmark_nav") is not None for r in rows) and n > 0
    bench = [float(r["benchmark_nav"]) for r in rows] if has_bench else []

    out: dict[str, Optional[float]] = {
        "twr": None, "spy_twr": None, "excess": None,
        "max_dd": None, "spy_max_dd": None,
        "sharpe": None, "information_ratio": None, "tracking_error": None,
        "n_days": n,
    }
    if n >= 1:
        out["max_dd"] = max_drawdown(navs)
        if has_bench:
            out["spy_max_dd"] = max_drawdown(bench)
    if n < 2:
        return out

    out["twr"] = navs[-1] / navs[0] - 1 if navs[0] else None
    if has_bench and bench[0]:
        out["spy_twr"] = bench[-1] / bench[0] - 1
        if out["twr"] is not None:
            out["excess"] = out["twr"] - out["spy_twr"]

    port_r = [navs[i] / navs[i - 1] - 1 for i in range(1, n) if navs[i - 1]]
    if len(port_r) >= 2 and statistics.pstdev(port_r) > 0:
        out["sharpe"] = statistics.mean(port_r) / statistics.pstdev(port_r) * _ANN

    if has_bench:
        spy_r = [bench[i] / bench[i - 1] - 1 for i in range(1, n) if bench[i - 1]]
        if len(spy_r) == len(port_r) and len(port_r) >= 2:
            excess_r = [p - s for p, s in zip(port_r, spy_r)]
            te = statistics.pstdev(excess_r)
            out["tracking_error"] = te * _ANN
            if te > 0:
                out["information_ratio"] = statistics.mean(excess_r) / te * _ANN

    return out
