"""One-off operator action: trim Arm B's over-cap positions to MAX_SINGLE_POSITION.

Mechanical constitutional enforcement on the EXISTING book (not a strategy/mandate
change; does not touch the frozen prompt). Confirmed by the operator as a real defect
to fix on the aggressive arm's cash-accounting-fix-restated book (see
docs/PHAETHON_ARM_B_LEDGER_MEMO.md), not an intended outcome of the mandate.

What it does, in order:
  1. Restate the current book (src.phaethon.ledger.restate_book) — a no-op on a book
     already within cash, but keeps this on the same "restated book" the memo and the
     governance layer operate on.
  2. Compute weight_pct per holding (src.phaethon.scorecard), run trim_to_cap.
  3. For every trimmed ticker, reduce ITS SHARES so its dollar value matches the new
     capped weight exactly, and add the released dollars to cash. cost_basis/entry_price
     and every other per-holding field are left untouched — this is a partial sell, not
     a position rebuild.
  4. Archive the pre-trim published JSON, write the trimmed book back to the real
     trader-state file, then re-publish via the governed pipeline (src.phaethon.publish)
     so the dashboard picks up restated + governed + trimmed output in one render.

Nothing here touches Arm A or the trader's strategy/proposal code.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.io_utils import atomic_write_text
from src.phaethon.ledger import restate_book
from src.phaethon.rebalance import trim_to_cap
from src.phaethon.scorecard import total_value, holdings_view

STATE_DIR = Path("/home/phaethon/phaethon/trader_b/state")
BOOK_PATH = STATE_DIR / "book.json"
LIVE_JSON = _ROOT / "docs" / "data" / "phaethon_b_live.json"
CAP = 0.10


def main() -> int:
    today = date.today().isoformat()

    book = json.loads(BOOK_PATH.read_text())
    restated, rejected = restate_book(book)
    if rejected:
        print(f"NOTE: restate rejected {len(rejected)} over-cash order(s): "
              f"{[r['ticker'] for r in rejected]}")

    tv_before = total_value(restated)
    holdings = holdings_view(restated, "B", tv_before)
    trimmed_view, released_pct, trim_log = trim_to_cap(holdings, cap=CAP)

    if not trim_log:
        print("Nothing over cap — no trim needed.")
        return 0

    print(f"Total portfolio value: ${tv_before:,.2f}")
    print(f"Positions over {CAP*100:.0f}% cap: {[e['ticker'] for e in trim_log]}")

    # 3. Apply the trim to the real book: reduce shares of each over-cap ticker so its
    # dollar value matches the capped weight exactly; add the released dollars to cash.
    # tv is conserved (frictionless, matching every other calc in this codebase — no
    # transaction-cost model exists anywhere in the frozen strategy/render layer).
    new_holdings = dict(restated["holdings"])
    new_cash = restated["cash"]
    for entry in trim_log:
        t = entry["ticker"]
        h = dict(new_holdings[t])
        target_value = CAP * tv_before
        released_dollars = h["shares"] * h["last_price"] - target_value
        h["shares"] = round(target_value / h["last_price"], 6)
        new_holdings[t] = h
        new_cash += released_dollars
        entry["released_dollars"] = round(released_dollars, 2)
        print(f"  {t}: {entry['before_pct']}% -> {entry['after_pct']}% "
              f"(released ${released_dollars:,.2f})")

    new_cash = round(new_cash, 2)
    new_book = {**restated, "cash": new_cash, "holdings": new_holdings}
    tv_after = total_value(new_book)
    print(f"Total portfolio value post-trim: ${tv_after:,.2f} "
          f"(conserved: {'yes' if abs(tv_after - tv_before) < 0.01 else 'NO — ' + str(tv_after - tv_before)})")
    print(f"cash_pct post-trim: {new_cash / tv_after * 100:.2f}%")

    # 4a. Archive the pre-trim published JSON — nothing silently overwritten.
    archive_path = _ROOT / "docs" / "data" / "archive" / f"phaethon_b_live_pre_trim_{today}.json"
    if LIVE_JSON.exists():
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(archive_path, LIVE_JSON.read_text())
        print(f"Archived pre-trim state -> {archive_path}")

    # 4b. Write the trimmed book back to the real trader-state file (source of truth for
    # every future publish/propose cycle — this must stick past the next cron run).
    atomic_write_text(BOOK_PATH, json.dumps(new_book, indent=2))
    print(f"Wrote trimmed book -> {BOOK_PATH}")

    # Save the trim log for the publish step to attach to the arm JSON.
    trim_meta = {
        "trim_note": f"trimmed {today} — " + "; ".join(
            f"{e['ticker']} reduced {e['before_pct']}% -> {e['after_pct']}%" for e in trim_log
        ) + ", excess released to cash",
        "trim_log": trim_log,
    }
    (STATE_DIR / "_pending_trim_meta.json").write_text(json.dumps(trim_meta, indent=2))
    print("Wrote trim metadata for the publish step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
