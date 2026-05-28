#!/usr/bin/env python3
"""Fetch current market prices and write live JSON to docs/data/.

No trading, no broker, no position mutations.
Runs every 15 min during US market hours (see run_dashboard_live_refresh.sh).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_AGENT = Path(__file__).resolve().parent.parent
_DOCS_DATA = _AGENT / "docs" / "data"
_DOCS_DATA.mkdir(parents=True, exist_ok=True)

_SCAI_POSITIONS = (
    Path.home() / "trading" / "scai_lab" / "data" / "paper"
    / "structural_paper_positions.jsonl"
)
_HERMES_POSITIONS = (
    Path.home() / "trading" / "hermes_lab" / "data" / "paper" / "positions.jsonl"
)
_ATS_POSITIONS = _AGENT / "data" / "paper_positions.yaml"
_HERMES_V3_VARIANTS_DIR = Path.home() / "trading" / "hermes_v3_lab" / "data" / "variants"

_ALWAYS_FETCH = ["SPY", "QQQ", "SMH"]


# ─── Time helpers ──────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _uk_time_str(utc_dt: datetime) -> str:
    month = utc_dt.month
    offset = 1 if 3 <= month <= 10 else 0
    uk_dt = utc_dt + timedelta(hours=offset)
    tz_name = "BST" if offset else "GMT"
    return uk_dt.strftime("%Y-%m-%d %H:%M") + " " + tz_name


def _market_status(utc_dt: datetime) -> tuple[str, str]:
    """Returns (status, note). Status: open|closed|pre_market|after_hours."""
    month = utc_dt.month
    et_offset = -4 if 3 <= month <= 11 else -5
    et = utc_dt + timedelta(hours=et_offset)
    wd = et.weekday()  # 0=Mon, 6=Sun
    t = et.hour + et.minute / 60

    if wd >= 5:
        return "closed", "Weekend"
    if t < 4:
        return "closed", "US market closed"
    if t < 9.5:
        return "pre_market", "US pre-market"
    if t < 16:
        return "open", "US market open"
    if t < 20:
        return "after_hours", "US after-hours"
    return "closed", "US market closed"


def _is_stale(last_data_date: date, utc_now: datetime) -> bool:
    """True if newest data is >2 trading days old."""
    today = utc_now.date()
    delta = (today - last_data_date).days
    # Allow weekends: Friday data is valid Mon/Tue
    return delta > 4


# ─── Position readers ─────────────────────────────────────────────────────────

def _read_ats() -> list[dict]:
    if not _ATS_POSITIONS.exists():
        return []
    try:
        import yaml
        raw = yaml.safe_load(_ATS_POSITIONS.read_text())
        rows = raw.get("positions", raw) if isinstance(raw, dict) else raw
        return rows or []
    except Exception:
        return []


def _read_jsonl_deduped(path: Path) -> list[dict]:
    if not path.exists():
        return []
    seen: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            key = rec.get("paper_id") or rec.get("basket_name") or rec.get("cluster_name", "")
            seen[key] = rec
        except json.JSONDecodeError:
            pass
    return list(seen.values())


def _read_scai() -> list[dict]:
    rows = _read_jsonl_deduped(_SCAI_POSITIONS)
    return [r for r in rows if r.get("status") == "open"]


def _read_hermes() -> list[dict]:
    rows = _read_jsonl_deduped(_HERMES_POSITIONS)
    return [r for r in rows if r.get("status") == "open"]


# ─── Price fetcher ─────────────────────────────────────────────────────────────

def _fetch_prices(tickers: list[str]) -> tuple[dict[str, dict], bool]:
    """
    Returns ({ticker: {last_price, prev_close, last_data_date}}, had_error).
    Uses fast_info for current price + prev_close per ticker.
    Falls back to 5d history download if fast_info unavailable.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  ERROR: yfinance not installed", file=sys.stderr)
        return {}, True

    result: dict[str, dict] = {}
    unique = sorted(set(tickers))

    # Primary: fast_info (most current, one call per ticker but fast)
    errors: list[str] = []
    for t in unique:
        try:
            fi = yf.Ticker(t).fast_info
            lp = fi.get("lastPrice")
            pc = fi.get("previousClose")
            if lp and lp == lp:  # not NaN
                result[t] = {
                    "last_price": round(float(lp), 4),
                    "prev_close": round(float(pc), 4) if pc and pc == pc else round(float(lp), 4),
                    "last_data_date": _now_utc().date().isoformat(),
                }
        except Exception as e:
            errors.append(t)

    # Fallback: batch history download for any that failed
    missing = [t for t in unique if t not in result]
    if missing:
        try:
            import yfinance as yf
            df = yf.download(
                missing if len(missing) > 1 else missing + ["SPY"],
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if not df.empty and "Close" in df.columns.get_level_values(0):
                close = df["Close"]
                for t in missing:
                    try:
                        s = close[t].dropna() if t in close.columns else None
                        if s is None or s.empty:
                            continue
                        lp = float(s.iloc[-1])
                        pc = float(s.iloc[-2]) if len(s) >= 2 else lp
                        last_dt = s.index[-1].date().isoformat()
                        result[t] = {
                            "last_price": round(lp, 4),
                            "prev_close": round(pc, 4),
                            "last_data_date": last_dt,
                        }
                    except Exception:
                        pass
        except Exception:
            pass

    had_error = len([t for t in unique if t not in result]) > 0
    return result, had_error


def _hist_entry_price(ticker: str, entry_date_str: str) -> float | None:
    """
    Return the benchmark price to use as the entry baseline.

    For same-day entries (entry_date == today): today's close hasn't happened yet,
    so we use previousClose (yesterday's confirmed close). This prevents the bug
    where both entry and current price reference the same intraday tick → 0.0%.

    For historical entries: find the closest confirmed daily close on or after
    entry_date, falling back to the closest close before it.
    """
    today = _now_utc().date()
    try:
        import yfinance as yf
        import pandas as pd
        entry_dt = pd.Timestamp(entry_date_str).date()
    except Exception:
        return None

    # Same-day (or future) entry: use previousClose as baseline
    if entry_dt >= today:
        try:
            fi = yf.Ticker(ticker).fast_info
            pc = fi.get("previousClose")
            if pc and pc == pc:  # guard against NaN
                return round(float(pc), 4)
        except Exception:
            pass
        return None

    # Historical entry: find closest confirmed close
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=True)
        if hist.empty:
            return None

        best_after: tuple[int, float] | None = None
        best_before: tuple[int, float] | None = None

        for idx, row in hist.iterrows():
            idx_date = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()
            price = float(row["Close"])
            diff = (idx_date - entry_dt).days
            if diff >= 0:
                if best_after is None or diff < best_after[0]:
                    best_after = (diff, price)
            else:
                abs_diff = abs(diff)
                if best_before is None or abs_diff < best_before[0]:
                    best_before = (abs_diff, price)

        if best_after is not None:
            return round(best_after[1], 4)
        if best_before is not None:
            return round(best_before[1], 4)
        return None
    except Exception:
        return None


# ─── Per-system JSON builders ──────────────────────────────────────────────────

def _build_ats_json(positions: list[dict], prices: dict[str, dict], now: datetime) -> dict:
    status, note = _market_status(now)
    pos_out = []
    returns = []
    day_changes = []

    for p in positions:
        t = p.get("ticker", "")
        entry_price = float(p.get("entry_price", 0) or 0)
        spy_entry = float(p.get("spy_entry_price", 0) or 0)
        pd_ = prices.get(t, {})
        lp = pd_.get("last_price")
        pc = pd_.get("prev_close")
        stale = False

        if lp and entry_price > 0:
            ret = round((lp - entry_price) / entry_price * 100, 3)
            returns.append(ret)
        else:
            ret = None
            stale = True

        if lp and pc and pc > 0:
            day_chg = round((lp - pc) / pc * 100, 3)
            day_changes.append(day_chg)
        else:
            day_chg = None

        pos_out.append({
            "ticker": t,
            "entry_date": p.get("entry_date", ""),
            "entry_price": entry_price,
            "spy_entry_price": spy_entry,
            "last_price": lp,
            "prev_close": pc,
            "day_change_pct": day_chg,
            "return_pct": ret,
            "stale": stale,
        })

    port_return = round(sum(returns) / len(returns), 3) if returns else None
    port_today = round(sum(day_changes) / len(day_changes), 3) if day_changes else None

    spy_prices = prices.get("SPY", {})
    spy_lp = spy_prices.get("last_price")
    spy_pc = spy_prices.get("prev_close")
    # ATS positions all share the same SPY entry price
    spy_entry_common = float(positions[0].get("spy_entry_price", 745.64)) if positions else 745.64
    spy_return = round((spy_lp - spy_entry_common) / spy_entry_common * 100, 3) if spy_lp and spy_entry_common > 0 else None
    spy_today = round((spy_lp - spy_pc) / spy_pc * 100, 3) if spy_lp and spy_pc and spy_pc > 0 else None
    alpha = round(port_return - spy_return, 3) if port_return is not None and spy_return is not None else None

    return {
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_uk": _uk_time_str(now),
        "market_status": status,
        "market_note": note,
        "delay_warning": "Prices may be 15-min delayed (yfinance)",
        "positions": pos_out,
        "portfolio_return_pct": port_return,
        "portfolio_today_pct": port_today,
        "spy_entry_price": spy_entry_common,
        "spy_last_price": spy_lp,
        "spy_return_pct": spy_return,
        "spy_today_pct": spy_today,
        "alpha_vs_spy_pct": alpha,
        "n_positions": len(positions),
        "n_priced": len(returns),
        "source": "yfinance",
        "stale_warning": len(returns) < len(positions),
        "error": None,
    }


def _build_basket_json(
    basket: dict,
    prices: dict[str, dict],
    now: datetime,
    sys_name: str,
    spy_entry_price: "float | None" = None,
    spy_baseline_status: str = "unavailable",
) -> dict:
    tickers: list[str] = basket.get("tickers", [])
    weights: dict[str, float] = basket.get("weights", {})
    entry_prices: dict[str, float] = {k: float(v) for k, v in basket.get("entry_prices", {}).items()}
    benchmark = basket.get("benchmark", "QQQ")
    entry_date = basket.get("entry_price_fill_date") or basket.get("entry_date") or basket.get("created_at", "")[:10]

    if not weights:
        w = 1.0 / len(tickers) if tickers else 1.0
        weights = {t: w for t in tickers}

    ticker_rows: dict[str, dict] = {}
    basket_return = 0.0
    basket_today = 0.0
    n_priced = 0

    for t in tickers:
        ep = entry_prices.get(t, 0)
        pd_ = prices.get(t, {})
        lp = pd_.get("last_price")
        pc = pd_.get("prev_close")
        w = weights.get(t, 1.0 / len(tickers))

        ret = round((lp - ep) / ep * 100, 3) if lp and ep > 0 else None
        day_chg = round((lp - pc) / pc * 100, 3) if lp and pc and pc > 0 else None

        ticker_rows[t] = {
            "last_price": lp,
            "prev_close": pc,
            "day_change_pct": day_chg,
            "return_pct": ret,
        }

        if ret is not None:
            basket_return += w * ret
            n_priced += 1
        if day_chg is not None:
            basket_today += w * day_chg

    # Benchmark return
    bm_prices = prices.get(benchmark, {})
    bm_lp = bm_prices.get("last_price")
    bm_pc = bm_prices.get("prev_close")

    # Look up benchmark entry price from history
    bm_entry = _hist_entry_price(benchmark, entry_date) if entry_date else None
    bm_return = round((bm_lp - bm_entry) / bm_entry * 100, 3) if bm_lp and bm_entry and bm_entry > 0 else None
    bm_today = round((bm_lp - bm_pc) / bm_pc * 100, 3) if bm_lp and bm_pc and bm_pc > 0 else None
    alpha = round(basket_return - bm_return, 3) if n_priced == len(tickers) and bm_return is not None else None

    # SPY comparison since entry
    spy_prices = prices.get("SPY", {})
    spy_lp = spy_prices.get("last_price")
    spy_pc = spy_prices.get("prev_close")
    spy_ret = (
        round((spy_lp - spy_entry_price) / spy_entry_price * 100, 3)
        if spy_lp and spy_entry_price and spy_entry_price > 0
        else None
    )
    spy_today_v = (
        round((spy_lp - spy_pc) / spy_pc * 100, 3)
        if spy_lp and spy_pc and spy_pc > 0
        else None
    )
    alpha_spy = (
        round(basket_return - spy_ret, 3)
        if n_priced == len(tickers) and spy_ret is not None
        else None
    )

    spy_baseline_reason = (
        "entry is today; using previous close as baseline" if spy_baseline_status == "same_day_estimated"
        else ("" if spy_baseline_status == "ok" else "SPY entry price unavailable")
    )

    return {
        "paper_id": basket.get("paper_id", ""),
        "basket_name": basket.get("basket_name", ""),
        "tickers": tickers,
        "entry_prices": entry_prices,
        "entry_date": entry_date,
        "last_prices": {t: ticker_rows[t]["last_price"] for t in tickers},
        "prev_closes": {t: ticker_rows[t]["prev_close"] for t in tickers},
        "day_changes": {t: ticker_rows[t]["day_change_pct"] for t in tickers},
        "returns": {t: ticker_rows[t]["return_pct"] for t in tickers},
        "basket_return_pct": round(basket_return, 3) if n_priced > 0 else None,
        "basket_today_pct": round(basket_today, 3) if n_priced > 0 else None,
        "benchmark": benchmark,
        "benchmark_entry_price": bm_entry,
        "benchmark_last_price": bm_lp,
        "benchmark_return_pct": bm_return,
        "benchmark_today_pct": bm_today,
        "alpha_vs_benchmark_pct": alpha,
        "spy_entry_date": entry_date,
        "spy_entry_price": spy_entry_price,
        "spy_latest_price": spy_lp,
        "spy_last_price": spy_lp,
        "spy_return_pct": spy_ret,
        "spy_today_pct": spy_today_v,
        "alpha_vs_spy_pct": alpha_spy,
        "spy_baseline_status": spy_baseline_status,
        "spy_baseline_reason": spy_baseline_reason,
        "n_priced": n_priced,
        "stale": n_priced < len(tickers),
    }


def _build_lab_json(
    positions: list[dict],
    prices: dict[str, dict],
    now: datetime,
    sys_name: str,
) -> dict:
    status, note = _market_status(now)

    # Pre-compute SPY entry prices per unique basket entry date (one API call per date)
    unique_dates: set[str] = set()
    for b in positions:
        ed = b.get("entry_price_fill_date") or b.get("entry_date") or b.get("created_at", "")[:10]
        if ed:
            unique_dates.add(ed)
    spy_by_date: dict[str, "float | None"] = {ed: _hist_entry_price("SPY", ed) for ed in unique_dates}

    today_str = now.date().isoformat()
    spy_status_by_date: dict[str, str] = {}
    for ed in unique_dates:
        price = spy_by_date.get(ed)
        if price is None:
            spy_status_by_date[ed] = "unavailable"
        elif ed >= today_str:
            spy_status_by_date[ed] = "same_day_estimated"
        else:
            spy_status_by_date[ed] = "ok"

    baskets = []
    for b in positions:
        ed = b.get("entry_price_fill_date") or b.get("entry_date") or b.get("created_at", "")[:10]
        spy_ep = spy_by_date.get(ed) if ed else None
        spy_status = spy_status_by_date.get(ed, "unavailable") if ed else "unavailable"
        baskets.append(_build_basket_json(b, prices, now, sys_name, spy_entry_price=spy_ep, spy_baseline_status=spy_status))

    returns = [b["basket_return_pct"] for b in baskets if b["basket_return_pct"] is not None]
    todays = [b["basket_today_pct"] for b in baskets if b["basket_today_pct"] is not None]
    spy_rets = [b["spy_return_pct"] for b in baskets if b.get("spy_return_pct") is not None]

    spy_prices = prices.get("SPY", {})
    spy_lp = spy_prices.get("last_price")
    spy_pc = spy_prices.get("prev_close")
    spy_today_pct = (
        round((spy_lp - spy_pc) / spy_pc * 100, 3)
        if spy_lp and spy_pc and spy_pc > 0
        else None
    )
    spy_return_avg = round(sum(spy_rets) / len(spy_rets), 3) if spy_rets else None
    port_ret = round(sum(returns) / len(returns), 3) if returns else None
    alpha_spy = (
        round(port_ret - spy_return_avg, 3)
        if port_ret is not None and spy_return_avg is not None
        else None
    )

    earliest_entry_date = min(unique_dates) if unique_dates else None
    spy_baseline_statuses = list(spy_status_by_date.values())
    top_spy_status = (
        "ok" if all(s == "ok" for s in spy_baseline_statuses)
        else "same_day_estimated" if any(s == "same_day_estimated" for s in spy_baseline_statuses)
        else "unavailable"
    ) if spy_baseline_statuses else "unavailable"

    return {
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_uk": _uk_time_str(now),
        "market_status": status,
        "market_note": note,
        "delay_warning": "Prices may be 15-min delayed (yfinance)",
        "baskets": baskets,
        "portfolio_return_pct": port_ret,
        "portfolio_today_pct": round(sum(todays) / len(todays), 3) if todays else None,
        "spy_entry_date": earliest_entry_date,
        "spy_return_pct": spy_return_avg,
        "spy_today_pct": spy_today_pct,
        "alpha_vs_spy_pct": alpha_spy,
        "spy_baseline_status": top_spy_status,
        "n_baskets": len(positions),
        "n_priced": len(returns),
        "source": "yfinance",
        "stale_warning": len(returns) < len(positions),
        "error": None,
    }


def _read_hermes_v3_open_positions() -> list[dict]:
    """Read all open positions across Hermes v3 variants (read-only)."""
    if not _HERMES_V3_VARIANTS_DIR.exists():
        return []
    positions = []
    for f in sorted(_HERMES_V3_VARIANTS_DIR.glob("*_positions.jsonl")):
        if f.name == "variant_summary.json":
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("is_open"):
                    positions.append(rec)
            except json.JSONDecodeError:
                pass
    return positions


def _build_hermes_v3_json(
    open_positions: list[dict],
    prices: dict[str, dict],
    now: datetime,
) -> dict:
    status, note = _market_status(now)

    # Load variant summary for current pots/returns
    summary_file = _HERMES_V3_VARIANTS_DIR / "variant_summary.json"
    variant_summary: list[dict] = []
    if summary_file.exists():
        try:
            variant_summary = json.loads(summary_file.read_text())["variants"]
        except Exception:
            pass

    # Build positions by variant
    by_variant: dict[str, list[dict]] = {}
    for pos in open_positions:
        vid = pos.get("variant_id", "unknown")
        by_variant.setdefault(vid, []).append(pos)

    spy_prices = prices.get("SPY", {})
    spy_lp = spy_prices.get("last_price")
    spy_pc = spy_prices.get("prev_close")
    spy_today = round((spy_lp - spy_pc) / spy_pc * 100, 3) if spy_lp and spy_pc and spy_pc > 0 else None
    qqq_prices = prices.get("QQQ", {})
    qqq_lp = qqq_prices.get("last_price")

    variants_out = []
    for vs in variant_summary:
        vid = vs["variant_id"]
        pot = vs.get("current_pot", 5000.0)
        ret = vs.get("net_return_pct", 0.0)
        starting = 5000.0

        # Attach live position data
        pos_list = []
        for pos in by_variant.get(vid, []):
            ticker = pos["ticker"]
            entry = pos.get("entry_price_net", pos.get("entry_price_raw"))
            pd_ = prices.get(ticker, {})
            lp = pd_.get("last_price")
            shares = pos.get("shares", 0)
            unrealised = round((lp - entry) * shares, 2) if lp and entry and shares else None
            pos_return = round((lp - entry) / entry * 100, 3) if lp and entry and entry > 0 else None
            pos_list.append({
                "ticker": ticker,
                "entry_price": entry,
                "last_price": lp,
                "return_pct": pos_return,
                "unrealised_pnl": unrealised,
            })

        # SPY alpha since inception of variant
        spy_return_pct = vs.get("spy_return_pct")
        alpha = round(ret - spy_return_pct, 3) if ret is not None and spy_return_pct is not None else None

        variants_out.append({
            "variant_id": vid,
            "starting_pot": starting,
            "current_pot": pot,
            "net_return_pct": ret,
            "net_dollar_pnl": round(pot - starting, 2),
            "spy_return_pct": spy_return_pct,
            "alpha_vs_spy_pct": alpha,
            "open_positions": vs.get("open_positions", 0),
            "closed_trades": vs.get("closed_trades", 0),
            "positions": pos_list,
        })

    # Best/worst variants
    ranked = sorted(variants_out, key=lambda v: v["net_return_pct"] or 0, reverse=True)
    best = ranked[0] if ranked else None
    worst = ranked[-1] if ranked else None

    return {
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_uk": _uk_time_str(now),
        "market_status": status,
        "market_note": note,
        "delay_warning": "Prices may be 15-min delayed (yfinance)",
        "spy_return_pct": None,
        "spy_today_pct": spy_today,
        "qqq_return_pct": None,
        "best_variant_id": best["variant_id"] if best else None,
        "best_variant_return_pct": best["net_return_pct"] if best else None,
        "worst_variant_id": worst["variant_id"] if worst else None,
        "worst_variant_return_pct": worst["net_return_pct"] if worst else None,
        "variants": variants_out,
        "n_variants": len(variants_out),
        "source": "yfinance",
        "error": None,
    }


def _build_summary_json(
    ats_j: dict,
    scai_j: dict,
    hermes_j: dict,
    now: datetime,
) -> dict:
    status, note = _market_status(now)
    return {
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_uk": _uk_time_str(now),
        "market_status": status,
        "market_note": note,
        "systems": {
            "ats": {
                "portfolio_return_pct": ats_j.get("portfolio_return_pct"),
                "portfolio_today_pct": ats_j.get("portfolio_today_pct"),
                "alpha_vs_spy_pct": ats_j.get("alpha_vs_spy_pct"),
                "n_positions": ats_j.get("n_positions"),
            },
            "scai": {
                "portfolio_return_pct": scai_j.get("portfolio_return_pct"),
                "portfolio_today_pct": scai_j.get("portfolio_today_pct"),
                "spy_return_pct": scai_j.get("spy_return_pct"),
                "alpha_vs_spy_pct": scai_j.get("alpha_vs_spy_pct"),
                "n_baskets": scai_j.get("n_baskets"),
            },
            "hermes": {
                "portfolio_return_pct": hermes_j.get("portfolio_return_pct"),
                "portfolio_today_pct": hermes_j.get("portfolio_today_pct"),
                "spy_return_pct": hermes_j.get("spy_return_pct"),
                "alpha_vs_spy_pct": hermes_j.get("alpha_vs_spy_pct"),
                "n_baskets": hermes_j.get("n_baskets"),
            },
        },
    }


def _build_summary_json_v2(
    ats_j: dict,
    scai_j: dict,
    hermes_j: dict,
    hermes_v3_j: dict,
    now: datetime,
) -> dict:
    base = _build_summary_json(ats_j, scai_j, hermes_j, now)
    base["systems"]["hermes_v3"] = {
        "best_variant_id": hermes_v3_j.get("best_variant_id"),
        "best_variant_return_pct": hermes_v3_j.get("best_variant_return_pct"),
        "worst_variant_return_pct": hermes_v3_j.get("worst_variant_return_pct"),
        "n_variants": hermes_v3_j.get("n_variants"),
    }
    return base


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    now = _now_utc()
    print(f"[live-prices] {now.strftime('%Y-%m-%dT%H:%M:%SZ')}", file=sys.stderr)

    ats_pos = _read_ats()
    scai_pos = _read_scai()
    hermes_pos = _read_hermes()
    hermes_v3_pos = _read_hermes_v3_open_positions()

    print(f"  ATS: {len(ats_pos)} positions", file=sys.stderr)
    print(f"  SCAI: {len(scai_pos)} baskets", file=sys.stderr)
    print(f"  Hermes: {len(hermes_pos)} baskets", file=sys.stderr)
    print(f"  Hermes v3: {len(hermes_v3_pos)} open positions across variants", file=sys.stderr)

    # Collect all tickers
    ats_tickers = [p["ticker"] for p in ats_pos if "ticker" in p]
    lab_tickers: list[str] = []
    for b in scai_pos + hermes_pos:
        lab_tickers.extend(b.get("tickers", []))
    v3_tickers = [p["ticker"] for p in hermes_v3_pos if "ticker" in p]
    benchmarks = list({b.get("benchmark", "QQQ") for b in scai_pos + hermes_pos}) + _ALWAYS_FETCH
    all_tickers = list(set(ats_tickers + lab_tickers + v3_tickers + benchmarks))

    print(f"  Fetching {len(all_tickers)} tickers...", file=sys.stderr)
    prices, had_error = _fetch_prices(all_tickers)
    n_priced = len(prices)
    print(f"  Got prices for {n_priced}/{len(all_tickers)}", file=sys.stderr)
    if had_error:
        print("  WARNING: some tickers failed to price", file=sys.stderr)

    ats_j = _build_ats_json(ats_pos, prices, now)
    scai_j = _build_lab_json(scai_pos, prices, now, "scai")
    hermes_j = _build_lab_json(hermes_pos, prices, now, "hermes")
    hermes_v3_j = _build_hermes_v3_json(hermes_v3_pos, prices, now)
    summary_j = _build_summary_json_v2(ats_j, scai_j, hermes_j, hermes_v3_j, now)

    files = {
        "ats_live.json": ats_j,
        "scai_live.json": scai_j,
        "hermes_live.json": hermes_j,
        "hermes_v3_live.json": hermes_v3_j,
        "system_summary_live.json": summary_j,
    }
    for fname, data in files.items():
        out = _DOCS_DATA / fname
        new_priced = data.get("n_priced", 0) or 0
        if new_priced == 0 and out.exists():
            try:
                existing = json.loads(out.read_text())
                if (existing.get("n_priced") or 0) > 0:
                    print(f"  Skipped {fname} (new n_priced=0, keeping last good data)", file=sys.stderr)
                    continue
            except Exception:
                pass
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"  Wrote {out}", file=sys.stderr)

    print(
        f"  portfolio={ats_j.get('portfolio_return_pct')}% "
        f"SPY={ats_j.get('spy_return_pct')}% "
        f"alpha={ats_j.get('alpha_vs_spy_pct')}%",
        file=sys.stderr,
    )
    print("[live-prices] done", file=sys.stderr)
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
