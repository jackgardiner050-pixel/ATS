#!/usr/bin/env python3
"""Universe screener — runs the pipeline across all tickers in universe.yaml.

Phase 1: DCF + comps valuation (orchestrator)
Phase 2: Signal cross-check — 12m momentum + EPS revision direction
Phase 3: Confidence escalation — aligned/contradicting signals adjust tier
"""
import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.orchestrator import run_pipeline
from src.cadence import (
    load_state, is_due, update_state, apply_force,
    compute_next_due, save_state,
)
from src.signals.momentum import compute_universe_momentum
from src.signals.revisions import compute_revisions
from src.signals.escalation import (
    get_signal_alignment, apply_confidence_escalation,
    build_signal_alignment_list, should_force_rescreen, revision_symbol,
)


_SIGNAL_LOG = Path(__file__).parent.parent / "data" / "signal_log.jsonl"


def _update_recommendation_json(
    run_dir: Path,
    conf_after: str,
    conf_before: str,
    signal_alignment: list[dict],
) -> None:
    rec_path = run_dir / "recommendation.json"
    if not rec_path.exists():
        return
    with open(rec_path) as f:
        data = json.load(f)
    data["confidence"] = conf_after
    data["confidence_before_signals"] = conf_before
    data["signal_alignment"] = signal_alignment
    with open(rec_path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _log_signal(
    ticker: str, today: date, rating: str,
    conf_before: str, conf_after: str,
    momentum_quintile, revision_direction: str,
    n_aligned: int, n_contradicted: int,
) -> None:
    _SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ticker": ticker,
        "date": str(today),
        "rating": rating,
        "confidence_before": conf_before,
        "confidence_after": conf_after,
        "momentum_quintile": momentum_quintile,
        "revision_direction": revision_direction,
        "alignment_score": f"+{n_aligned} aligned, -{n_contradicted} contradicted",
    }
    with open(_SIGNAL_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def main():
    p = argparse.ArgumentParser(description="Universe screener with adaptive cadence.")
    p.add_argument("--universe", type=Path, default=Path("config/universe.yaml"))
    p.add_argument("--output-root", type=Path, default=Path("runs"))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--tickers", type=str, default=None,
                   help="Comma-separated ticker list; overrides --universe")
    p.add_argument("--force", type=str, action="append", default=[], metavar="TICKER",
                   help="Force re-screen for TICKER (may repeat)")
    p.add_argument("--force-all", action="store_true",
                   help="Force re-screen for every ticker in the universe")
    p.add_argument("--include-skipped", action="store_true",
                   help="Print rows for tickers not due this run")
    args = p.parse_args()

    today = date.today()

    # Resolve ticker list
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        with open(args.universe) as f:
            cfg = yaml.safe_load(f)
        tickers = [t.upper() for t in cfg.get("universe", [])]
    if args.limit:
        tickers = tickers[:args.limit]

    # Load cadence state
    state = load_state()

    # Determine forced set
    forced_tickers: set[str] = {t.upper() for t in args.force}
    if args.force_all:
        forced_tickers = set(tickers)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    screen_dir = args.output_root / "_screen" / ts
    screen_dir.mkdir(parents=True, exist_ok=True)

    n_due = sum(1 for t in tickers if t.upper() in forced_tickers or is_due(t, today, state))
    n_total = len(tickers)
    print(f"Screening universe: {n_total} tickers  |  due={n_due}  skipped={n_total - n_due}  (today={today})")
    print()

    results = []
    n_screened = 0
    n_skipped = 0
    n_broken = 0

    # ─── Phase 1: Valuation pipeline ─────────────────────────────────────────
    for i, ticker in enumerate(tickers, 1):
        ticker = ticker.upper()
        forced = ticker in forced_tickers
        due = forced or is_due(ticker, today, state)

        if not due:
            n_skipped += 1
            rec = state.get(ticker, {})
            results.append({
                "ticker": ticker,
                "rating": rec.get("last_rating", "?"),
                "confidence": rec.get("last_confidence", "?"),
                "current_price": None,
                "price_target": rec.get("last_pt"),
                "expected_return": rec.get("last_expected_return"),
                "last_screen_date": rec.get("last_screen_date"),
                "next_due_date": rec.get("next_due_date"),
                "status": "SKIPPED",
                "ok": True,
                "momentum_quintile": None,
                "revision_direction": None,
            })
            if args.include_skipped:
                print(f"[{i}/{n_total}] {ticker:<6} SKIPPED  (next due {rec.get('next_due_date', '?')})")
            continue

        status = "FORCED" if forced else "DUE"
        print(f"[{i}/{n_total}] {ticker}...", end=" ", flush=True)
        try:
            r = run_pipeline(ticker=ticker, output_root=args.output_root)
            state = update_state(ticker, r, state)
            conf = r.get("confidence", "?")
            results.append({
                "ticker": ticker,
                "rating": r["rating"],
                "confidence": conf,
                "confidence_before": conf,    # will be updated in Phase 3
                "current_price": r["current_price"],
                "price_target": r["price_target_12m"],
                "expected_return": r["expected_return"],
                "last_screen_date": str(today),
                "next_due_date": state.get(ticker, {}).get("next_due_date"),
                "status": status,
                "ok": True,
                "cohort_outlier": r.get("assumptions", {}).get("cohort_outlier", False),
                "_run_dir": r.get("_run_dir"),
                "momentum_quintile": None,    # filled in Phase 3
                "revision_direction": None,   # filled in Phase 3
            })
            n_screened += 1
            print(f"{r['rating']:<13} PT=${r['price_target_12m']:>6.0f}  ret={r['expected_return']*100:+.1f}%  [{conf}]")
        except Exception as e:
            print(f"FAILED: {e}")
            broken = {"rating": "BROKEN", "confidence": "UNKNOWN", "price_target_12m": 0.0, "expected_return": 0.0}
            state = update_state(ticker, broken, state)
            results.append({
                "ticker": ticker, "rating": "ERROR", "confidence": "?",
                "current_price": None, "price_target": None, "expected_return": None,
                "status": "ERROR", "ok": False, "error": str(e),
                "momentum_quintile": None, "revision_direction": None,
            })
            n_broken += 1

    # ─── Phase 2: Universe momentum (single batch) ───────────────────────────
    screened_tickers = [r["ticker"] for r in results
                        if r.get("ok") and r.get("status") not in ("SKIPPED", "ERROR")]
    if screened_tickers:
        print(f"\n  Computing 12m momentum for {len(tickers)} universe tickers...")
        momentum_data = compute_universe_momentum(tickers)
    else:
        momentum_data = {}

    # ─── Phase 3: Revisions + escalation ─────────────────────────────────────
    confidence_changes: list[dict] = []
    force_rescreen_list: list[str] = []

    if screened_tickers:
        print(f"  Computing analyst revisions + confidence escalation...")

    for entry in results:
        if not entry.get("ok") or entry.get("status") in ("SKIPPED", "ERROR"):
            # Carry forward momentum for skipped tickers (for display)
            if entry.get("status") == "SKIPPED":
                mom = momentum_data.get(entry["ticker"], {})
                entry["momentum_quintile"] = mom.get("quintile")
            continue

        ticker = entry["ticker"]
        conf_before = entry["confidence"]
        rating = entry["rating"]
        cohort_outlier = entry.get("cohort_outlier", False)

        # Momentum
        mom = momentum_data.get(ticker, {})
        quintile = mom.get("quintile")
        entry["momentum_quintile"] = quintile

        # Revisions
        rev = compute_revisions(ticker)
        direction = rev.get("direction", "NO_COVERAGE")
        entry["revision_direction"] = direction
        entry["revision_detail"] = rev

        # Alignment
        aligned, contradicting, neutral = get_signal_alignment(rating, quintile, direction)
        conf_after = apply_confidence_escalation(conf_before, aligned, contradicting, cohort_outlier)
        entry["confidence"] = conf_after
        entry["confidence_before"] = conf_before
        entry["alignment_score"] = f"+{len(aligned)} aligned, -{len(contradicting)} contradicted"

        if conf_after != conf_before:
            confidence_changes.append({
                "ticker": ticker, "rating": rating,
                "before": conf_before, "after": conf_after,
                "reason": entry["alignment_score"],
            })
            # Update cadence to reflect new confidence
            state[ticker]["last_confidence"] = conf_after
            next_due = compute_next_due(rating, conf_after, today)
            state[ticker]["next_due_date"] = str(next_due)

        # HOLD + sharp revision → force_rescreen next run
        if should_force_rescreen(rating, direction):
            force_rescreen_list.append(ticker)
            state[ticker]["force_rescreen"] = True

        # Update recommendation.json
        run_dir_str = entry.get("_run_dir")
        if run_dir_str:
            sig_list = build_signal_alignment_list(
                aligned, contradicting, neutral,
                rating, quintile, direction,
            )
            _update_recommendation_json(
                Path(run_dir_str), conf_after, conf_before, sig_list
            )

        # Append to signal log
        _log_signal(ticker, today, rating, conf_before, conf_after,
                    quintile, direction, len(aligned), len(contradicting))

    if force_rescreen_list or any(c["before"] != c["after"] for c in confidence_changes):
        save_state(state)

    # ─── Phase 4: Print summary table ────────────────────────────────────────

    # Sort: screened (by return desc) → skipped → errors
    def _sort_key(r):
        if r.get("status") == "ERROR":
            return (2, 0.0)
        if r.get("status") == "SKIPPED":
            return (1, -(r.get("expected_return") or 0))
        return (0, -(r.get("expected_return") or 0))

    results.sort(key=_sort_key)

    print()
    print("=" * 90)
    print(f"  SCREEN SUMMARY — {n_total} tickers  |  screened={n_screened}  skipped={n_skipped}  broken={n_broken}")
    print("=" * 90)

    hdr = f"  {'Ticker':<8} {'Status':<8} {'Rating':<14} {'Conf':<7} {'Mom':>4} {'Rev':>4} {'Price':>10} {'PT':>10} {'Return':>10}"
    print(hdr)
    print("  " + "-" * 87)

    for r in results:
        status = r.get("status", "DUE")
        if status == "SKIPPED" and not args.include_skipped:
            continue

        conf = r.get("confidence", "?")
        quintile = r.get("momentum_quintile")
        mom_str = str(quintile) if quintile is not None else "—"
        rev_dir = r.get("revision_direction")
        rev_str = revision_symbol(rev_dir) if rev_dir else "—"

        if status == "SKIPPED":
            ret_str = f"{r['expected_return']*100:+.1f}%" if r.get("expected_return") is not None else ""
            pt_str = f"${r['price_target']:>8.0f}" if r.get("price_target") else ""
            print(f"  {r['ticker']:<8} {status:<8} {r['rating']:<14} {conf:<7} {mom_str:>4} {rev_str:>4} {'':>10} {pt_str:>10} {ret_str:>10}")
        elif r.get("ok"):
            print(f"  {r['ticker']:<8} {status:<8} {r['rating']:<14} {conf:<7} {mom_str:>4} {rev_str:>4} "
                  f"${r['current_price']:>8.2f}  ${r['price_target']:>8.0f}  {r['expected_return']*100:>+8.1f}%")
        else:
            print(f"  {r['ticker']:<8} {'ERROR':<8} {'ERROR':<14}")

    # Distribution
    all_ratings = [
        r["rating"] for r in results
        if r.get("ok") and r.get("rating") not in ("?", "ERROR", None)
    ]
    dist = Counter(all_ratings)
    print()
    print("  Distribution (active + carried forward):")
    for rating in ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]:
        n = dist.get(rating, 0)
        print(f"    {rating:<13} {n:>2}  {'█' * n}")

    # Confidence changes from signal escalation
    if confidence_changes:
        n_up = sum(1 for c in confidence_changes if _TIERS_IDX.get(c["after"], 0) > _TIERS_IDX.get(c["before"], 0))
        n_down = sum(1 for c in confidence_changes if _TIERS_IDX.get(c["after"], 0) < _TIERS_IDX.get(c["before"], 0))
        print()
        print(f"  Confidence changes from signal escalation  (↑{n_up} escalated, ↓{n_down} degraded):")
        for c in sorted(confidence_changes, key=lambda x: x["ticker"]):
            arrow = "↑" if _TIERS_IDX.get(c["after"], 0) > _TIERS_IDX.get(c["before"], 0) else "↓"
            print(f"    {arrow} {c['ticker']:<6} {c['rating']:<14} {c['before']} → {c['after']}  ({c['reason']})")
    else:
        print()
        print("  No confidence changes from signal escalation this run.")

    if force_rescreen_list:
        print()
        print(f"  force_rescreen set for HOLD + sharp revision: {', '.join(sorted(force_rescreen_list))}")

    # Save summary
    with open(screen_dir / "summary.json", "w") as f:
        json.dump(
            {"timestamp": ts, "results": results,
             "stats": {"screened": n_screened, "skipped": n_skipped, "broken": n_broken},
             "confidence_changes": confidence_changes},
            f, indent=2, default=str,
        )
    print(f"\n  Summary saved → {screen_dir / 'summary.json'}")


_TIERS_IDX = {"BROKEN": 0, "LOW": 1, "MED": 2, "HIGH": 3}


if __name__ == "__main__":
    main()
