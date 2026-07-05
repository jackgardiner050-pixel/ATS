#!/usr/bin/env python3
"""Hypothesis registry CLI — the honesty dashboard + append-only ledger.

  registry.py new                     # interactive; refuses without all fields
  registry.py status <id> <STATUS>    # append a status event; never edits
  registry.py stats                   # m, current Bonferroni alpha, pass rate
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.research.registry import (
    add_entry, advance_status, load_registry, registry_stats,
    IMMUTABLE_FIELDS, VALID_STATUS,
)

_PROMPTS = {
    "id": "id", "created": "created (YYYY-MM-DD)",
    "hypothesis": "hypothesis (one testable sentence)",
    "mechanism": "mechanism (who is the counterparty / why the edge exists)",
    "universe": "universe", "window": "window", "metric": "metric",
    "threshold": "threshold", "analysis_plan_sha": "analysis_plan_sha (sha256 of frozen plan doc)",
}


def cmd_new(args) -> int:
    print("Register a new hypothesis — every field is required (blank aborts).")
    fields = {}
    for k in IMMUTABLE_FIELDS:
        v = input(f"  {_PROMPTS[k]}: ").strip()
        if not v:
            print(f"REFUSED: '{k}' is required — a hypothesis cannot be registered without it.",
                  file=sys.stderr)
            return 1
        fields[k] = v
    fields["status"] = "REGISTERED"
    try:
        e = add_entry(fields)
    except ValueError as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 1
    print(f"registered {e['id']} (content_hash {e['content_hash'][:12]}…)")
    return 0


def cmd_status(args) -> int:
    try:
        e = advance_status(args.id, args.new_status, result_ref=args.result_ref,
                           ts=datetime.now(timezone.utc).isoformat())
    except ValueError as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 1
    print(f"{args.id} → {e['status']}")
    return 0


def cmd_stats(args) -> int:
    s = registry_stats(load_registry())
    print(f"m (hypotheses ever)  : {s['m']}")
    print(f"Bonferroni alpha     : {s['alpha']}")
    print(f"pass rate (resolved) : {s['pass_rate']:.2%} ({s['passed']}/{s['resolved']})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hypothesis registry — honesty dashboard.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new", help="register a new hypothesis (interactive)").set_defaults(fn=cmd_new)
    ps = sub.add_parser("status", help="advance an entry's status (append-only)")
    ps.add_argument("id")
    ps.add_argument("new_status", choices=VALID_STATUS)
    ps.add_argument("--result-ref", default=None)
    ps.set_defaults(fn=cmd_status)
    sub.add_parser("stats", help="print m, alpha, pass rate").set_defaults(fn=cmd_stats)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
