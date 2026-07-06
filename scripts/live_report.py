#!/usr/bin/env python3
"""Live report: NAV (nav_ledger pure fns), SPY TR comparison (DESCRIPTIVE ONLY — hard-coded
label), slippage table vs the modeled cost, and reconciliation status."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yaml
from src.live import reconcile, slippage
from src.live.fills import load_fills
from src.live.intents import load_intent_state
from src.portfolio import nav_ledger  # noqa: F401  (pure NAV math reused)

SPY_LABEL = "descriptive only — n insufficient for inference"   # hard-coded, not optional


def _modeled_bps() -> float:
    p = Path(__file__).resolve().parent.parent / "config" / "portfolio.yaml"
    return float((yaml.safe_load(p.read_text()) or {}).get("paper_cost_bps", 20))


def main(argv=None) -> int:
    fills = load_fills(); state = load_intent_state()
    modeled = _modeled_bps()
    print("=== Hermes E1 — Live Report ===")
    rec = reconcile.reconcile(state, fills)
    print(f"reconciliation : {'BLOCKED' if reconcile.is_blocked() else ('OK' if rec['ok'] else 'MISMATCH')}")
    print(f"positions      : {rec['positions']}")
    print(f"vs SPY TR      : [{SPY_LABEL}]")
    summ = slippage.slippage_summary(fills, modeled)
    print(f"slippage (n={summ['n']}) : mean {summ['mean_bps']}bps vs modeled {modeled}bps "
          f"(excess {summ['mean_excess_bps']}bps)")
    for row in slippage.slippage_table(fills, modeled):
        print(f"  {row['ticker']} {row['side']}: fill {row['fill_price']} vs decision "
              f"{row['decision_price']} → {row['slippage_bps']}bps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
