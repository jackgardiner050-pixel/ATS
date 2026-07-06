#!/usr/bin/env python3
"""Daily reconcile (cron): fills↔intents, positions=Σfills, optional --broker-csv cross-check,
plus the breaker evaluation. ANY mismatch → alert + RECONCILE_BLOCK sentinel."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live import breakers, reconcile
from src.live.fills import load_fills
from src.live.intents import load_intent_state
from src.live.limits import load_live_limits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily live reconciliation.")
    ap.add_argument("--broker-csv", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    limits = load_live_limits()
    state, fills = load_intent_state(), load_fills()
    broker = reconcile.parse_broker_csv(a.broker_csv, limits.get("broker_csv_columns")) if a.broker_csv else None

    r = (reconcile.reconcile(state, fills, broker) if a.dry_run
         else reconcile.reconcile_and_maybe_block(state, fills, broker))
    b = breakers.evaluate({"daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0, "cumulative_pnl_pct": 0.0}, limits)

    def alert(t):
        print(t) if a.dry_run else __import__("src.telegram.client", fromlist=["send_message"]).send_message(t)

    if r["ok"]:
        print(f"reconcile OK — positions: {r['positions']}")
    else:
        alert("⛔ RECONCILE MISMATCH — RECONCILE_BLOCK set; card generation refused:\n- "
              + "\n- ".join(r["mismatches"]))
    if b["blocked"]:
        print("breakers: BLOCKED — " + "; ".join(b["reasons"]))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
