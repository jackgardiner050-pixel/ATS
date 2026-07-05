#!/usr/bin/env python3
"""Universe liveness check — flag delisted / renamed tickers before a screen run.

For every ticker referenced in `config/universe.yaml` (the screen universe) and
`config/peer_groups.yaml` (peer cohorts), verify that yfinance returns a
non-empty 5-day price history. Tickers that return nothing are almost always
delisted (acquired, merged, bankrupt) or renamed — the screener would later fail
on them, so we surface them here first.

Warn-only by design: this never exits non-zero for suspects, so it can sit ahead
of the screen in run_weekly.sh without ever blocking the pipeline. (It exits
non-zero only on an internal error, e.g. a missing config file.)

Usage:
    python scripts/check_universe_liveness.py
    python scripts/check_universe_liveness.py --tickers SUMQ,AGX   # explicit list
    python scripts/check_universe_liveness.py --universe-only       # skip peers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Iterable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = _ROOT / "config" / "universe.yaml"
PEER_GROUPS_PATH = _ROOT / "config" / "peer_groups.yaml"


# ─── Ticker collection ───────────────────────────────────────────────────────

def load_universe_tickers(path: Path = UNIVERSE_PATH) -> list[str]:
    """Tickers listed under `universe:` in universe.yaml."""
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return [t.upper() for t in (cfg.get("universe") or [])]


def load_peer_tickers(path: Path = PEER_GROUPS_PATH) -> list[str]:
    """Every ticker that appears in peer_groups.yaml — both cohort keys and peers.

    Peers can include names not in the screen universe, so this is a superset.
    """
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    groups = cfg.get("peer_groups") or {}
    seen: set[str] = set()
    for key, peers in groups.items():
        seen.add(str(key).upper())
        for p in (peers or []):
            seen.add(str(p).upper())
    return sorted(seen)


def collect_tickers(universe_only: bool = False) -> list[str]:
    """Deduplicated, sorted union of universe + peer-group tickers."""
    tickers = set(load_universe_tickers())
    if not universe_only:
        tickers |= set(load_peer_tickers())
    return sorted(tickers)


# ─── Liveness probe ──────────────────────────────────────────────────────────

def _default_fetch(ticker: str) -> bool:
    """True if yfinance returns a non-empty 5d history for `ticker`.

    Any exception (network, unknown symbol) is treated as "not live" — the point
    of this check is precisely to surface names yfinance can't price.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d")
        return hist is not None and not hist.empty
    except Exception:
        return False


def check_liveness(
    tickers: Iterable[str],
    fetch: Callable[[str], bool] = _default_fetch,
) -> tuple[list[str], list[str]]:
    """Split tickers into (live, suspects) using `fetch`.

    `fetch(ticker) -> bool` is injectable so tests can run without yfinance.
    A suspect is any ticker for which fetch returns falsy.
    """
    live: list[str] = []
    suspects: list[str] = []
    for t in tickers:
        (live if fetch(t) else suspects).append(t)
    return live, suspects


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Flag delisted/renamed tickers (warn-only).")
    p.add_argument("--tickers", type=str, default=None,
                   help="Comma-separated ticker list; overrides config files")
    p.add_argument("--universe-only", action="store_true",
                   help="Check only universe.yaml, skip peer_groups.yaml")
    args = p.parse_args()

    if args.tickers:
        tickers = sorted({t.strip().upper() for t in args.tickers.split(",") if t.strip()})
    else:
        tickers = collect_tickers(universe_only=args.universe_only)

    print(f"Checking liveness of {len(tickers)} tickers (5d yfinance history)...")
    live, suspects = check_liveness(tickers)

    print(f"live={len(live)}  suspects={len(suspects)}")
    if suspects:
        print("WARN: no 5d history returned for the following tickers "
              "(likely delisted/renamed — verify before next screen):")
        for t in suspects:
            print(f"  - {t}")
    else:
        print("All tickers returned price history. No delisted/renamed suspects.")

    # Warn-only: never block the pipeline on suspects.
    return 0


if __name__ == "__main__":
    sys.exit(main())
