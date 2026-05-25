#!/usr/bin/env python3
"""Swing Bot v1 — Follow-up Backtests (Phase B + Sensitivity + Catalyst Breakdown)

Tests:
  1. Phase B: Haiku classifies the 2,125 non-1.01/2.01 pre-filter survivors.
             Auto-includes Phase A material (1.01/2.01). Compare vs Phase A.
  2. Sensitivity grid: momentum threshold 1.0%→3.0% on Phase A material.
             Find best PF with ≥100 trades.
  3. Catalyst breakdown: Phase A 50 trades split by item code (1.01 / 2.01 / both).

Output:  swing-bot/backtest/PHASE_B_SENSITIVITY.md  (committed to git)
Purpose: Go/No-Go decision on flipping alert_mode_only Thursday 2026-05-28

Hard rules unchanged — place_real_order() not called, no real positions opened.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# ── Import shared infrastructure from run_backtest.py ─────────────────────────
_spec = importlib.util.spec_from_file_location(
    "run_backtest", Path(__file__).parent / "run_backtest.py"
)
_bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bt)

log = logging.getLogger("followup")

# ── Constants ──────────────────────────────────────────────────────────────────
HAIKU_COST_CAP      = 15.0          # £ — separate from live £5/month cap
PHASE_A_ITEMS       = {"1.01", "2.01"}
MOMENTUM_THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0]
N_MC_SIMS           = 5_000         # faster than full 10k; enough for P(kill)
BACKTEST_MONTHS     = 24
OUTPUT_DIR          = _ROOT / "backtest"   # swing-bot/backtest/ — NOT in data/ gitignore

# ── Thread-safe Haiku state ────────────────────────────────────────────────────
_haiku_lock  = threading.Lock()
_haiku_state: dict = {"cost_gbp": 0.0, "calls": 0, "cap_hit": False}


def _classify_one(filing: dict, api_key: str) -> Optional[dict]:
    """Thread-safe Haiku call for one filing. Returns classification dict or None."""
    with _haiku_lock:
        if _haiku_state["cap_hit"] or _haiku_state["cost_gbp"] >= HAIKU_COST_CAP:
            _haiku_state["cap_hit"] = True
            return None

    text = _bt._fetch_filing_text(filing["cik"], filing["accession"])
    if not text:
        return None

    items_str    = ", ".join(filing.get("items", [])) or "unknown"
    user_content = f"8-K items: {items_str}\n\n{text[:_bt.MAX_FILING_CHARS]}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model=_bt.HAIKU_MODEL,
            max_tokens=80,
            system=_bt._HAIKU_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw    = resp.content[0].text.strip()
        result = json.loads(raw)
        assert "category" in result
        assert isinstance(result.get("material"), bool)
        assert 0.0 <= float(result.get("confidence", 0)) <= 1.0

        cost_usd = (
            resp.usage.input_tokens  / 1000 * _bt.HAIKU_COST_PER_1K_INPUT_USD
            + resp.usage.output_tokens / 1000 * _bt.HAIKU_COST_PER_1K_OUTPUT_USD
        )
        cost_gbp = cost_usd / _bt.GBPUSD

        with _haiku_lock:
            _haiku_state["cost_gbp"] += cost_gbp
            _haiku_state["calls"]    += 1
            n = _haiku_state["calls"]
            c = _haiku_state["cost_gbp"]
            if n % 25 == 0:
                print(f"  [HAIKU] {n} calls | £{c:.4f} / £{HAIKU_COST_CAP:.0f} "
                      f"({c / HAIKU_COST_CAP * 100:.1f}%)")
            if c >= HAIKU_COST_CAP:
                _haiku_state["cap_hit"] = True

        return result

    except (json.JSONDecodeError, AssertionError):
        return None
    except Exception as exc:
        log.debug("Haiku call failed (%s): %s", filing.get("ticker"), exc)
        return None


# ── Trade helpers ─────────────────────────────────────────────────────────────
def _apply_entry(candidates: list[dict], momentum_threshold: float) -> list[dict]:
    """Apply entry rules. Returns enriched filing dicts with entry_price/entry_date."""
    result = []
    for f in candidates:
        dd = f.get("day_data", {})
        if dd.get("price_change_pct", 0.0)  < momentum_threshold:
            continue
        if dd.get("trend_5d_pct", 0.0)      < _bt.TREND_FLOOR_PCT:
            continue
        if dd.get("avg_daily_vol_usd", 0.0)  < _bt.MIN_LIQUIDITY_USD:
            continue
        close = dd.get("close", 0.0)
        if close <= 0:
            continue
        f2 = dict(f)
        f2["entry_price"] = close
        f2["entry_date"]  = dd.get("actual_date", f["filed_date"])
        result.append(f2)
    return result


def _simulate_trades(entry_candidates: list[dict], price_cache: dict) -> list[dict]:
    """Exit-simulate and apply concurrency constraint. Returns final trade list."""
    raw: list[dict] = []
    for f in entry_candidates:
        df = price_cache.get(f["ticker"])
        if df is None:
            continue
        ex = _bt._simulate_exit(df, f["entry_date"], f["entry_price"])
        if ex["exit_reason"] == "no_data":
            continue
        cl  = f.get("classification", {}) or {}
        raw.append({
            "ticker":        f["ticker"],
            "filed_date":    f["filed_date"],
            "items":         f.get("items", []),
            "catalyst_type": cl.get("category", "8K_rule"),
            "entry_date":    f["entry_date"],
            "entry_price":   f["entry_price"],
            "exit_date":     ex["exit_date"],
            "exit_price":    ex["exit_price"],
            "exit_reason":   ex["exit_reason"],
            "return_pct":    round(ex["return_pct"], 4),
            "pnl_gbp":       round(50.0 * ex["return_pct"] / 100, 4),
            "hold_days":     ex["hold_days"],
        })
    return _bt._apply_concurrency(raw)


def _trade_stats(trades: list[dict]) -> dict:
    """Compute summary statistics for a list of closed trades."""
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "total_pnl": 0.0, "profit_factor": 0.0, "annualized_pct": 0.0,
            "expected_return": 0.0, "p_hard_kill": 0.0,
        }

    wins   = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]
    win_rate      = len(wins) / n * 100
    avg_win       = statistics.mean([t["return_pct"] for t in wins])   if wins   else 0.0
    avg_loss      = statistics.mean([t["return_pct"] for t in losses]) if losses else 0.0
    gross_profit  = sum(50.0 * t["return_pct"] / 100 for t in wins)
    gross_loss    = abs(sum(50.0 * t["return_pct"] / 100 for t in losses))
    total_pnl     = gross_profit - gross_loss
    pf            = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    ann           = (total_pnl / 500.0) * (12 / BACKTEST_MONTHS) * 100
    exp_ret       = avg_win * (win_rate / 100) + avg_loss * (1 - win_rate / 100)

    # Lightweight Monte Carlo for P(hard kill)
    returns = [t["return_pct"] for t in trades]
    n_kill  = 0
    for _ in range(N_MC_SIMS):
        equity = 500.0
        peak   = equity
        for r in random.choices(returns, k=n):
            equity += 50.0 * r / 100
            if equity > peak:
                peak = equity
            if peak > 0 and (equity - peak) / peak <= -0.20:
                n_kill += 1
                break
    p_hard_kill = n_kill / N_MC_SIMS * 100

    return {
        "n":                n,
        "win_rate":         round(win_rate, 1),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "total_pnl":        round(total_pnl, 2),
        "profit_factor":    round(pf, 2) if pf != float("inf") else 999.0,
        "annualized_pct":   round(ann, 1),
        "expected_return":  round(exp_ret, 2),
        "p_hard_kill":      round(p_hard_kill, 1),
    }


# ── Verdict ────────────────────────────────────────────────────────────────────
def _verdict(
    phase_a: dict,
    phase_b: dict,
    best_thresh_stats: dict,
    best_threshold: float,
) -> tuple[str, list[str]]:
    """Return (STRONG_GO|GO|CAUTION|NO_GO, [reason_lines])."""
    pf  = best_thresh_stats.get("profit_factor", 0.0)
    wr  = best_thresh_stats.get("win_rate", 0.0)
    n   = best_thresh_stats.get("n", 0)
    pk  = best_thresh_stats.get("p_hard_kill", 100.0)
    ann = best_thresh_stats.get("annualized_pct", 0.0)

    reasons: list[str] = []

    if pf >= 1.30 and wr >= 52.0 and n >= 100 and pk < 2.0:
        label = "STRONG_GO"
        reasons.append(
            f"At {best_threshold:.1f}% momentum: PF={pf:.2f}x, WR={wr:.1f}%, "
            f"{n} trades over 24 months, P(hard kill)={pk:.1f}% — clear, repeatable edge."
        )
    elif pf >= 1.10 and wr >= 46.0 and n >= 60 and pk < 8.0 and ann > 0:
        label = "GO"
        reasons.append(
            f"At {best_threshold:.1f}% momentum: PF={pf:.2f}x, WR={wr:.1f}%, "
            f"{n} trades — marginal positive edge. Live paper acceptable."
        )
    elif pf >= 1.00 and ann > 0 and pk < 15.0:
        label = "CAUTION"
        reasons.append(
            f"PF={pf:.2f}x is thin at {best_threshold:.1f}% threshold. "
            f"Recommend another week of alert-only logs before flipping."
        )
    else:
        label = "NO_GO"
        reasons.append(
            f"PF={pf:.2f}x ≤ 1.0 or P(hard kill)={pk:.1f}% unacceptably high. "
            f"Keep alert_mode_only=true."
        )

    # Phase B comment
    b_n  = phase_b.get("n", 0)
    a_n  = phase_a.get("n", 0)
    b_pf = phase_b.get("profit_factor", 0.0)
    a_pf = phase_a.get("profit_factor", 0.0)
    if b_n > a_n:
        reasons.append(
            f"Phase B adds {b_n - a_n} incremental trades via Haiku "
            f"(PF {b_pf:.2f}x vs Phase A {a_pf:.2f}x). "
            + ("Haiku improves the system." if b_pf >= a_pf else "Haiku does NOT improve PF — question Phase B value.")
        )
    else:
        reasons.append("Phase B adds no incremental trades — Haiku provides no lift at this cost.")

    # Flip recommendation
    if label in ("STRONG_GO", "GO"):
        reasons.append(
            f"Recommendation: flip alert_mode_only → false Thursday 2026-05-28 "
            f"at {best_threshold:.1f}% momentum threshold (update settings.yaml)."
        )
    else:
        reasons.append("Recommendation: keep alert_mode_only=true. Review again after 3 live trading weeks.")

    return label, reasons


# ── Report ─────────────────────────────────────────────────────────────────────
def _write_report(
    phase_a_stats: dict,
    phase_b_stats: dict,
    sensitivity_rows: list[dict],
    catalyst_rows: list[dict],
    haiku_cost: float,
    haiku_calls: int,
    verdict_label: str,
    verdict_reasons: list[str],
    run_date: str,
) -> Path:
    verdict_icon = {"STRONG_GO": "✅", "GO": "🟢", "CAUTION": "🟡", "NO_GO": "🔴"}.get(verdict_label, "❓")
    flip_str     = "**FLIP TO `false`**" if verdict_label in ("STRONG_GO", "GO") else "**KEEP `true`**"

    def fmt(v):
        if isinstance(v, float):
            return f"{v:+.2f}" if abs(v) < 1000 else f"{v:.0f}"
        return str(v)

    rows_comp = [
        ("Trades",                     "n"),
        ("Win rate (%)",               "win_rate"),
        ("Avg win (%)",                "avg_win"),
        ("Avg loss (%)",               "avg_loss"),
        ("Expected return/trade (%)",  "expected_return"),
        ("Profit factor",              "profit_factor"),
        ("Total P&L (£)",              "total_pnl"),
        ("Annualised return (%)",      "annualized_pct"),
        ("P(hard kill ≤−20%) (%)",    "p_hard_kill"),
    ]

    lines: list[str] = [
        "# Swing Bot v1 — Phase B + Sensitivity Analysis",
        "",
        f"**Generated:** {run_date}  ",
        f"**Purpose:** Go/No-Go on `alert_mode_only` flip Thursday 2026-05-28  ",
        f"**Haiku cost (Test 1):** £{haiku_cost:.4f} ({haiku_calls} calls)  ",
        f"**Monte Carlo:** {N_MC_SIMS:,} bootstrap simulations per stats block  ",
        "",
        "---",
        "",
        "## Test 1: Phase B vs Phase A",
        "",
        "Phase A materiality = 1.01/2.01 item codes only (994 survivors).  ",
        "Phase B = Phase A pool (auto-included) + Haiku classification of the 2,125  ",
        "other pre-filter survivors (7.01/8.01/5.02 triggered). Entry rules identical.",
        "",
        "| Metric | Phase A | Phase B | Δ |",
        "|--------|--------:|--------:|--:|",
    ]
    for label, key in rows_comp:
        a = phase_a_stats.get(key, 0)
        b = phase_b_stats.get(key, 0)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = round(b - a, 2)
            sign  = "+" if delta > 0 else ""
            delta_str = f"{sign}{delta}"
        else:
            delta_str = "—"
        lines.append(f"| {label} | {fmt(a)} | {fmt(b)} | {delta_str} |")

    # Sensitivity grid
    lines += [
        "",
        "---",
        "",
        "## Test 2: Sensitivity Grid (Momentum Threshold, Phase A Materiality)",
        "",
        "All other entry rules fixed: 5-day trend ≥−1%, avg daily vol ≥$6.35M,  ",
        "concurrency ≤10 positions, exit rules unchanged.  ",
        "◀ marks best profit factor with ≥100 trades (or overall best if none reach 100).",
        "",
        "| Threshold | Trades | Win rate | Avg win | Avg loss | Exp. ret | PF | Total P&L | Ann. % | P(kill) |",
        "|----------:|-------:|---------:|--------:|---------:|---------:|---:|----------:|-------:|--------:|",
    ]
    for row in sensitivity_rows:
        s    = row["stats"]
        mark = " ◀" if row.get("best") else ""
        pf_s = f"{s['profit_factor']:.2f}x" if s["profit_factor"] < 900 else "∞"
        lines.append(
            f"| {row['threshold']:.1f}% | {s['n']} | {s['win_rate']:.1f}% | "
            f"{s['avg_win']:+.2f}% | {s['avg_loss']:+.2f}% | "
            f"{s['expected_return']:+.2f}% | {pf_s} | "
            f"£{s['total_pnl']:+.2f} | {s['annualized_pct']:+.1f}% | "
            f"{s['p_hard_kill']:.1f}%{mark} |"
        )

    # Catalyst breakdown
    lines += [
        "",
        "---",
        "",
        "## Test 3: Catalyst Breakdown (Phase A, 3% momentum threshold)",
        "",
        "| Item code | Trades | Win rate | Avg win | Avg loss | Exp. return | PF | Ann. % |",
        "|-----------|-------:|---------:|--------:|---------:|------------:|---:|-------:|",
    ]
    for row in catalyst_rows:
        s    = row["stats"]
        pf_s = f"{s['profit_factor']:.2f}x" if s["profit_factor"] < 900 else "∞"
        lines.append(
            f"| {row['label']} | {s['n']} | {s['win_rate']:.1f}% | "
            f"{s['avg_win']:+.2f}% | {s['avg_loss']:+.2f}% | "
            f"{s['expected_return']:+.2f}% | {pf_s} | {s['annualized_pct']:+.1f}% |"
        )

    # Verdict
    lines += [
        "",
        "---",
        "",
        f"## Verdict: {verdict_icon} {verdict_label}",
        "",
        f"**`alert_mode_only` Thursday:** {flip_str}",
        "",
    ]
    for reason in verdict_reasons:
        lines.append(f"- {reason}")

    lines += [
        "",
        "---",
        "",
        "*All positions paper-only. `place_real_order()` raises `RuntimeError`. Hard rules unchanged.*  ",
        f"*Generated by `run_followup_tests.py` on {run_date}.*",
        "",
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "PHASE_B_SENSITIVITY.md"
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
    api_key  = os.environ.get("ANTHROPIC_API_KEY", "")
    run_date = date.today().isoformat()

    print(f"\n{'=' * 64}")
    print(f"  Swing Bot v1 — Follow-up Backtests")
    print(f"  Test 1: Phase B (Haiku)  | Test 2: Sensitivity | Test 3: Catalysts")
    print(f"{'=' * 64}\n")

    # ── Shared pipeline (uses cache from Phase A run — should be fast) ─────────
    log.info("Rebuilding pipeline from cache...")

    tickers     = _bt._load_tickers()
    cik_map     = _bt._load_cik_map()
    ticker_cik  = {t: cik_map[t] for t in tickers if t in cik_map}
    price_cache = _bt._load_price_cache(tickers)

    log.info("Fetching EDGAR filings from cache...")
    all_filings: list[dict] = []
    for ticker, cik in ticker_cik.items():
        filings = _bt._fetch_ticker_8ks(ticker, cik)
        all_filings.extend(
            f for f in filings
            if _bt.BACKTEST_START <= f["filed_date"] <= _bt.BACKTEST_END
        )
    log.info("Filings in window: %d", len(all_filings))

    log.info("Applying pre-filter...")
    pre_filtered: list[dict] = []
    for filing in all_filings:
        df = price_cache.get(filing["ticker"])
        if df is None or df.empty:
            continue
        dd = _bt._get_day_data(df, filing["filed_date"])
        if not dd:
            continue
        passes, _ = _bt.prefilter_8k(filing["items"], dd["price_change_pct"])
        if not passes:
            continue
        if dd["close"] < _bt.PRICE_FLOOR_USD:
            continue
        if _bt._is_delisted_within_60d(df, filing["filed_date"]):
            continue
        filing["day_data"] = dd
        pre_filtered.append(filing)

    phase_a_material = [f for f in pre_filtered if PHASE_A_ITEMS & set(f["items"])]
    others           = [f for f in pre_filtered if not (PHASE_A_ITEMS & set(f["items"]))]
    log.info("Pre-filter survivors: %d (Phase A: %d | Others: %d)",
             len(pre_filtered), len(phase_a_material), len(others))

    # ── Test 2: Sensitivity grid ──────────────────────────────────────────────
    print("\n[TEST 2] Sensitivity grid (momentum threshold 1.0%→3.0%)...")
    sensitivity_rows: list[dict] = []
    best_pf  = -1.0
    best_idx = -1

    for i, threshold in enumerate(MOMENTUM_THRESHOLDS):
        cands  = _apply_entry(phase_a_material, threshold)
        trades = _simulate_trades(cands, price_cache)
        s      = _trade_stats(trades)
        sensitivity_rows.append({"threshold": threshold, "stats": s})
        log.info("  %.1f%%: %d trades | PF=%.2f | WR=%.1f%% | Ann=%.1f%% | P(kill)=%.1f%%",
                 threshold, s["n"], s["profit_factor"], s["win_rate"],
                 s["annualized_pct"], s["p_hard_kill"])
        if s["n"] >= 100 and s["profit_factor"] > best_pf:
            best_pf  = s["profit_factor"]
            best_idx = i

    if best_idx < 0:  # no threshold hit ≥100 trades
        best_idx = max(range(len(sensitivity_rows)),
                       key=lambda i: sensitivity_rows[i]["stats"]["profit_factor"])
    sensitivity_rows[best_idx]["best"] = True
    best_stats     = sensitivity_rows[best_idx]["stats"]
    best_threshold = sensitivity_rows[best_idx]["threshold"]
    log.info("Best threshold: %.1f%% (%d trades, PF=%.2f)", best_threshold, best_stats["n"], best_stats["profit_factor"])

    # ── Test 3: Catalyst breakdown ────────────────────────────────────────────
    print("\n[TEST 3] Catalyst breakdown by item code (Phase A, 3% threshold)...")
    cands_3pct   = _apply_entry(phase_a_material, 3.0)
    trades_3pct  = _simulate_trades(cands_3pct, price_cache)
    phase_a_stats = _trade_stats(trades_3pct)

    def _group(label: str, has: set, not_has: set = frozenset()) -> dict:
        subset = [
            t for t in trades_3pct
            if (set(t["items"]) & has) and not (set(t["items"]) & not_has)
        ]
        return {"label": label, "stats": _trade_stats(subset)}

    catalyst_rows = [
        _group("1.01 M&A/agreements (only)", {"1.01"}, {"2.01"}),
        _group("2.01 Completion of acq (only)", {"2.01"}, {"1.01"}),
        _group("1.01 + 2.01 (combined deal)", {"1.01", "2.01"}),
        {"label": "All Phase A (combined)", "stats": phase_a_stats},
    ]

    for row in catalyst_rows:
        s = row["stats"]
        log.info("  %-30s %2d trades | PF=%.2f | WR=%.1f%%",
                 row["label"], s["n"], s["profit_factor"], s["win_rate"])

    # ── Test 1: Phase B Haiku ─────────────────────────────────────────────────
    print(f"\n[TEST 1] Phase B — Haiku classification of {len(others)} non-Phase-A filings...")

    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — Test 1 uses Phase A stats as Phase B")
        phase_b_stats = phase_a_stats
    else:
        # Pre-Haiku efficiency filter:
        # 8.01-only filings with same_day_pct < 1.5% can't reach the 3% entry gate.
        # 7.01 and 5.02 survivors already had ≥3%/≥5% confirmed by pre-filter.
        haiku_cands: list[dict] = []
        efficiency_skipped = 0
        for f in others:
            item_set = set(f["items"])
            only_8_01 = item_set <= {"8.01"}
            pct = f.get("day_data", {}).get("price_change_pct", 0.0)
            if only_8_01 and pct < 1.5:
                efficiency_skipped += 1
                continue
            haiku_cands.append(f)

        log.info("Pre-Haiku filter: %d → %d (skipped %d 8.01-only low-move filings)",
                 len(others), len(haiku_cands), efficiency_skipped)
        print(f"[HAIKU] {len(haiku_cands)} filings to classify | cap: £{HAIKU_COST_CAP:.0f}\n")

        # Concurrent classification (5 workers — respects EDGAR text cache)
        haiku_material: list[dict] = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_classify_one, f, api_key): f for f in haiku_cands}
            for fut in as_completed(futures):
                filing = futures[fut]
                try:
                    result = fut.result()
                    if (result
                            and result.get("material")
                            and float(result.get("confidence", 0)) >= _bt.HAIKU_MIN_CONFIDENCE):
                        filing["classification"] = result
                        haiku_material.append(filing)
                except Exception as exc:
                    log.debug("Classification error %s: %s", filing.get("ticker"), exc)

        print(f"\n[HAIKU] Done — {_haiku_state['calls']} calls | "
              f"£{_haiku_state['cost_gbp']:.4f} | "
              f"{len(haiku_material)} material")

        # Phase B pool = auto-included Phase A material + Haiku-classified others
        phase_b_pool  = list(phase_a_material) + haiku_material
        cands_b       = _apply_entry(phase_b_pool, 3.0)
        trades_b      = _simulate_trades(cands_b, price_cache)
        phase_b_stats = _trade_stats(trades_b)
        log.info("Phase B: %d trades (%+d vs Phase A %d)",
                 phase_b_stats["n"], phase_b_stats["n"] - phase_a_stats["n"], phase_a_stats["n"])

    # ── Verdict ────────────────────────────────────────────────────────────────
    verdict_label, verdict_reasons = _verdict(
        phase_a_stats, phase_b_stats, best_stats, best_threshold
    )

    # ── Write report ───────────────────────────────────────────────────────────
    report_path = _write_report(
        phase_a_stats, phase_b_stats,
        sensitivity_rows, catalyst_rows,
        _haiku_state["cost_gbp"], _haiku_state["calls"],
        verdict_label, verdict_reasons, run_date,
    )

    # ── Console summary ────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print(f"  FOLLOW-UP TESTS COMPLETE")
    print(f"{'=' * 64}")
    print(f"  Phase A:          {phase_a_stats['n']:>3} trades | PF={phase_a_stats['profit_factor']:.2f}x | WR={phase_a_stats['win_rate']:.1f}%")
    print(f"  Phase B:          {phase_b_stats['n']:>3} trades | PF={phase_b_stats['profit_factor']:.2f}x | WR={phase_b_stats['win_rate']:.1f}%")
    print(f"  Best threshold:   {best_threshold:.1f}% ({best_stats['n']} trades | PF={best_stats['profit_factor']:.2f}x)")
    print(f"  Haiku:            £{_haiku_state['cost_gbp']:.4f} ({_haiku_state['calls']} calls)")
    print(f"  Verdict:          {verdict_label}")
    print(f"  Report:           {report_path}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
