#!/usr/bin/env python3
"""CLI: record a human-reported fill (mirrors the Telegram /fill reply handler)."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live.fills import record_fill


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record a fill for an order card.")
    ap.add_argument("card_id"); ap.add_argument("price", type=float); ap.add_argument("qty", type=float)
    ap.add_argument("--decision-price", type=float, default=None)
    ap.add_argument("--card-price", type=float, default=None)
    a = ap.parse_args(argv)
    try:
        f = record_fill(a.card_id, a.price, a.qty, decision_price=a.decision_price, card_price=a.card_price)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    print(f"recorded: {f['side']} {f['qty']} {f['ticker']} @ {f['price']} (card {a.card_id}) → FILLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
