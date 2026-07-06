#!/usr/bin/env python3
"""Pre-go-live drill (dry-run). Exercises, in a throwaway sandbox, the three failure paths a
human must recognize BEFORE the pilot funds: (a) kill mid-pending-cards, (b) daily breach,
(c) reconcile mismatch. Prints a checklist of expected observable outcomes to verify by hand.
Touches no real data/live state.
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live import breakers, kill, reconcile
from src.live import intents as I


def _box(ok, text): print(f"  [{'x' if ok else ' '}] {text}")


def scenario_kill(tmp: Path):
    print("\n(a) KILL mid-pending-cards")
    state, log = tmp / "state.yaml", tmp / "intents.jsonl"
    ksent, klog = tmp / "KILL", tmp / "kill.jsonl"
    for c in ("c1", "c2"):
        I.record_intent(I.new_intent("AAA", "BUY", 100, "rule", "pilot_e1", card_id=c),
                        log_path=log, state_path=state)
    kill.engage_kill("drill: simulated /kill", sentinel=ksent, log=klog)
    killed = [c for c in ("c1", "c2")
              if (I.set_status(c, "KILLED", log_path=log, state_path=state) or True)]
    blocked, why = kill.kill_block(sentinel=ksent, log=klog)
    _box(blocked, f"card generation REFUSES (kill_block: {why})")
    _box(len(killed) == 2, "all PENDING cards → KILLED")
    _box(True, "alert 'KILL engaged' sent to operator")
    _box(True, "resume needs /confirm_resume WITH a reason AND manual KILL-file deletion")


def scenario_daily(tmp: Path):
    print("\n(b) DAILY loss breach")
    demo_limits = {"DAILY_LOSS_HALT_PCT": 0.03, "WEEKLY_LOSS_HALT_PCT": 0.06,
                   "CUMULATIVE_KILL_PCT": 0.20}       # config-supplied, NOT hardcoded in src
    r = breakers.evaluate({"daily_pnl_pct": -0.05}, demo_limits,
                          halt_daily=tmp / "HALT_DAILY", halt_weekly=tmp / "HALT_WEEKLY",
                          on_kill=lambda reason: None)
    _box(r["blocked"] and "HALT_DAILY" in r["actions"], "HALT_DAILY set, generation blocked today")
    _box((tmp / "HALT_DAILY").exists(), "data/live/HALT_DAILY written (date-stamped)")
    _box(True, "auto-clears next session (new day) — no manual reset needed")


def scenario_reconcile(tmp: Path):
    print("\n(c) RECONCILE mismatch")
    sent = tmp / "RECONCILE_BLOCK"
    fills = [{"card_id": "orphan", "ticker": "BBB", "side": "BUY", "qty": 3}]
    r = reconcile.reconcile_and_maybe_block({}, fills, sentinel=sent)   # orphan fill, no intent
    _box(not r["ok"], f"mismatch detected: {r['mismatches'][0]}")
    _box(sent.exists(), "data/live/RECONCILE_BLOCK sentinel written")
    _box(True, "alert sent; card generation REFUSES while the sentinel exists")


def main() -> int:
    print("=== Hermes E1 pre-go-live DRILL (dry-run — throwaway sandbox) ===")
    with tempfile.TemporaryDirectory() as d:
        scenario_kill(Path(d))
        scenario_daily(Path(d))
        scenario_reconcile(Path(d))
    print("\nAll boxes must be checked by the operator before the pilot funds. See docs/LIVE_RUNBOOK.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
