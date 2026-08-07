"""Phaethon publish orchestration — assemble governed per-arm JSON from trader state.

This is the repo-owned logic the thin cron wrapper (scripts/phaethon/publish.sh) calls.
It renders the scorecard (frozen), runs governance (surfacing NONCONFORMING), tags
cohorts, enforces the leakage sanitize gate, and writes the arm JSON. Git push stays
in the shell wrapper.

CRITICAL (NO_LIVE_PNL_LEARNING firewall): nothing in this package reads live P&L / fills
artifacts, and nothing here is on any LLM prompt-construction path. It only renders
already-computed scorecard/holdings state. Enforced by tests/test_constitutional_guards.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts._common import get_print
from src.io_utils import atomic_write_text
from datetime import date

from src.phaethon.scorecard import render_arm
from src.phaethon.governance import run_governance
from src.phaethon.schema import validate_phaethon_holding
from src.phaethon.ledger import restate_book

print = get_print(__file__)  # noqa: A001

_ROOT = Path(__file__).resolve().parent.parent.parent

# Leakage sanitize gate — verbatim from the droplet publisher: refuse to publish if any
# personal/real-account term appears in the rendered JSON.
SANITIZE_RE = re.compile(
    r"moneybox|trading ?212|t212|gardiner|live\.co|gmail|£|real.account|real.holding|sipp|\bisa\b",
    re.IGNORECASE)


def sanitize_findings(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in SANITIZE_RE.finditer(text)})


def assemble_arm(scorecard: dict, book: dict, arm: str, screener_settings: dict,
                 constitution: dict, mcap_fetch=None, check_mcap: bool = True,
                 as_of: str | None = None, restate: bool = True,
                 trim_note: str | None = None, trim_log: list | None = None) -> dict:
    """Render one arm + attach governance status + validate cohort tags. Pure-ish.

    restate=True applies the cash-accounting fix (src/phaethon/ledger.restate_book):
    over-cash buys are rejected so cash_pct ∈ [0,100%] and gross ≤ 100%. The output is
    marked 'restated' with the rejected orders and the original figures preserved by the
    caller (archive). A within-cash book is unchanged (no false rejections).

    trim_note/trim_log are set only by the one-off operator trim action (see
    scripts/phaethon/trim_arm_b_to_cap.py) — on every normal daily publish both are
    None and the output is byte-identical to before this parameter existed."""
    rejected = []
    if restate:
        book, rejected = restate_book(book)
    arm_json = render_arm(scorecard, book, arm, as_of=as_of)
    if restate:
        arm_json["restated"] = f"restated {as_of or date.today().isoformat()}, cash-accounting bug fixed"
        arm_json["restated_rejected_over_cash"] = rejected
        arm_json["n_positions"] = len(arm_json["holdings"])   # reflect the corrected book
    if trim_note is not None:
        arm_json["trimmed"] = trim_note
        arm_json["trim_log"] = trim_log or []
    gov = run_governance(arm_json["holdings"], screener_settings, constitution,
                         mcap_fetch=mcap_fetch, check_mcap=check_mcap)
    arm_json["status"] = gov["status"]                       # drives the red banner
    arm_json["governance"] = {
        "conforming": gov["conforming"], "violations": gov["violations"],
        "gross_exposure_pct": gov["gross_exposure_pct"],
    }
    for h in arm_json["holdings"]:
        validate_phaethon_holding(h)
    return arm_json


def _alert_nonconforming(arm: str, status: str) -> None:
    try:
        from src.telegram.client import send_message
        send_message(f"⚠️ Phaethon arm {arm}: {status}")
    except Exception as e:
        print(f"  telegram alert skipped: {e}")


def _load_state(state_dir: Path) -> tuple[dict, dict]:
    sc = json.loads((state_dir / "scorecard_public.json").read_text())
    bk = json.loads((state_dir / "book.json").read_text())
    return sc, bk


def _load_pending_trim(state_dir: Path) -> tuple[str | None, list | None]:
    """One-off trim metadata written by scripts/phaethon/trim_arm_b_to_cap.py, if any.
    Consumed (deleted) after a successful publish — applied to exactly one render."""
    p = state_dir / "_pending_trim_meta.json"
    if not p.exists():
        return None, None
    meta = json.loads(p.read_text())
    return meta.get("trim_note"), meta.get("trim_log")


def publish_arm(state_dir: Path, arm: str, out_path: Path, screener_settings: dict,
                constitution: dict) -> int:
    sc, bk = _load_state(state_dir)
    trim_note, trim_log = _load_pending_trim(state_dir)
    arm_json = assemble_arm(sc, bk, arm, screener_settings, constitution,
                            trim_note=trim_note, trim_log=trim_log)
    text = json.dumps(arm_json, indent=2)

    leaks = sanitize_findings(text)
    if leaks:
        print(f"  ABORT arm {arm} — personal/account data present ({', '.join(leaks)}); NOT writing")
        return 1

    atomic_write_text(out_path, text)
    if trim_note is not None:
        (state_dir / "_pending_trim_meta.json").unlink(missing_ok=True)
        print(f"  arm {arm}: trim applied and consumed — {trim_note}")
    if not arm_json["governance"]["conforming"]:
        print(f"  arm {arm}: {arm_json['status']}")
        _alert_nonconforming(arm, arm_json["status"])
    else:
        print(f"  arm {arm}: CONFORMING")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble governed Phaethon arm JSON (repo-owned).")
    ap.add_argument("--state-a", type=Path, default=Path("/home/phaethon/phaethon/trader/state"))
    ap.add_argument("--state-b", type=Path, default=Path("/home/phaethon/phaethon/trader_b/state"))
    args = ap.parse_args()

    settings = yaml.safe_load((_ROOT / "config" / "settings.yaml").read_text()) or {}
    screener = settings.get("screener", {})
    constitution = yaml.safe_load((_ROOT / "config" / "constitution.yaml").read_text()) or {}
    data = _ROOT / "docs" / "data"
    data.mkdir(parents=True, exist_ok=True)

    rc = 0
    rc |= publish_arm(args.state_a, "A", data / "phaethon_live.json", screener, constitution)
    rc |= publish_arm(args.state_b, "B", data / "phaethon_b_live.json", screener, constitution)
    return rc


if __name__ == "__main__":
    sys.exit(main())
