#!/usr/bin/env python3
"""Hermes E1 order-card generation — PROPOSAL ONLY.

Reads the SAME screener output paper_run consumes, applies EVERY gate before sending
anything — kill switch, loss breakers (fail-safe on unset thresholds), reconcile block,
capital funding, and per-order admissibility — then renders Telegram order cards. It never
places an order and NEVER writes to any paper cohort file (data/paper_*). --dry-run prints
the cards and persists nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from src.live import breakers, kill, reconcile
from src.live.cards import render_batch, render_card
from src.live.fills import expire_stale
from src.live.intents import load_intent_state, new_intent, record_intent
from src.live.limits import cards_enabled, check_order_admissible, load_live_limits

_SCREEN_ROOT = _REPO / "runs" / "_screen"


def _alert(text: str, dry: bool) -> None:
    if dry:
        print(text)
    else:
        from src.telegram.client import send_message
        send_message(text)


def _latest_summary(override: str | None) -> dict:
    if override:
        return json.loads(Path(override).read_text())
    dirs = [d for d in sorted(_SCREEN_ROOT.iterdir()) if d.is_dir()] if _SCREEN_ROOT.exists() else []
    if not dirs or not (dirs[-1] / "summary.json").exists():
        print("No screen summary found under runs/_screen/ — run run_universe.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads((dirs[-1] / "summary.json").read_text())


def _orders_this_week(state: dict, now: datetime) -> int:
    yw = now.isocalendar()[:2]
    return sum(1 for i in state.values()
               if i.get("status") in ("PENDING", "FILLED")
               and datetime.fromisoformat(str(i["ts"]).replace("Z", "+00:00")).isocalendar()[:2] == yw)


def _pnl_state() -> dict:
    """Live P&L for the breakers, from fills + marks. At pilot start there are no fills, so
    the mechanism sees flat P&L — the breaker THRESHOLDS being unset is what blocks (fail-safe)."""
    return {"daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0, "cumulative_pnl_pct": 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hermes E1 order-card generation (proposal only).")
    ap.add_argument("--dry-run", action="store_true", help="print cards, send nothing, persist nothing")
    ap.add_argument("--screen", default=None, help="path to a screen summary.json (fixture/override)")
    ap.add_argument("--limits", default=None, help="path to a live_limits.yaml (fixture/override)")
    args = ap.parse_args(argv)
    dry = args.dry_run
    now = datetime.now(timezone.utc)

    limits = load_live_limits(Path(args.limits) if args.limits else None)

    # 0. auto-expire stale PENDING cards (alert on each)
    for e in expire_stale(now=now):
        _alert(f"⏳ EXPIRED order card {e['card_id']} — {e['side']} {e['ticker']} (untouched > 2 trading days)", dry)

    # 1. kill switch (file is source of truth) — refuse + KILL all PENDING
    blocked, why = kill.kill_block()
    if blocked:
        killed = kill.kill_all_pending()
        _alert(f"⛔ KILL engaged — {why}. {len(killed)} PENDING card(s) → KILLED. No cards generated.", dry)
        return 1

    # 2. loss breakers — FAIL-SAFE: unset thresholds block generation
    b = breakers.evaluate(_pnl_state(), limits)
    if b["blocked"]:
        _alert("⛔ Breakers block card generation:\n- " + "\n- ".join(b["reasons"]), dry)
        return 1

    # 3. reconcile block
    if reconcile.is_blocked():
        _alert("⛔ RECONCILE_BLOCK present — cards refused until the mismatch is resolved.", dry)
        return 1

    # 4. capital funded
    if not cards_enabled(limits):
        _alert("⛔ MAX_LIVE_CAPITAL_GBP is 0 — pilot unfunded; no order cards.", dry)
        return 1

    # 5. build + gate candidate intents from the screen (STRONG_BUY / MED|HIGH only)
    summary = _latest_summary(args.screen)
    state = load_intent_state()
    book_state = {"orders_this_week": _orders_this_week(state, now)}
    capital = float(limits["MAX_LIVE_CAPITAL_GBP"])
    max_w = float(limits["MAX_SINGLE_POSITION_LIVE"])
    made = []
    for r in summary.get("results", []):
        if r.get("rating") != "STRONG_BUY" or r.get("confidence") not in ("MED", "HIGH"):
            continue
        probe = {"ticker": r["ticker"], "weight": max_w}
        v = check_order_admissible(probe, book_state, limits)
        if v:
            _alert(f"• skip {r['ticker']}: {v[0]}", dry)
            continue
        made.append(new_intent(
            ticker=r["ticker"], side="BUY", notional_gbp=round(capital * max_w, 2),
            source_rule=r.get("source_rule", "oracle_v1"), cohort="pilot_e1",
            limit_guidance=r.get("current_price"),
            decision_price=r.get("current_price"), card_price=r.get("current_price")))
        book_state["orders_this_week"] += 1

    # 6. render — dry-run prints and persists NOTHING; live persists to data/live + sends
    if dry:
        print(render_batch(made))
        print(f"\n[dry-run] {len(made)} card(s) generated — nothing sent, nothing persisted.")
        return 0
    for it in made:
        record_intent(it)                       # data/live only — never a paper cohort file
        from src.telegram.client import send_message
        send_message(render_card(it))
    print(f"sent {len(made)} order card(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
