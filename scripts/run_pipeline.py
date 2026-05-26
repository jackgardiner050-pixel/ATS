#!/usr/bin/env python3
"""CLI entry point — run the full research pipeline for one ticker.

Usage:
    python scripts/run_pipeline.py AGX
    python scripts/run_pipeline.py AGX --price 700 --shares 14.0
    python scripts/run_pipeline.py PWR --consensus-low 350 --consensus-high 410

Environment:
    EDGAR_IDENTITY  required, e.g. "Your Name your@email.com"
"""
import argparse
import sys
from pathlib import Path

# Allow running from agent/ root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestrator import run_pipeline


def main():
    p = argparse.ArgumentParser(description="Equity research agent — single-ticker deep dive")
    p.add_argument("ticker", help="Ticker symbol (e.g. AGX)")
    p.add_argument("--price", type=float, help="Override current price (skips yfinance)")
    p.add_argument("--shares", type=float, help="Override diluted shares in millions")
    p.add_argument("--consensus-low", type=float, help="Sell-side consensus PT low")
    p.add_argument("--consensus-high", type=float, help="Sell-side consensus PT high")
    p.add_argument("--peer-ev-ebitda-median", type=float, default=None)
    p.add_argument("--peer-ev-ebitda-p75", type=float, default=None)
    p.add_argument("--peer-pe-median", type=float, default=None)
    p.add_argument("--output-root", type=Path, default=Path("runs"))
    args = p.parse_args()

    consensus_range = None
    if args.consensus_low is not None and args.consensus_high is not None:
        consensus_range = (args.consensus_low, args.consensus_high)

    # Only pass peer_multiples if explicitly overridden on CLI; otherwise let
    # the orchestrator auto-resolve via yfinance peer data.
    peer_multiples = None
    if args.peer_ev_ebitda_median is not None:
        peer_multiples = {
            "median_ev_ebitda": args.peer_ev_ebitda_median,
            "p75_ev_ebitda": args.peer_ev_ebitda_p75 or 20.0,
            "median_pe": args.peer_pe_median or 25.0,
        }

    result = run_pipeline(
        ticker=args.ticker,
        output_root=args.output_root,
        override_price=args.price,
        override_shares_mm=args.shares,
        peer_multiples=peer_multiples,
        consensus_range=consensus_range,
    )

    print()
    print("=" * 60)
    print(f"  {result['ticker']} — {result['rating']}")
    print(f"  Price target 12-mo:  ${result['price_target_12m']:.0f}")
    print(f"  Current price:       ${result['current_price']:.2f}")
    print(f"  Expected return:     {result['expected_return']*100:+.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
