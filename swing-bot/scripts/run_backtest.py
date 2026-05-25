#!/usr/bin/env python3
"""Swing Bot v1 — Historical Backtest + Monte Carlo Overlay

Usage:
  python run_backtest.py [--no-haiku] [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Pipeline:
  1. Load watchlist, build CIK map
  2. Fetch all 8-K filings per ticker via EDGAR submissions API (cached)
  3. Filter to backtest date range
  4. Pre-filter: item codes → 7.01/5.02 price-move gates → price floor → delisting
  5. Haiku classification for survivors (£15 hard cap, progressive cost output)
  6. Entry rules: momentum ≥3%, 5d trend ≥-1%, liquidity ≥$6.35M
  7. Exit simulation: profit target +10%, stop loss -5%, time exit 10 days
  8. Portfolio concurrency: max 10 simultaneous positions
  9. Monte Carlo: 10,000 bootstrap iterations
  10. Report: markdown + JSONL trade log

Hard rules unchanged:
  - place_real_order() not called (no orders possible in backtest)
  - All data reads from swing-bot/data/backtest_cache/
  - No cross-imports from agent/src/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import statistics
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import yaml

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# ── Constants ──────────────────────────────────────────────────────────────────
BACKTEST_START = "2024-01-01"
BACKTEST_END   = "2025-12-31"
HIST_START     = "2023-11-01"   # 60-day pre-window for 5-day trend + volume calcs
HIST_END       = "2026-05-26"   # inclusive of today for delisting check

POSITION_SIZE_GBP    = 50.0
MAX_POSITIONS        = 10
PORTFOLIO_START_GBP  = 500.0
GBPUSD               = 1.27
PRICE_FLOOR_USD      = 5.0 * GBPUSD     # £5 ≈ $6.35
MIN_PRICE_CHANGE_PCT = 3.0
MIN_LIQUIDITY_USD    = 6_350_000
TREND_FLOOR_PCT      = -1.0
PROFIT_TARGET_PCT    = 10.0
STOP_LOSS_PCT        = -5.0
MAX_HOLD_DAYS        = 10
DELISTING_WINDOW_DAYS = 60

HAIKU_COST_CAP_GBP          = 15.0
HAIKU_COST_PER_1K_INPUT_USD = 0.0008
HAIKU_COST_PER_1K_OUTPUT_USD= 0.004
HAIKU_MODEL                 = "claude-haiku-4-5-20251001"
MAX_FILING_CHARS            = 1000
HAIKU_MIN_CONFIDENCE        = 0.6

N_MC_SIMS = 10_000

EDGAR_IDENTITY = "Jack Gardiner jackgardiner050@gmail.com"

# ── Paths ──────────────────────────────────────────────────────────────────────
_CACHE_DIR   = _ROOT / "data" / "backtest_cache"
_CIK_CACHE   = _ROOT / "data" / "cik_map_cache.json"
_OUTPUT_DIR  = _ROOT / "reports"           # markdown reports (committed to git)
_DATA_DIR    = _ROOT / "data" / "backtest" # JSONL trade log (gitignored)

# ── Globals (cost tracking) ────────────────────────────────────────────────────
_haiku_cost_gbp: float = 0.0
_haiku_calls: int = 0

log = logging.getLogger("backtest")


# ── .env loader ───────────────────────────────────────────────────────────────
def _load_env() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# ── EDGAR helpers ─────────────────────────────────────────────────────────────
def _headers() -> dict:
    return {"User-Agent": EDGAR_IDENTITY, "Accept-Encoding": "gzip, deflate"}


def _load_tickers() -> list[str]:
    wl_path = _ROOT / "config" / "watchlist.yaml"
    with open(wl_path) as f:
        wl = yaml.safe_load(f) or {}
    tickers: list[str] = []
    for tier in ("tier1", "tier2"):
        tickers.extend(wl.get(tier, []))
    return list(dict.fromkeys(tickers))


def _load_cik_map() -> dict[str, int]:
    if _CIK_CACHE.exists():
        age = (datetime.now() - datetime.fromtimestamp(_CIK_CACHE.stat().st_mtime)).days
        if age < 7:
            with open(_CIK_CACHE) as f:
                return {k: int(v) for k, v in json.load(f).items()}
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    raw = resp.json()
    cik_map = {
        e["ticker"].upper(): int(e["cik_str"])
        for e in raw.values()
        if "ticker" in e and "cik_str" in e
    }
    _CIK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(_CIK_CACHE, "w") as f:
        json.dump(cik_map, f)
    return cik_map


def _fetch_ticker_8ks(ticker: str, cik: int) -> list[dict]:
    """Fetch 8-K filings for one ticker from EDGAR submissions API. Cached 3 days."""
    cache_file = _CACHE_DIR / "edgar" / f"{ticker}.json"
    if cache_file.exists():
        age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
        if age < 3:
            with open(cache_file) as f:
                return json.load(f)

    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("EDGAR fetch failed %s (CIK %d): %s", ticker, cik, exc)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms       = recent.get("form", [])
    dates       = recent.get("filingDate", [])
    accessions  = recent.get("accessionNumber", [])
    items_list  = recent.get("items", [])

    result: list[dict] = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        filed = dates[i] if i < len(dates) else ""
        if not filed:
            continue
        acc       = accessions[i] if i < len(accessions) else ""
        raw_items = items_list[i] if i < len(items_list) else ""
        items     = [x.strip() for x in raw_items.split(",") if x.strip()]
        result.append({
            "ticker":     ticker,
            "cik":        cik,
            "accession":  acc,
            "filed_date": filed,
            "items":      items,
        })

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(result, f)
    time.sleep(0.12)   # EDGAR courtesy pause
    return result


# ── Price cache ───────────────────────────────────────────────────────────────
def _load_price_cache(tickers: list[str]) -> dict:
    """Batch-download 2+ years of OHLCV for all tickers. Per-ticker CSV cache, 7-day TTL."""
    import pandas as pd
    import yfinance as yf

    price_dir = _CACHE_DIR / "prices"
    price_dir.mkdir(parents=True, exist_ok=True)

    all_hist: dict[str, pd.DataFrame] = {}
    to_fetch: list[str] = []

    for ticker in tickers:
        cf = price_dir / f"{ticker}.csv"
        if cf.exists():
            age = (datetime.now() - datetime.fromtimestamp(cf.stat().st_mtime)).days
            if age < 7:
                try:
                    df = pd.read_csv(cf, index_col=0, parse_dates=True)
                    if not df.empty:
                        all_hist[ticker] = df
                        continue
                except Exception:
                    pass
        to_fetch.append(ticker)

    if to_fetch:
        log.info("Downloading yfinance history for %d tickers (batches of 50)...", len(to_fetch))
        for i in range(0, len(to_fetch), 50):
            batch = to_fetch[i : i + 50]
            try:
                raw = yf.download(
                    batch, start=HIST_START, end=HIST_END,
                    auto_adjust=True, progress=False, threads=True,
                )
                if raw is None or raw.empty:
                    continue

                if len(batch) == 1:
                    ticker = batch[0]
                    raw.index = pd.to_datetime(raw.index)
                    raw.to_csv(price_dir / f"{ticker}.csv")
                    all_hist[ticker] = raw
                else:
                    for ticker in batch:
                        try:
                            if isinstance(raw.columns, pd.MultiIndex):
                                tdf = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                            else:
                                tdf = raw[[ticker]].dropna(how="all")
                            if not tdf.empty:
                                tdf.to_csv(price_dir / f"{ticker}.csv")
                                all_hist[ticker] = tdf
                        except KeyError:
                            pass
            except Exception as exc:
                log.warning("Batch download failed (i=%d): %s", i, exc)
            time.sleep(0.5)

    log.info("Price cache ready: %d / %d tickers", len(all_hist), len(tickers))
    return all_hist


# ── Day-data lookup ───────────────────────────────────────────────────────────
def _get_day_data(df, filing_date: str) -> dict:
    """Return price/volume/trend data on the filing date or nearest next trading day."""
    import pandas as pd

    target = pd.Timestamp(filing_date)
    for delta in range(4):
        dt = (target + pd.Timedelta(days=delta)).normalize()
        mask = df.index.normalize() == dt
        rows = df[mask]
        if rows.empty:
            continue
        row   = rows.iloc[-1]
        close = float(row.get("Close", 0) or 0)
        open_ = float(row.get("Open", close) or close)
        if close <= 0:
            continue

        pct_change = (close - open_) / open_ * 100 if open_ > 0 else 0.0

        before = df[df.index < rows.index[0]].tail(30)
        avg_vol   = float(before["Volume"].mean()) if not before.empty else 0.0
        avg_price = float(before["Close"].mean()) if not before.empty else close
        avg_vol_usd = avg_vol * avg_price

        five_back = df[df.index < rows.index[0]].tail(6)
        if len(five_back) >= 5:
            price_5d_ago = float(five_back.iloc[0]["Close"])
            trend_5d = (close - price_5d_ago) / price_5d_ago * 100 if price_5d_ago > 0 else 0.0
        else:
            trend_5d = 0.0

        return {
            "close":            close,
            "price_change_pct": round(pct_change, 2),
            "trend_5d_pct":     round(trend_5d, 2),
            "avg_daily_vol_usd":round(avg_vol_usd, 0),
            "actual_date":      rows.index[0].date().isoformat(),
        }
    return {}


def _is_delisted_within_60d(df, filing_date: str) -> bool:
    """Return True if last price data is < 60 days after filing (probable delisting)."""
    import pandas as pd

    if df is None or df.empty:
        return True
    filing_dt = pd.Timestamp(filing_date).normalize()
    cutoff    = filing_dt + pd.Timedelta(days=DELISTING_WINDOW_DAYS)
    today     = pd.Timestamp.now().normalize()
    if cutoff > today:
        return False   # window hasn't elapsed — can't know
    post = df[df.index.normalize() >= filing_dt]
    if post.empty:
        return True
    return post.index[-1].normalize() < cutoff


# ── Pre-filter ────────────────────────────────────────────────────────────────
def prefilter_8k(items: list[str], same_day_pct: float) -> tuple[bool, str]:
    """
    Returns (passes, skip_reason).

    Allowed triggers (in priority order):
      1.01, 2.01, 8.01  — always pass, no price confirmation needed
      7.01               — pass only if same_day_pct >= 3%
      5.02               — pass only if same_day_pct >= 5%
    All other item codes are ignored.
    """
    item_set      = set(items)
    high_priority = bool(item_set & {"1.01", "2.01"})
    has_8_01      = "8.01" in item_set
    has_7_01      = "7.01" in item_set
    has_5_02      = "5.02" in item_set

    if high_priority or has_8_01:
        return True, ""

    if has_7_01:
        if same_day_pct >= 3.0:
            return True, ""
        return False, f"7.01_no_move({same_day_pct:.1f}%)"

    if has_5_02:
        if same_day_pct >= 5.0:
            return True, ""
        return False, f"5.02_no_move({same_day_pct:.1f}%)"

    return False, "no_allowed_items"


# ── Filing text fetch (cached) ────────────────────────────────────────────────
def _fetch_filing_text(cik: int, accession: str) -> str:
    acc_nodash = accession.replace("-", "")
    cache_file = _CACHE_DIR / "texts" / f"{acc_nodash}.txt"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="replace")[:MAX_FILING_CHARS]
    try:
        url  = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc_nodash}-index.htm"
        resp = requests.get(url, headers=_headers(), timeout=15)
        text = resp.text.replace("\x00", " ")[:MAX_FILING_CHARS]
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8", errors="replace")
        time.sleep(0.12)
        return text
    except Exception:
        return ""


# ── Haiku classifier ──────────────────────────────────────────────────────────
_HAIKU_SYSTEM = (
    "You are a financial document classifier. "
    "Respond with ONLY a valid JSON object. Do NOT use markdown code fences. No other text.\n"
    '{"category":"M&A"|"FDA"|"earnings"|"executive_change"|"Reg_FD"|"other",'
    '"material":true|false,"confidence":0.0-1.0}\n'
    "material=true means this event is likely to move the stock ≥2%."
)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that LLMs sometimes add despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        if "\n" in text:
            text = text.split("\n", 1)[1]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _classify_8k(text: str, item_codes: list[str]) -> Optional[dict]:
    """Call Haiku. Raises RuntimeError if £15 cap is exceeded."""
    global _haiku_cost_gbp, _haiku_calls

    if _haiku_cost_gbp >= HAIKU_COST_CAP_GBP:
        raise RuntimeError(
            f"HARD COST CAP EXCEEDED: £{_haiku_cost_gbp:.4f} >= £{HAIKU_COST_CAP_GBP:.0f}"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    items_str    = ", ".join(item_codes) if item_codes else "unknown"
    user_content = f"8-K items: {items_str}\n\n{text[:MAX_FILING_CHARS]}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=80,
            system=_HAIKU_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw    = _strip_fences(resp.content[0].text)
        result = json.loads(raw)
        assert "category" in result
        assert isinstance(result.get("material"), bool)
        assert 0.0 <= float(result.get("confidence", 0)) <= 1.0

        cost_usd = (
            resp.usage.input_tokens  / 1000 * HAIKU_COST_PER_1K_INPUT_USD
            + resp.usage.output_tokens / 1000 * HAIKU_COST_PER_1K_OUTPUT_USD
        )
        cost_gbp = cost_usd / GBPUSD
        _haiku_cost_gbp += cost_gbp
        _haiku_calls    += 1

        if _haiku_calls % 25 == 0:
            print(
                f"  [HAIKU] {_haiku_calls} calls | "
                f"£{_haiku_cost_gbp:.4f} / £{HAIKU_COST_CAP_GBP:.0f} cap "
                f"({_haiku_cost_gbp / HAIKU_COST_CAP_GBP * 100:.1f}%)"
            )

        return result

    except (json.JSONDecodeError, AssertionError):
        return None
    except Exception as exc:
        log.warning("Haiku call failed: %s", exc)
        return None


# ── Exit simulation ───────────────────────────────────────────────────────────
def _simulate_exit(df, entry_date: str, entry_price: float) -> dict:
    """Walk forward through daily closes until an exit condition fires."""
    import pandas as pd

    entry_dt = pd.Timestamp(entry_date).normalize()
    post     = df[df.index.normalize() > entry_dt].head(30)

    trading_day = 0
    for idx, row in post.iterrows():
        if idx.weekday() >= 5:   # yfinance rarely includes weekends, but guard anyway
            continue
        trading_day += 1
        cur = float(row.get("Close", 0) or 0)
        if cur <= 0:
            continue
        ret = (cur - entry_price) / entry_price * 100

        if ret >= PROFIT_TARGET_PCT:
            return {"exit_price": cur, "return_pct": ret,
                    "exit_reason": "profit_target", "hold_days": trading_day,
                    "exit_date": idx.date().isoformat()}
        if ret <= STOP_LOSS_PCT:
            return {"exit_price": cur, "return_pct": ret,
                    "exit_reason": "stop_loss", "hold_days": trading_day,
                    "exit_date": idx.date().isoformat()}
        if trading_day >= MAX_HOLD_DAYS:
            return {"exit_price": cur, "return_pct": ret,
                    "exit_reason": "time_exit", "hold_days": trading_day,
                    "exit_date": idx.date().isoformat()}

    # Ran out of data before max hold
    if trading_day > 0:
        last = post.iloc[-1]
        cur  = float(last.get("Close", entry_price) or entry_price)
        ret  = (cur - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        return {"exit_price": cur, "return_pct": ret,
                "exit_reason": "time_exit_partial", "hold_days": trading_day,
                "exit_date": post.index[-1].date().isoformat()}

    return {"exit_price": entry_price, "return_pct": 0.0,
            "exit_reason": "no_data", "hold_days": 0, "exit_date": ""}


# ── Concurrency constraint ────────────────────────────────────────────────────
def _apply_concurrency(all_trades: list[dict]) -> list[dict]:
    """Enforce MAX_POSITIONS simultaneous positions. Earliest-entry-first."""
    trades_sorted = sorted(all_trades, key=lambda t: t["entry_date"])
    open_pos: list[dict] = []
    accepted: list[dict] = []

    for trade in trades_sorted:
        entry = trade["entry_date"]
        open_pos = [p for p in open_pos if p.get("exit_date", "") >= entry]
        if len(open_pos) >= MAX_POSITIONS:
            continue
        accepted.append(trade)
        open_pos.append(trade)

    return accepted


# ── Monte Carlo ───────────────────────────────────────────────────────────────
def _monte_carlo(trades: list[dict]) -> dict:
    """Bootstrap resample observed trade returns; compute portfolio equity distribution."""
    if len(trades) < 5:
        return {}

    returns = [t["return_pct"] for t in trades]
    n       = len(returns)

    sim_finals: list[float] = []
    sim_max_dds: list[float] = []

    for _ in range(N_MC_SIMS):
        sampled = random.choices(returns, k=n)
        equity  = PORTFOLIO_START_GBP
        peak    = equity
        max_dd  = 0.0
        for r in sampled:
            equity += POSITION_SIZE_GBP * r / 100
            if equity > peak:
                peak = equity
            dd = (equity - peak) / peak if peak > 0 else 0.0
            if dd < max_dd:
                max_dd = dd
        sim_finals.append(equity)
        sim_max_dds.append(max_dd)

    sorted_f  = sorted(sim_finals)
    sorted_dd = sorted(sim_max_dds)
    p5_idx    = max(0, int(0.05 * N_MC_SIMS) - 1)
    p95_idx   = min(N_MC_SIMS - 1, int(0.95 * N_MC_SIMS))

    n_hard_kill   = sum(1 for f in sim_finals
                        if (f - PORTFOLIO_START_GBP) / PORTFOLIO_START_GBP <= -0.20)
    n_soft_alert  = sum(1 for f in sim_finals
                        if (f - PORTFOLIO_START_GBP) / PORTFOLIO_START_GBP <= -0.10)

    return {
        "n_sims":              N_MC_SIMS,
        "n_trades":            n,
        "median_final_gbp":    round(statistics.median(sim_finals), 2),
        "p5_final_gbp":        round(sorted_f[p5_idx], 2),
        "p95_final_gbp":       round(sorted_f[p95_idx], 2),
        "median_max_dd_pct":   round(statistics.median(sim_max_dds) * 100, 2),
        "p95_max_dd_pct":      round(sorted_dd[p95_idx] * 100, 2),
        "prob_hard_kill_pct":  round(n_hard_kill  / N_MC_SIMS * 100, 1),
        "prob_soft_alert_pct": round(n_soft_alert / N_MC_SIMS * 100, 1),
    }


# ── Report ────────────────────────────────────────────────────────────────────
def _write_report(
    funnel: dict,
    skip_reasons: dict,
    trades: list[dict],
    mc: dict,
    use_haiku: bool,
    run_date: str,
) -> Path:
    n = len(trades)
    wins   = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]

    win_rate     = len(wins) / n * 100 if n > 0 else 0.0
    avg_win      = statistics.mean([t["return_pct"] for t in wins])   if wins   else 0.0
    avg_loss     = statistics.mean([t["return_pct"] for t in losses]) if losses else 0.0
    total_pnl    = sum(POSITION_SIZE_GBP * t["return_pct"] / 100 for t in trades)
    gross_profit = sum(POSITION_SIZE_GBP * t["return_pct"] / 100 for t in wins)
    gross_loss   = abs(sum(POSITION_SIZE_GBP * t["return_pct"] / 100 for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    exit_counts: dict[str, int] = {}
    for t in trades:
        r = t.get("exit_reason", "unknown")
        exit_counts[r] = exit_counts.get(r, 0) + 1

    # ── Funnel table rows ─────────────────────────────────────────────────────
    total          = funnel.get("total", 0)
    no_price       = skip_reasons.get("no_price_data", 0) + skip_reasons.get("no_day_data", 0)
    no_item        = skip_reasons.get("no_allowed_items", 0)
    drop_7_01      = sum(v for k, v in skip_reasons.items() if k.startswith("7.01"))
    drop_5_02      = sum(v for k, v in skip_reasons.items() if k.startswith("5.02"))
    drop_price_fl  = skip_reasons.get("price_floor", 0)
    drop_delist    = skip_reasons.get("delisted_within_60d", 0)
    after_prefilter= funnel.get("after_prefilter", 0)
    after_haiku    = funnel.get("after_haiku", 0)
    after_entry    = funnel.get("after_entry", 0)
    final_trades   = funnel.get("final_trades", 0)

    def row(label: str, count: int, drop: int) -> str:
        drop_str = f"−{drop}" if drop > 0 else "—"
        return f"| {label} | {count:,} | {drop_str} |"

    lines = [
        "# Swing Bot v1 — Historical Backtest Report",
        "",
        f"**Run date:** {run_date}  ",
        f"**Backtest window:** {BACKTEST_START} → {BACKTEST_END}  ",
        f"**Haiku classification:** {'enabled (Phase B)' if use_haiku else 'disabled (Phase A rule-based)'}  ",
        f"**Haiku cost:** £{_haiku_cost_gbp:.4f} ({_haiku_calls} calls)  ",
        f"**Monte Carlo:** {N_MC_SIMS:,} simulations  ",
        "",
        "---",
        "",
        "## 1. Pre-filter Funnel",
        "",
        "| Stage | Count | Drop |",
        "|-------|------:|-----:|",
        row("Total 8-K filings in window", total, 0),
        row("No price data (excluded)", total - no_price, no_price),
        row("After item code filter (no 1.01/2.01/7.01/8.01/5.02)", total - no_price - no_item, no_item),
        row("After 7.01 price-move gate (≥3%)", total - no_price - no_item - drop_7_01, drop_7_01),
        row("After 5.02 price-move gate (≥5%)", total - no_price - no_item - drop_7_01 - drop_5_02, drop_5_02),
        row("After price floor (≥£5 / $6.35)", after_prefilter + drop_delist, drop_price_fl),
        row("After delisting filter (60d)", after_prefilter, drop_delist),
        row(
            "After Haiku materiality (confidence ≥0.6)" if use_haiku
            else "After Phase A materiality (1.01/2.01 item codes only)",
            after_haiku, after_prefilter - after_haiku,
        ),
        row("After entry rules (momentum + liquidity)", after_entry, after_haiku - after_entry),
        row("After concurrency constraint (≤10 positions)", final_trades, after_entry - final_trades),
        "",
        "---",
        "",
        "## 2. Trade Statistics",
        "",
        f"*{n} trades over 2 years (£{POSITION_SIZE_GBP:.0f}/position, £{PORTFOLIO_START_GBP:.0f} starting capital)*",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Total trades | {n} |",
        f"| Win rate | {win_rate:.1f}% |",
        f"| Avg win | {avg_win:+.2f}% |",
        f"| Avg loss | {avg_loss:+.2f}% |",
        f"| Profit factor | {profit_factor:.2f}x |",
        f"| Total P&L | £{total_pnl:+.2f} |",
        f"| Return on £{PORTFOLIO_START_GBP:.0f} | {total_pnl / PORTFOLIO_START_GBP * 100:+.1f}% |",
        "",
        "### Exit Breakdown",
        "",
        "| Reason | Count | % |",
        "|--------|------:|--:|",
    ]
    for reason, cnt in sorted(exit_counts.items(), key=lambda x: -x[1]):
        pct = cnt / n * 100 if n > 0 else 0
        lines.append(f"| {reason} | {cnt} | {pct:.0f}% |")

    lines += [
        "",
        "---",
        "",
        f"## 3. Monte Carlo Overlay ({N_MC_SIMS:,} bootstrap simulations)",
        "",
        f"Resampling {mc.get('n_trades', 0)} observed trades with replacement.",
        "Each simulation draws the same number of trades and reorders them randomly.",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Median final portfolio | £{mc.get('median_final_gbp', 0):.2f} |",
        f"| 5th percentile | £{mc.get('p5_final_gbp', 0):.2f} |",
        f"| 95th percentile | £{mc.get('p95_final_gbp', 0):.2f} |",
        f"| Median max drawdown | {mc.get('median_max_dd_pct', 0):.1f}% |",
        f"| 95th pct max drawdown | {mc.get('p95_max_dd_pct', 0):.1f}% |",
        f"| P(hard kill ≤−20%) | {mc.get('prob_hard_kill_pct', 0):.1f}% |",
        f"| P(soft alert ≤−10%) | {mc.get('prob_soft_alert_pct', 0):.1f}% |",
        "",
        "---",
        "",
        "## 4. Haiku Classification Cost",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Total calls | {_haiku_calls:,} |",
        f"| Total cost | £{_haiku_cost_gbp:.4f} |",
        f"| Per-call cost | £{(_haiku_cost_gbp / _haiku_calls):.6f} |" if _haiku_calls else "| Per-call cost | £0 |",
        f"| Hard cap | £{HAIKU_COST_CAP_GBP:.0f} |",
        f"| Cap utilisation | {_haiku_cost_gbp / HAIKU_COST_CAP_GBP * 100:.1f}% |",
        "",
        "---",
        "",
        "## 5. Pre-filter Skip Breakdown",
        "",
        "| Skip reason | Count |",
        "|-------------|------:|",
    ]
    # Aggregate granular per-percentage keys into readable groups
    grouped_skips: dict[str, int] = {}
    for reason, cnt in skip_reasons.items():
        if reason.startswith("7.01_no_move"):
            key = "7.01 Reg FD — move < 3% threshold"
        elif reason.startswith("5.02_no_move"):
            key = "5.02 leadership — move < 5% threshold"
        else:
            key = reason
        grouped_skips[key] = grouped_skips.get(key, 0) + cnt
    for reason, cnt in sorted(grouped_skips.items(), key=lambda x: -x[1]):
        lines.append(f"| {reason} | {cnt:,} |")

    lines += [
        "",
        "---",
        "",
        "*Entry simulated at closing price on filing date (or next trading day).*  ",
        "*All positions paper only. Hard rules unchanged: `place_real_order()` raises `RuntimeError`.*  ",
        f"*Generated by `run_backtest.py` on {run_date}.*",
    ]

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _OUTPUT_DIR / f"backtest_{run_date.replace('-', '')}.md"
    report_path.write_text("\n".join(lines) + "\n")
    log.info("Report: %s", report_path)
    return report_path


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Swing Bot v1 Historical Backtest")
    parser.add_argument("--no-haiku", action="store_true",
                        help="Skip Haiku — use Phase A rule-based materiality")
    parser.add_argument("--start", default=BACKTEST_START)
    parser.add_argument("--end",   default=BACKTEST_END)
    args = parser.parse_args()

    use_haiku = not args.no_haiku
    bt_start  = args.start
    bt_end    = args.end
    run_date  = date.today().isoformat()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    _load_env()
    (_CACHE_DIR / "edgar").mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / "texts").mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / "prices").mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 62}")
    print(f"  Swing Bot v1 — Historical Backtest")
    print(f"  Window : {bt_start} → {bt_end}")
    print(f"  Haiku  : {'ENABLED (Phase B)' if use_haiku else 'DISABLED (Phase A)'}")
    print(f"  Cap    : £{HAIKU_COST_CAP_GBP:.0f}")
    print(f"{'=' * 62}\n")

    # ── 1. Watchlist + CIK map ────────────────────────────────────────────────
    tickers    = _load_tickers()
    cik_map    = _load_cik_map()
    ticker_cik = {t: cik_map[t] for t in tickers if t in cik_map}
    log.info("Watchlist: %d tickers | CIK match: %d", len(tickers), len(ticker_cik))

    # ── 2. Price history (batch download, cached) ─────────────────────────────
    log.info("Loading price history (first run takes a few minutes)...")
    price_cache = _load_price_cache(tickers)

    # ── 3. EDGAR 8-K pull ─────────────────────────────────────────────────────
    log.info("Fetching EDGAR 8-K filings for %d tickers...", len(ticker_cik))
    all_filings: list[dict] = []
    for i, (ticker, cik) in enumerate(ticker_cik.items()):
        filings = _fetch_ticker_8ks(ticker, cik)
        all_filings.extend(
            f for f in filings
            if bt_start <= f["filed_date"] <= bt_end
        )
        if (i + 1) % 100 == 0:
            log.info("  EDGAR: %d / %d tickers, %d filings so far",
                     i + 1, len(ticker_cik), len(all_filings))

    funnel       : dict[str, int] = {"total": len(all_filings)}
    skip_reasons : dict[str, int] = {}
    log.info("Total 8-K filings in window: %d", len(all_filings))

    # ── 4. Pre-filter ─────────────────────────────────────────────────────────
    log.info("Applying pre-filters...")
    pre_filtered: list[dict] = []

    for filing in all_filings:
        ticker = filing["ticker"]
        df     = price_cache.get(ticker)

        if df is None or df.empty:
            skip_reasons["no_price_data"] = skip_reasons.get("no_price_data", 0) + 1
            continue

        day_data = _get_day_data(df, filing["filed_date"])
        if not day_data:
            skip_reasons["no_day_data"] = skip_reasons.get("no_day_data", 0) + 1
            continue

        same_day_pct = day_data["price_change_pct"]
        close_price  = day_data["close"]

        # Pre-filter A: item codes + price-move gates
        passes, reason = prefilter_8k(filing["items"], same_day_pct)
        if not passes:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        # Pre-filter B: price floor £5 ($6.35)
        if close_price < PRICE_FLOOR_USD:
            skip_reasons["price_floor"] = skip_reasons.get("price_floor", 0) + 1
            continue

        # Pre-filter C: delisting within 60 days
        if _is_delisted_within_60d(df, filing["filed_date"]):
            skip_reasons["delisted_within_60d"] = skip_reasons.get("delisted_within_60d", 0) + 1
            continue

        filing["day_data"] = day_data
        pre_filtered.append(filing)

    funnel["after_prefilter"] = len(pre_filtered)
    log.info("Pre-filter survivors: %d / %d  (skip: %s)",
             len(pre_filtered), len(all_filings),
             dict(sorted(skip_reasons.items(), key=lambda x: -x[1])[:5]))

    # ── 5. Haiku classification ───────────────────────────────────────────────
    classified: list[dict] = []

    if use_haiku:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.warning("ANTHROPIC_API_KEY not set — falling back to Phase A rule-based")
            use_haiku = False
        else:
            print(f"\n[HAIKU] Classifying {len(pre_filtered)} filings...")
            print(f"[HAIKU] Cost cap: £{HAIKU_COST_CAP_GBP:.0f}\n")
            cap_hit = False

            for i, filing in enumerate(pre_filtered):
                try:
                    text   = _fetch_filing_text(filing["cik"], filing["accession"])
                    result = _classify_8k(text, filing["items"])
                    if result is None:
                        # API key present but call failed — treat as not material
                        continue
                    if result.get("material") and float(result.get("confidence", 0)) >= HAIKU_MIN_CONFIDENCE:
                        filing["classification"] = result
                        classified.append(filing)
                except RuntimeError as exc:
                    log.error("%s", exc)
                    print(f"\n[HAIKU] COST CAP REACHED after {i + 1} filings")
                    print(f"[HAIKU] Final cost: £{_haiku_cost_gbp:.4f}")
                    cap_hit = True
                    break

            print(f"\n[HAIKU] Done. {_haiku_calls} calls | £{_haiku_cost_gbp:.4f} spent\n")
            if cap_hit:
                log.warning("Cost cap hit — %d filings remain unclassified", len(pre_filtered) - len(classified))

    if not use_haiku:
        # Phase A: material if high-priority item code (1.01 or 2.01) present
        classified = [
            f for f in pre_filtered
            if bool(set(f["items"]) & {"1.01", "2.01"})
        ]
        log.info("Phase A rule-based materiality: %d / %d", len(classified), len(pre_filtered))

    funnel["after_haiku"] = len(classified)

    # ── 6. Entry rules ────────────────────────────────────────────────────────
    log.info("Entry rule evaluation for %d candidates...", len(classified))
    entry_candidates: list[dict] = []

    for filing in classified:
        dd = filing.get("day_data", {})
        price_change_pct = dd.get("price_change_pct", 0.0)
        trend_5d_pct     = dd.get("trend_5d_pct", 0.0)
        avg_vol_usd      = dd.get("avg_daily_vol_usd", 0.0)
        current_price    = dd.get("close", 0.0)

        if price_change_pct < MIN_PRICE_CHANGE_PCT:
            continue
        if trend_5d_pct < TREND_FLOOR_PCT:
            continue
        if avg_vol_usd < MIN_LIQUIDITY_USD:
            continue
        if current_price <= 0:
            continue

        filing["entry_price"] = current_price
        filing["entry_date"]  = dd.get("actual_date", filing["filed_date"])
        entry_candidates.append(filing)

    funnel["after_entry"] = len(entry_candidates)
    log.info("Entry rule survivors: %d", len(entry_candidates))

    # ── 7. Exit simulation ────────────────────────────────────────────────────
    log.info("Simulating exits...")
    raw_trades: list[dict] = []

    for filing in entry_candidates:
        ticker = filing["ticker"]
        df     = price_cache.get(ticker)
        if df is None:
            continue

        exit_result = _simulate_exit(df, filing["entry_date"], filing["entry_price"])
        if exit_result["exit_reason"] == "no_data":
            continue

        classification = filing.get("classification", {})
        catalyst_cat   = classification.get("category", "8K_rule") if classification else "8K_rule"

        raw_trades.append({
            "ticker":       ticker,
            "filed_date":   filing["filed_date"],
            "items":        filing.get("items", []),
            "catalyst_type":catalyst_cat,
            "entry_date":   filing["entry_date"],
            "entry_price":  filing["entry_price"],
            "exit_date":    exit_result["exit_date"],
            "exit_price":   exit_result["exit_price"],
            "exit_reason":  exit_result["exit_reason"],
            "return_pct":   round(exit_result["return_pct"], 4),
            "pnl_gbp":      round(POSITION_SIZE_GBP * exit_result["return_pct"] / 100, 4),
            "hold_days":    exit_result["hold_days"],
        })

    # ── 8. Concurrency constraint ─────────────────────────────────────────────
    trades = _apply_concurrency(raw_trades)
    funnel["final_trades"] = len(trades)
    log.info("After concurrency: %d trades", len(trades))

    # ── 9. Monte Carlo ────────────────────────────────────────────────────────
    log.info("Monte Carlo (%d simulations)...", N_MC_SIMS)
    mc = _monte_carlo(trades)

    # ── 10. Save trade log ────────────────────────────────────────────────────
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    trades_path = _DATA_DIR / f"trades_{run_date.replace('-', '')}.jsonl"
    with open(trades_path, "w") as f:
        for t in trades:
            f.write(json.dumps(t, default=str) + "\n")
    log.info("Trade log: %s", trades_path)

    # ── 11. Report ────────────────────────────────────────────────────────────
    report_path = _write_report(funnel, skip_reasons, trades, mc, use_haiku, run_date)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 62}")
    print(f"  BACKTEST COMPLETE")
    print(f"{'=' * 62}")
    print(f"  8-K filings:        {funnel['total']:>6,}")
    print(f"  Pre-filter:         {funnel.get('after_prefilter', '?'):>6}")
    print(f"  Material (Haiku/A): {funnel.get('after_haiku', '?'):>6}")
    print(f"  Entry rule pass:    {funnel.get('after_entry', '?'):>6}")
    print(f"  Actual trades:      {len(trades):>6}")

    if trades:
        wr        = sum(1 for t in trades if t["return_pct"] > 0) / len(trades) * 100
        total_pnl = sum(t["pnl_gbp"] for t in trades)
        print(f"  Win rate:           {wr:>5.1f}%")
        print(f"  Total P&L:          £{total_pnl:>+.2f}")

    if mc:
        print(f"\n  Monte Carlo (£500 start, {mc['n_sims']:,} sims):")
        print(f"    Median final:   £{mc['median_final_gbp']:.2f}")
        print(f"    5th pct:        £{mc['p5_final_gbp']:.2f}")
        print(f"    95th pct:       £{mc['p95_final_gbp']:.2f}")
        print(f"    P(hard kill):    {mc['prob_hard_kill_pct']:.1f}%")
        print(f"    P(soft alert):   {mc['prob_soft_alert_pct']:.1f}%")

    print(f"\n  Haiku:  £{_haiku_cost_gbp:.4f}  ({_haiku_calls} calls)")
    print(f"  Report: {report_path}")
    print(f"  Trades: {trades_path}")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
