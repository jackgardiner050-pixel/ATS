"""Hermes E1 lifecycle: intent → card → fill → reconcile → NAV; expiry; reconcile-block;
and the filesystem sandbox — no src/live code path writes to data/paper_*."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.live import reconcile, slippage
from src.live.cards import render_card
from src.live.fills import expire_stale, load_fills, record_fill
from src.live.intents import load_intent_state, new_intent, record_intent
from src.portfolio import nav_ledger

ROOT = Path(__file__).parent.parent


def _p(tmp):
    return tmp / "intents.jsonl", tmp / "state.yaml", tmp / "fills.jsonl"


def test_full_lifecycle(tmp_path):
    log, state, fills_log = _p(tmp_path)
    it = new_intent("AAPL", "BUY", 1000, "oracle_v1", "pilot_e1", limit_guidance=190.0,
                    decision_price=190.0, card_price=190.0, card_id="C1")
    record_intent(it, log_path=log, state_path=state)

    card = render_card(it)
    assert "C1" in card and "/fill C1 <price> <qty>" in card and "PROPOSAL ONLY" in card

    f = record_fill("C1", 191.0, 5, fills_log=fills_log, state_path=state, intents_log=log)
    assert f["side"] == "BUY" and f["qty"] == 5
    assert load_intent_state(state)["C1"]["status"] == "FILLED"

    r = reconcile.reconcile(load_intent_state(state), load_fills(fills_log))
    assert r["ok"] and r["positions"] == {"AAPL": 5.0}

    assert nav_ledger.max_drawdown([100.0, 110.0, 99.0]) > 0          # nav_ledger pure fn reused
    row = slippage.slippage_row(f, 20.0)
    assert row["slippage_bps"] > 0                                    # BUY 191 vs decision 190 = adverse
    print("  ✓ intent→card→fill→reconcile→NAV lifecycle")


def test_pending_card_expires_after_two_trading_days(tmp_path):
    log, state, _ = _p(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    record_intent(new_intent("X", "BUY", 100, "r", "pilot_e1", ts=old, card_id="OLD"),
                  log_path=log, state_path=state)
    expired = expire_stale(state_path=state, intents_log=log)
    assert [e["card_id"] for e in expired] == ["OLD"]
    assert load_intent_state(state)["OLD"]["status"] == "EXPIRED"
    print("  ✓ PENDING > 2 trading days → EXPIRED")


def test_reconcile_block_and_clear(tmp_path):
    sent = tmp_path / "RECONCILE_BLOCK"
    r = reconcile.reconcile_and_maybe_block(
        {}, [{"card_id": "orphan", "ticker": "B", "side": "BUY", "qty": 1}], sentinel=sent)
    assert not r["ok"] and sent.exists() and reconcile.is_blocked(sent)
    with pytest.raises(ValueError):
        reconcile.clear_block("", sentinel=sent)               # needs a reason
    assert reconcile.clear_block("resolved by hand", sentinel=sent) and not reconcile.is_blocked(sent)
    print("  ✓ mismatch → RECONCILE_BLOCK; clear requires a reason")


def test_src_live_never_touches_paper_cohort_files():
    for p in (ROOT / "src" / "live").glob("*.py"):
        t = p.read_text()
        for banned in ("paper_positions", "paper_trades", "data/paper"):
            assert banned not in t, f"{p.name} references {banned}"
    print("  ✓ no src/live module references a paper cohort file")


def test_live_writes_stay_in_sandbox_not_paper(tmp_path):
    """Running the live path with tmp paths must not modify any data/paper_* file."""
    log, state, fills_log = _p(tmp_path)
    paper = list((ROOT / "data").glob("paper_*"))
    before = {p: p.stat().st_mtime for p in paper}
    record_intent(new_intent("A", "BUY", 100, "r", "pilot_e1", card_id="Z"), log_path=log, state_path=state)
    record_fill("Z", 10.0, 1, fills_log=fills_log, state_path=state, intents_log=log)
    reconcile.reconcile(load_intent_state(state), load_fills(fills_log))
    assert {p: p.stat().st_mtime for p in paper} == before
    assert not (tmp_path / "data" / "paper_positions.yaml").exists()
    print("  ✓ live writes stayed in the sandbox; no data/paper_* touched")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
