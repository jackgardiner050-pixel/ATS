"""Live-pilot guard layer tests (modeled on the constitution guards)."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.live.limits import (
    load_live_limits, LiveLimitViolation, cards_enabled,
    check_order_admissible, check_breakers,
)

ROOT = Path(__file__).parent.parent
COMMITTED = ROOT / "config" / "live_limits.yaml"


def _write(tmp_path, **over):
    cfg = yaml.safe_load(COMMITTED.read_text())
    cfg.update(over)
    p = tmp_path / "live_limits.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def _funded(**over):
    cfg = yaml.safe_load(COMMITTED.read_text())
    cfg["MAX_LIVE_CAPITAL_GBP"] = 10000
    cfg.update(over)
    return cfg


# ─── ACCEPTANCE: committed file is stage E1, capital 0 ────────────────────────

def test_committed_is_e1_and_capital_zero():
    cfg = load_live_limits()                       # committed loads clean
    assert cfg["execution_stage"] == "E1"
    assert cfg["MAX_LIVE_CAPITAL_GBP"] == 0
    print("  ✓ committed live_limits.yaml: E1, capital 0")


# ─── load-time validation ─────────────────────────────────────────────────────

def test_e2_rejected_at_parse(tmp_path):
    with pytest.raises(LiveLimitViolation, match="constitution v3"):
        load_live_limits(_write(tmp_path, execution_stage="E2"))
    print("  ✓ E2 rejected at load (requires constitution v3)")


def test_human_executes_false_raises_at_load(tmp_path):
    with pytest.raises(LiveLimitViolation, match="HUMAN_EXECUTES_ALL_ORDERS"):
        load_live_limits(_write(tmp_path, HUMAN_EXECUTES_ALL_ORDERS=False))
    print("  ✓ HUMAN_EXECUTES_ALL_ORDERS: false raises at load")


# ─── card gating + order admissibility ────────────────────────────────────────

def test_capital_zero_blocks_cards():
    cfg = load_live_limits()
    assert cards_enabled(cfg) is False
    v = check_order_admissible({"ticker": "X", "weight": 0.05}, {"orders_this_week": 0}, cfg)
    assert v and "unfunded" in v[0]
    print("  ✓ capital 0 → cards disabled, no order admissible")


def test_11pct_position_rejected():
    cfg = _funded()
    v = check_order_admissible({"ticker": "AAPL", "weight": 0.11}, {"orders_this_week": 0}, cfg)
    assert any("MAX_SINGLE_POSITION_LIVE" in s for s in v)
    assert check_order_admissible({"ticker": "AAPL", "weight": 0.10}, {"orders_this_week": 0}, cfg) == []
    print("  ✓ 11% position rejected; 10% admissible")


def test_6th_weekly_order_rejected():
    cfg = _funded()
    v = check_order_admissible({"ticker": "X", "weight": 0.05}, {"orders_this_week": 5}, cfg)
    assert any("MAX_ORDERS_PER_WEEK" in s for s in v)
    assert check_order_admissible({"ticker": "X", "weight": 0.05}, {"orders_this_week": 4}, cfg) == []
    print("  ✓ 6th weekly order rejected; 5th admissible")


# ─── breakers (placeholders skip; fire when set) ──────────────────────────────

def test_breakers_skip_null_and_fire_when_set():
    assert check_breakers({"daily_pnl_pct": -0.5}, load_live_limits())["halt"] is False  # null → skip
    cfg = _funded(DAILY_LOSS_HALT_PCT=0.03, CUMULATIVE_KILL_PCT=0.20)
    r = check_breakers({"daily_pnl_pct": -0.04, "cumulative_pnl_pct": -0.05}, cfg)
    assert r["halt"] and not r["kill"]
    r2 = check_breakers({"cumulative_pnl_pct": -0.25}, cfg)
    assert r2["halt"] and r2["kill"]
    print("  ✓ null breakers skipped; set breakers halt; cumulative → kill")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
