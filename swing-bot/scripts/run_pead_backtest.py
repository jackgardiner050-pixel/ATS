#!/usr/bin/env python3
"""Swing Bot v1 — PEAD (Post-Earnings Announcement Drift) Backtest

Strategy:
  Entry: close of T+1 (day after earnings) when:
    - EPS beat ≥ 5% vs consensus estimate
    - Revenue grew YoY (any positive growth, proxy for revenue beat)
    - Stock up ≥ 3% on T+1 (close-to-close from earnings date)
    - Avg daily volume ≥ £5M ($6.35M)
    - Fewer than 10 concurrent positions

  Exit (first to trigger):
    - Profit target: +15%
    - Stop loss: −8%
    - Time exit: 90 trading days
    - Signal reversal: subsequent earnings miss (EPS surprise < 0)

Same 24-month window (2024-01-01 to 2025-12-31) and ticker universe as Phase A.
No LLM calls — pure rules. Cost: £0.

Output: swing-bot/backtest/PEAD_RESULTS.md
"""
from __future__ import annotations

import importlib.util
import json
import logging
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

# ── Shared infrastructure from run_backtest.py ────────────────────────────────
_ROOT  = Path(__file__).parent.parent
_BROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
_spec = importlib.util.spec_from_file_location("run_backtest", _BROOT / "run_backtest.py")
_bt   = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bt)

log = logging.getLogger("pead")

# ── Constants ─────────────────────────────────────────────────────────────────
BACKTEST_START        = "2024-01-01"
BACKTEST_END          = "2025-12-31"
POSITION_SIZE_GBP     = 50.0
MAX_POSITIONS         = 10
PORTFOLIO_START       = 500.0
GBPUSD                = 1.27
MIN_LIQUIDITY_USD     = 6_350_000        # £5M ≈ $6.35M
PRICE_MOVE_MIN_PCT    = 3.0              # T+1 close-to-close vs T close
EPS_BEAT_DEFAULT      = 5.0
EPS_BEAT_THRESHOLDS   = [3.0, 5.0, 7.0, 10.0]
PROFIT_TARGET_PCT     = 15.0
STOP_LOSS_PCT         = -8.0
MAX_HOLD_DAYS         = 90              # trading days
N_MC_SIMS             = 10_000
BACKTEST_MONTHS       = 24

_OUTPUT_DIR  = _ROOT / "backtest"
_EARN_CACHE  = _ROOT / "data" / "pead" / "earnings"


# ── Earnings fetch + cache ────────────────────────────────────────────────────
def _fetch_earnings(sym: str) -> list[dict]:
    """Fetch earnings history for one ticker. Cached 7 days."""
    cache = _EARN_CACHE / f"{sym}.json"
    if cache.exists():
        age = (date.today() - date.fromtimestamp(cache.stat().st_mtime)).days
        if age < 7:
            return json.loads(cache.read_text())

    results: list[dict] = []
    try:
        tk = yf.Ticker(sym)

        # ── EPS beats from earnings_dates ──────────────────────────────────
        ed = None
        for attr in ("get_earnings_dates", "earnings_dates"):
            try:
                ed = tk.get_earnings_dates(limit=24) if attr == "get_earnings_dates" else tk.earnings_dates
                if ed is not None and not ed.empty:
                    break
            except Exception:
                ed = None

        if ed is None or ed.empty:
            return []

        # Normalise column names (yfinance changes them across versions)
        ed.columns = [str(c).strip() for c in ed.columns]
        col_map: dict[str, str] = {}
        for col in ed.columns:
            cl = col.lower()
            if "eps estimate" in cl or "eps_estimate" in cl:
                col_map["eps_est"] = col
            elif "reported" in cl or "eps actual" in cl or "eps_actual" in cl:
                col_map["eps_act"] = col
            elif "surprise" in cl:
                col_map["surprise"] = col

        # ── Revenue YoY from quarterly income statement ────────────────────
        rev_by_quarter: dict[str, float] = {}   # "YYYY-QN" -> revenue
        try:
            fin = None
            for attr in ("quarterly_income_stmt", "quarterly_financials"):
                try:
                    fin = getattr(tk, attr)
                    if fin is not None and not fin.empty:
                        break
                except Exception:
                    fin = None

            if fin is not None and not fin.empty:
                rev_row = None
                for label in ("Total Revenue", "TotalRevenue", "Revenue"):
                    if label in fin.index:
                        rev_row = fin.loc[label]
                        break

                if rev_row is not None:
                    rev_row = rev_row.dropna().sort_index()
                    for qdt, val in rev_row.items():
                        key = f"{qdt.year}-Q{(qdt.month - 1) // 3 + 1}"
                        rev_by_quarter[key] = float(val)
        except Exception:
            pass

        def _rev_yoy(earn_date_str: str) -> Optional[float]:
            """Return YoY revenue growth % for the quarter matching earn_date."""
            try:
                dt = pd.Timestamp(earn_date_str)
                qkey = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
                # same quarter prior year
                prior_qkey = f"{dt.year - 1}-Q{(dt.month - 1) // 3 + 1}"
                curr = rev_by_quarter.get(qkey)
                prior = rev_by_quarter.get(prior_qkey)
                if curr is not None and prior is not None and prior != 0:
                    return round((curr - prior) / abs(prior) * 100, 1)
            except Exception:
                pass
            return None

        # ── Build per-earnings dicts ──────────────────────────────────────
        for earn_date, row in ed.iterrows():
            try:
                d_str = str(earn_date.date()) if hasattr(earn_date, "date") else str(earn_date)[:10]
            except Exception:
                continue

            try:
                eps_est = float(row[col_map["eps_est"]]) if "eps_est" in col_map else None
            except (ValueError, TypeError):
                eps_est = None
            try:
                eps_act = float(row[col_map["eps_act"]]) if "eps_act" in col_map else None
            except (ValueError, TypeError):
                eps_act = None
            try:
                surprise = float(row[col_map["surprise"]]) if "surprise" in col_map else None
                if surprise is None and eps_est is not None and eps_act is not None and eps_est != 0:
                    surprise = round((eps_act - eps_est) / abs(eps_est) * 100, 2)
            except (ValueError, TypeError):
                surprise = None

            results.append({
                "date":            d_str,
                "eps_estimate":    eps_est,
                "eps_actual":      eps_act,
                "surprise_pct":    surprise,
                "revenue_yoy_pct": _rev_yoy(d_str),
            })

        results.sort(key=lambda x: x["date"])
    except Exception as exc:
        log.warning("Earnings fetch failed for %s: %s", sym, exc)
        return []

    _EARN_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(results, indent=2))
    time.sleep(0.3)
    return results


# ── Price helpers ─────────────────────────────────────────────────────────────
def _get_t1_data(df: pd.DataFrame, earnings_date_str: str) -> Optional[dict]:
    """Return T+1 entry data: close-to-close % move T→T+1, avg volume, entry price."""
    target = pd.Timestamp(earnings_date_str).normalize()

    # Find T (earnings date or nearest next trading day within 3 days)
    t_close: Optional[float] = None
    t_idx: Optional[pd.Timestamp] = None
    for delta in range(4):
        dt = (target + pd.Timedelta(days=delta)).normalize()
        rows = df[df.index.normalize() == dt]
        if rows.empty:
            continue
        c = float(rows.iloc[-1].get("Close", 0) or 0)
        if c > 0:
            t_close = c
            t_idx   = rows.index[-1]
            break

    if t_close is None or t_idx is None:
        return None

    # T+1: next trading day after T
    t1_rows = df[df.index > t_idx].head(3)
    if t1_rows.empty:
        return None
    t1_row   = t1_rows.iloc[0]
    t1_close = float(t1_row.get("Close", 0) or 0)
    if t1_close <= 0:
        return None

    pct_change = (t1_close - t_close) / t_close * 100

    # 30-day avg daily notional (pre T+1)
    before      = df[df.index < t1_rows.index[0]].tail(30)
    avg_vol     = float(before["Volume"].mean()) if not before.empty else 0.0
    avg_price   = float(before["Close"].mean()) if not before.empty else t1_close
    avg_vol_usd = avg_vol * avg_price

    return {
        "entry_date":    str(t1_rows.index[0].date()),
        "entry_price":   t1_close,
        "t1_pct_change": round(pct_change, 2),
        "avg_vol_usd":   round(avg_vol_usd, 0),
    }


# ── Exit simulation ───────────────────────────────────────────────────────────
def _simulate_exit_pead(
    df: pd.DataFrame,
    entry_date: str,
    entry_price: float,
    subsequent_earnings: list[dict],
) -> dict:
    """Walk forward and apply PEAD exit rules."""
    entry_dt  = pd.Timestamp(entry_date).normalize()
    post      = df[df.index.normalize() > entry_dt].head(MAX_HOLD_DAYS + 10)
    traded    = 0

    # Pre-build set of subsequent miss dates for fast lookup
    miss_dates = {
        e["date"] for e in subsequent_earnings
        if e.get("surprise_pct") is not None and e["surprise_pct"] < 0
    }

    for idx, row in post.iterrows():
        close = float(row.get("Close", 0) or 0)
        if close <= 0:
            continue
        traded    += 1
        ret_pct    = (close - entry_price) / entry_price * 100
        cur_date   = str(idx.date())

        # Signal reversal (subsequent earnings miss — exit the day it's known)
        if cur_date in miss_dates:
            return {"exit_date": cur_date, "exit_price": close,
                    "exit_reason": "signal_reversal", "return_pct": ret_pct,
                    "hold_days": traded}

        if ret_pct >= PROFIT_TARGET_PCT:
            return {"exit_date": cur_date, "exit_price": close,
                    "exit_reason": "profit_target", "return_pct": ret_pct,
                    "hold_days": traded}

        if ret_pct <= STOP_LOSS_PCT:
            return {"exit_date": cur_date, "exit_price": close,
                    "exit_reason": "stop_loss", "return_pct": ret_pct,
                    "hold_days": traded}

        if traded >= MAX_HOLD_DAYS:
            return {"exit_date": cur_date, "exit_price": close,
                    "exit_reason": "time_exit", "return_pct": ret_pct,
                    "hold_days": traded}

    if post.empty:
        return {"exit_date": entry_date, "exit_price": entry_price,
                "exit_reason": "no_data", "return_pct": 0.0, "hold_days": 0}

    last   = post.iloc[-1]
    close  = float(last.get("Close", 0) or 0)
    return {"exit_date": str(post.index[-1].date()), "exit_price": close,
            "exit_reason": "time_exit",
            "return_pct": (close - entry_price) / entry_price * 100 if entry_price > 0 else 0.0,
            "hold_days": traded}


# ── Pipeline ──────────────────────────────────────────────────────────────────
def _build_candidates(
    earnings_data: dict[str, list[dict]],
    price_cache: dict,
    eps_threshold: float,
) -> list[dict]:
    """Apply entry filters. Returns candidates sorted by entry_date."""
    candidates: list[dict] = []

    for sym, elist in earnings_data.items():
        df = price_cache.get(sym)
        if df is None or df.empty:
            continue

        for earn in elist:
            d = earn["date"]
            if d < BACKTEST_START or d > BACKTEST_END:
                continue

            # EPS beat
            surprise = earn.get("surprise_pct")
            if surprise is None or surprise < eps_threshold:
                continue

            # Revenue beat (YoY > 0); skip if no data (don't disqualify)
            rev_yoy = earn.get("revenue_yoy_pct")
            if rev_yoy is not None and rev_yoy <= 0.0:
                continue

            # T+1 data
            t1 = _get_t1_data(df, d)
            if t1 is None:
                continue

            # Price move ≥ 3% (T close → T+1 close)
            if t1["t1_pct_change"] < PRICE_MOVE_MIN_PCT:
                continue

            # Liquidity
            if t1["avg_vol_usd"] < MIN_LIQUIDITY_USD:
                continue

            candidates.append({
                "ticker":          sym,
                "earnings_date":   d,
                "entry_date":      t1["entry_date"],
                "entry_price":     t1["entry_price"],
                "eps_beat_pct":    round(surprise, 2),
                "revenue_yoy_pct": rev_yoy,
                "t1_move_pct":     t1["t1_pct_change"],
                "avg_vol_usd":     t1["avg_vol_usd"],
            })

    return sorted(candidates, key=lambda x: x["entry_date"])


def _simulate_all(
    candidates: list[dict],
    price_cache: dict,
    earnings_data: dict[str, list[dict]],
) -> list[dict]:
    """Simulate exits, apply concurrency, return final trades."""
    raw: list[dict] = []
    subsequent_map: dict[str, list[dict]] = {}
    for sym, elist in earnings_data.items():
        subsequent_map[sym] = sorted(elist, key=lambda x: x["date"])

    for c in candidates:
        sym = c["ticker"]
        df  = price_cache.get(sym)
        if df is None:
            continue

        sub = [e for e in subsequent_map.get(sym, []) if e["date"] > c["entry_date"]]
        ex  = _simulate_exit_pead(df, c["entry_date"], c["entry_price"], sub)
        if ex["exit_reason"] == "no_data":
            continue

        raw.append({
            "ticker":          c["ticker"],
            "earnings_date":   c["earnings_date"],
            "eps_beat_pct":    c["eps_beat_pct"],
            "revenue_yoy_pct": c["revenue_yoy_pct"],
            "t1_move_pct":     c["t1_move_pct"],
            "entry_date":      c["entry_date"],
            "entry_price":     c["entry_price"],
            "exit_date":       ex["exit_date"],
            "exit_price":      ex["exit_price"],
            "exit_reason":     ex["exit_reason"],
            "return_pct":      round(ex["return_pct"], 4),
            "pnl_gbp":         round(POSITION_SIZE_GBP * ex["return_pct"] / 100, 4),
            "hold_days":       ex["hold_days"],
        })

    return _bt._apply_concurrency(raw)


# ── Stats + SPY + Equity curve ────────────────────────────────────────────────
def _trade_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "total_pnl": 0.0, "profit_factor": 0.0, "annualized_pct": 0.0,
                "expected_return": 0.0, "p_hard_kill": 0.0, "avg_hold_days": 0.0}

    wins   = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]

    win_rate     = len(wins) / n * 100
    avg_win      = statistics.mean([t["return_pct"] for t in wins])   if wins   else 0.0
    avg_loss     = statistics.mean([t["return_pct"] for t in losses]) if losses else 0.0
    gross_profit = sum(POSITION_SIZE_GBP * t["return_pct"] / 100 for t in wins)
    gross_loss   = abs(sum(POSITION_SIZE_GBP * t["return_pct"] / 100 for t in losses))
    total_pnl    = gross_profit - gross_loss
    pf           = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    ann          = (total_pnl / PORTFOLIO_START) * (12 / BACKTEST_MONTHS) * 100
    exp_ret      = avg_win * (win_rate / 100) + avg_loss * (1 - win_rate / 100)
    avg_hold     = statistics.mean([t["hold_days"] for t in trades])

    returns = [t["return_pct"] for t in trades]
    n_kill  = 0
    for _ in range(N_MC_SIMS):
        eq = PORTFOLIO_START
        pk = eq
        for r in random.choices(returns, k=n):
            eq += POSITION_SIZE_GBP * r / 100
            if eq > pk:
                pk = eq
            if pk > 0 and (eq - pk) / pk <= -0.20:
                n_kill += 1
                break
    p_hard_kill = n_kill / N_MC_SIMS * 100

    return {
        "n":              n,
        "win_rate":       round(win_rate, 1),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "total_pnl":      round(total_pnl, 2),
        "profit_factor":  round(pf, 2) if pf != float("inf") else 999.0,
        "annualized_pct": round(ann, 1),
        "expected_return":round(exp_ret, 2),
        "p_hard_kill":    round(p_hard_kill, 1),
        "avg_hold_days":  round(avg_hold, 1),
    }


def _spy_return() -> Optional[dict]:
    try:
        spy = yf.download("SPY", start=BACKTEST_START, end=BACKTEST_END,
                          auto_adjust=True, progress=False)
        if spy is None or spy.empty:
            return None
        spy   = spy.sort_index()
        close = spy["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()   # multi-level columns → Series
        s_price = float(close.iloc[0])
        e_price = float(close.iloc[-1])
        ret     = (e_price - s_price) / s_price * 100
        return {
            "start_price": round(s_price, 2),
            "end_price":   round(e_price, 2),
            "total_return_pct": round(ret, 1),
        }
    except Exception as exc:
        log.warning("SPY download failed: %s", exc)
        return None


def _monthly_equity(trades: list[dict]) -> list[dict]:
    """Month-end equity from closed P&L (running total from £500 start)."""
    equity  = PORTFOLIO_START
    result  = []
    year, month = 2024, 1
    while (year, month) <= (2025, 12):
        mon_str  = f"{year}-{month:02d}"
        mon_pnl  = sum(t["pnl_gbp"] for t in trades if t["exit_date"][:7] == mon_str)
        equity  += mon_pnl
        result.append({"month": mon_str, "pnl_gbp": round(mon_pnl, 2),
                        "equity_gbp": round(equity, 2)})
        month += 1
        if month > 12:
            month = 1
            year  += 1
    return result


def _exit_reason_breakdown(trades: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in trades:
        r = t["exit_reason"]
        counts[r] = counts.get(r, 0) + 1
    return counts


# ── Verdict ───────────────────────────────────────────────────────────────────
def _verdict(
    s: dict,
    spy: Optional[dict],
    sensitivity: Optional[list] = None,
    exit_breakdown: Optional[dict] = None,
) -> tuple[str, list[str]]:
    pf  = s["profit_factor"]
    wr  = s["win_rate"]
    n   = s["n"]
    pk  = s["p_hard_kill"]
    ann = s["annualized_pct"]
    reasons: list[str] = []

    spy_ret = spy["total_return_pct"] if spy else None

    if pf >= 1.50 and wr >= 55.0 and n >= 30 and pk < 3.0:
        label = "STRONG_GO"
        reasons.append(f"PF={pf:.2f}x, WR={wr:.1f}%, {n} trades, P(kill)={pk:.1f}% — strong PEAD edge confirmed.")
    elif pf >= 1.20 and wr >= 50.0 and n >= 20 and pk < 8.0 and ann > 0:
        label = "GO"
        reasons.append(f"PF={pf:.2f}x, WR={wr:.1f}%, {n} trades — positive PEAD edge. Live paper acceptable.")
    elif pf >= 1.00 and ann > 0 and pk < 15.0 and n >= 10:
        label = "CAUTION"
        reasons.append(f"PF={pf:.2f}x is marginal with {n} trades. Small-sample risk.")
    else:
        label = "NO_GO"
        reasons.append(
            f"PF={pf:.2f}x, WR={wr:.1f}%, P(hard kill)={pk:.1f}% — strategy as specified has "
            f"no reliable edge at the 5% EPS beat threshold."
        )

    # Stop-loss saturation
    if exit_breakdown:
        stops = exit_breakdown.get("stop_loss", 0)
        stop_pct = stops / n * 100 if n > 0 else 0
        if stop_pct >= 50:
            reasons.append(
                f"Stop-loss saturation: {stops}/{n} exits ({stop_pct:.0f}%) hit the −8% stop. "
                f"The entry trigger (+3% T+1 move) is already buying after the initial pop, "
                f"leaving little room before the stop is reached on a mean-reversion."
            )

    # P(kill) warning
    if pk >= 15.0:
        reasons.append(
            f"P(hard kill)={pk:.1f}% — unacceptably high for a £500 paper account. "
            f"The -8% stop is too wide relative to position size (£50) and recovery dynamics."
        )

    # Sensitivity note
    if sensitivity:
        best = min(sensitivity, key=lambda r: -r["stats"]["profit_factor"])
        if best["threshold"] != EPS_BEAT_DEFAULT and best["stats"]["profit_factor"] > pf:
            reasons.append(
                f"Best sensitivity result: EPS beat ≥ {best['threshold']:.0f}% gives "
                f"PF={best['stats']['profit_factor']:.2f}x, WR={best['stats']['win_rate']:.1f}%, "
                f"P(kill)={best['stats']['p_hard_kill']:.1f}% — a different threshold materially "
                f"changes outcomes, suggesting the 5% default is not a stable optimum."
            )

    # SPY comparison
    if spy_ret is not None:
        cmp = "beats" if ann > spy_ret else "underperforms"
        reasons.append(
            f"Strategy annualises at {ann:+.1f}% vs SPY {spy_ret:+.1f}% buy-and-hold over the same window ({cmp} SPY)."
        )

    # Sample-size caveat
    if n < 50:
        reasons.append(
            f"⚠ {n} trades is a thin sample — earnings data coverage varies by ticker "
            f"and yfinance historical estimates have known gaps. "
            f"These results may not generalise."
        )

    reasons.append(
        "Recommendation: do NOT run PEAD alongside the swing-bot catalyst strategy. "
        "If PEAD is to be revisited, use a dedicated earnings data provider (e.g. Finnhub "
        "earnings calendar) and widen the stop to −12% or switch to a trailing stop."
    )

    return label, reasons


# ── Report ────────────────────────────────────────────────────────────────────
def _write_report(
    main_stats:      dict,
    spy:             Optional[dict],
    sensitivity:     list[dict],
    equity_curve:    list[dict],
    exit_breakdown:  dict[str, int],
    verdict_label:   str,
    verdict_reasons: list[str],
    n_candidates:    int,
    n_earnings_total:int,
    run_date:        str,
) -> Path:
    icon  = {"STRONG_GO": "✅", "GO": "🟢", "CAUTION": "🟡", "NO_GO": "🔴"}.get(verdict_label, "❓")
    flip  = "**FLIP alert_mode_only → false**" if verdict_label in ("STRONG_GO", "GO") else "**KEEP alert_mode_only=true**"
    s     = main_stats

    lines = [
        "# Swing Bot v1 — PEAD Backtest Results",
        "",
        f"**Generated:** {run_date}  ",
        f"**Window:** {BACKTEST_START} → {BACKTEST_END} (24 months)  ",
        f"**Universe:** same watchlist as Phase A backtest  ",
        f"**Earnings events scanned:** {n_earnings_total}  ",
        f"**Candidates after entry filters (5% EPS beat):** {n_candidates}  ",
        f"**Trades after concurrency cap:** {s['n']}  ",
        f"**Monte Carlo:** {N_MC_SIMS:,} bootstrap simulations  ",
        "",
        "---",
        "",
        "## Summary Statistics",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Trades | {s['n']} |",
        f"| Win rate | {s['win_rate']:.1f}% |",
        f"| Avg win | {s['avg_win']:+.2f}% |",
        f"| Avg loss | {s['avg_loss']:+.2f}% |",
        f"| Expected return / trade | {s['expected_return']:+.2f}% |",
        f"| Profit factor | {s['profit_factor']:.2f}x |",
        f"| Total P&L | £{s['total_pnl']:+.2f} |",
        f"| Annualised return | {s['annualized_pct']:+.1f}% |",
        f"| Avg holding period | {s['avg_hold_days']:.0f} trading days |",
        f"| P(hard kill ≤−20%) | {s['p_hard_kill']:.1f}% |",
    ]

    if spy:
        lines.append(f"| SPY total return (same window) | {spy['total_return_pct']:+.1f}% |")

    # Exit breakdown
    lines += [
        "",
        "### Exit reasons",
        "",
        "| Reason | Count |",
        "|--------|------:|",
    ]
    for reason, cnt in sorted(exit_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {reason} | {cnt} |")

    # Sensitivity grid
    lines += [
        "",
        "---",
        "",
        "## Sensitivity: EPS Beat Threshold",
        "",
        "Entry filter varied; all other rules fixed (T+1 move ≥3%, vol ≥$6.35M, stop −8%, target +15%, 90d).  ",
        "◀ marks the default threshold (5%).",
        "",
        "| EPS beat ≥ | Candidates | Trades | Win rate | PF | Ann. % | P(kill) |",
        "|----------:|-----------:|-------:|---------:|---:|-------:|--------:|",
    ]
    for row in sensitivity:
        mark = " ◀" if row["threshold"] == EPS_BEAT_DEFAULT else ""
        s2   = row["stats"]
        pf_s = f"{s2['profit_factor']:.2f}x" if s2["profit_factor"] < 900 else "∞"
        lines.append(
            f"| {row['threshold']:.0f}% | {row['n_cands']} | {s2['n']} | "
            f"{s2['win_rate']:.1f}% | {pf_s} | {s2['annualized_pct']:+.1f}% | "
            f"{s2['p_hard_kill']:.1f}%{mark} |"
        )

    # Monthly equity curve
    lines += [
        "",
        "---",
        "",
        "## Monthly Equity Curve",
        "",
        "Starting capital £500. Equity moves when trades close.  ",
        "",
        "| Month | P&L | Equity |",
        "|-------|----:|-------:|",
    ]
    for row in equity_curve:
        pnl_str = f"£{row['pnl_gbp']:+.2f}" if row["pnl_gbp"] != 0 else "—"
        lines.append(f"| {row['month']} | {pnl_str} | £{row['equity_gbp']:.2f} |")

    # Verdict
    lines += [
        "",
        "---",
        "",
        f"## Verdict: {icon} {verdict_label}",
        "",
        f"**alert_mode_only:** {flip}",
        "",
    ]
    for r in verdict_reasons:
        lines.append(f"- {r}")

    lines += [
        "",
        "---",
        "",
        "**Strategy rules:**  ",
        f"Entry: T+1 close | EPS beat ≥ {EPS_BEAT_DEFAULT:.0f}% | Revenue YoY > 0 | "
        f"T+1 move ≥ {PRICE_MOVE_MIN_PCT:.0f}% | vol ≥ £5M  ",
        f"Exit: profit +{PROFIT_TARGET_PCT:.0f}% | stop −{abs(STOP_LOSS_PCT):.0f}% | "
        f"{MAX_HOLD_DAYS}d time exit | signal reversal  ",
        "",
        "*All positions paper-only. `place_real_order()` raises `RuntimeError`. "
        "Hard rules unchanged.*  ",
        f"*Generated by `run_pead_backtest.py` on {run_date}.*",
        "",
    ]

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUTPUT_DIR / "PEAD_RESULTS.md"
    out.write_text("\n".join(lines))
    log.info("Report: %s", out)
    return out


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    _bt._load_env()
    run_date = date.today().isoformat()

    print(f"\n{'=' * 64}")
    print(f"  Swing Bot v1 — PEAD Backtest")
    print(f"  Window: {BACKTEST_START} → {BACKTEST_END} | Cost: £0 (no LLM)")
    print(f"{'=' * 64}\n")

    # ── Price cache (reuse Phase A data) ─────────────────────────────────
    log.info("Loading ticker list and price cache...")
    tickers     = _bt._load_tickers()
    price_cache = _bt._load_price_cache(tickers)

    # ── Earnings data ─────────────────────────────────────────────────────
    log.info("Fetching earnings data for %d tickers...", len(tickers))
    earnings_data: dict[str, list[dict]] = {}
    n_earnings_total = 0
    for i, sym in enumerate(tickers):
        elist = _fetch_earnings(sym)
        if elist:
            earnings_data[sym] = elist
            in_window = [e for e in elist if BACKTEST_START <= e["date"] <= BACKTEST_END]
            n_earnings_total += len(in_window)
        if (i + 1) % 20 == 0:
            log.info("  Fetched earnings: %d / %d tickers", i + 1, len(tickers))
    log.info("Earnings events in window: %d across %d tickers",
             n_earnings_total, len(earnings_data))

    # ── Main backtest (5% EPS beat threshold) ─────────────────────────────
    log.info("Building candidates (EPS beat ≥ %.0f%%)...", EPS_BEAT_DEFAULT)
    candidates = _build_candidates(earnings_data, price_cache, EPS_BEAT_DEFAULT)
    log.info("Candidates: %d | Applying exit simulation...", len(candidates))
    trades = _simulate_all(candidates, price_cache, earnings_data)
    main_stats = _trade_stats(trades)
    log.info("Trades after concurrency: %d | PF=%.2fx | WR=%.1f%%",
             main_stats["n"], main_stats["profit_factor"], main_stats["win_rate"])

    # ── SPY benchmark ─────────────────────────────────────────────────────
    log.info("Downloading SPY benchmark...")
    spy = _spy_return()
    if spy:
        log.info("SPY total return %s → %s: %+.1f%%",
                 BACKTEST_START, BACKTEST_END, spy["total_return_pct"])

    # ── Sensitivity grid ──────────────────────────────────────────────────
    print("\n[SENSITIVITY] EPS beat threshold grid...")
    sensitivity: list[dict] = []
    for thresh in EPS_BEAT_THRESHOLDS:
        cands = _build_candidates(earnings_data, price_cache, thresh)
        tr    = _simulate_all(cands, price_cache, earnings_data)
        s     = _trade_stats(tr)
        sensitivity.append({"threshold": thresh, "n_cands": len(cands), "stats": s})
        log.info("  EPS ≥ %.0f%%: %d cands → %d trades | PF=%.2fx | WR=%.1f%% | Ann=%+.1f%%",
                 thresh, len(cands), s["n"], s["profit_factor"], s["win_rate"], s["annualized_pct"])

    # ── Monthly equity curve ──────────────────────────────────────────────
    equity_curve    = _monthly_equity(trades)
    exit_breakdown  = _exit_reason_breakdown(trades)

    # ── Verdict ───────────────────────────────────────────────────────────
    verdict_label, verdict_reasons = _verdict(main_stats, spy, sensitivity, exit_breakdown)

    # ── Write report ──────────────────────────────────────────────────────
    report_path = _write_report(
        main_stats, spy, sensitivity, equity_curve,
        exit_breakdown, verdict_label, verdict_reasons,
        len(candidates), n_earnings_total, run_date,
    )

    print(f"\n{'=' * 64}")
    print(f"  PEAD BACKTEST COMPLETE")
    print(f"{'=' * 64}")
    print(f"  Earnings events:   {n_earnings_total}")
    print(f"  Candidates:        {len(candidates)}")
    print(f"  Trades:            {main_stats['n']}")
    print(f"  Win rate:          {main_stats['win_rate']:.1f}%")
    print(f"  Profit factor:     {main_stats['profit_factor']:.2f}x")
    print(f"  Annualised:        {main_stats['annualized_pct']:+.1f}%")
    print(f"  P(hard kill):      {main_stats['p_hard_kill']:.1f}%")
    if spy:
        print(f"  SPY (same window): {spy['total_return_pct']:+.1f}%")
    print(f"  Verdict:           {verdict_label}")
    print(f"  Report:            {report_path}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
