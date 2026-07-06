#!/usr/bin/env python3
"""Operator entry point for the live kill switch — the /kill and /confirm_resume handlers.

The KILL file is the single source of truth (works with Telegram down): this CLI writes/
reads it. Engaging kills all PENDING cards and alerts. Reset is two deliberate steps, each
requiring a reason: `confirm-resume <reason>` (step 1, logged) AND manual deletion of
data/live/KILL (step 2). A terminal (cumulative-breach) kill additionally refuses resume
until POST_MORTEM_PATH in live_limits.yaml points at a completed post-mortem.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live import breakers, kill
from src.live.limits import load_live_limits


def _alert(text: str, dry: bool) -> None:
    if dry:
        print(text)
    else:
        from src.telegram.client import send_message
        send_message(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Live kill switch operator control.")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("engage", help="/kill — engage the kill switch (writes data/live/KILL)")
    e.add_argument("reason")
    e.add_argument("--terminal", action="store_true", help="terminal (cumulative-breach) kill")

    r = sub.add_parser("confirm-resume", help="/confirm_resume — step 1 of the two-step reset")
    r.add_argument("reason")

    w = sub.add_parser("clear-weekly", help="clear HALT_WEEKLY (reason-gated, two-step with manual deletion)")
    w.add_argument("reason")

    sub.add_parser("status", help="show kill / halt state")
    a = ap.parse_args(argv)

    if a.cmd == "engage":
        kill.engage_kill(a.reason, terminal=a.terminal)
        killed = kill.kill_all_pending()
        _alert(f"⛔ KILL ENGAGED{' (TERMINAL)' if a.terminal else ''} — {a.reason}. "
               f"{len(killed)} PENDING card(s) → KILLED. Card generation refuses until reset.", a.dry_run)
        print(f"engaged; {len(killed)} pending → KILLED")
        return 0

    if a.cmd == "confirm-resume":
        try:
            kill.confirm_resume(a.reason, limits=load_live_limits())
        except ValueError as ex:
            print(f"refused: {ex}", file=sys.stderr)
            return 1
        _alert(f"↩️ /confirm_resume logged — {a.reason}. Step 1 of 2 done. "
               f"Now MANUALLY delete data/live/KILL to complete the reset.", a.dry_run)
        print("confirm-resume logged; now manually delete data/live/KILL (step 2)")
        return 0

    if a.cmd == "clear-weekly":
        if not a.reason.strip():
            print("refused: clear-weekly requires a reason", file=sys.stderr); return 1
        if breakers.HALT_WEEKLY.exists():
            breakers.HALT_WEEKLY.unlink()
        _alert(f"↩️ HALT_WEEKLY cleared — {a.reason}.", a.dry_run)
        print("weekly halt cleared")
        return 0

    # status
    blocked, why = kill.kill_block()
    print(f"kill        : {'BLOCKED — ' + why if blocked else 'clear'}")
    print(f"KILL file   : {'present' if kill.is_killed() else 'absent'}")
    print(f"HALT_DAILY  : {'set (today)' if breakers.is_daily_halted() else 'clear'}")
    print(f"HALT_WEEKLY : {'set' if breakers.is_weekly_halted() else 'clear'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
