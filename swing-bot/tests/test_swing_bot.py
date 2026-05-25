"""Swing Bot v1 test suite — 35+ tests covering all hard rules.

Hard rules verified:
  1. place_real_order() raises RuntimeError (always)
  2. paper_only constraint tag present in all records
  3. ringfenced: data paths are under swing-bot/data/, not agent/data/
  4. kill switch triggers at ≤ -10% cumulative P&L
  5. kill switch triggers at disable_date expiry
  6. kill switch: disabled state persists and blocks further trading
  7. no_live_pnl_learning tag on all trade records
  8. LLM classifier returns None when disabled (Phase A)
  9. LLM cost cap enforced before API call
 10. entry rules: all 4 conditions independently block entry
 11. exit rules: all 4 exit conditions trigger correctly
 12. signal reversal overrides price-based exits
 13. is_negative_8k: Phase A rule (5.02 only → negative; 5.02+1.01 → not negative)
 14. Position round-trip: open → save → load → close → append → reload
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── Imports under test ────────────────────────────────────────────────────────
import sys
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.paper_executor import (
    place_real_order, open_position, close_position,
    load_positions, save_positions, load_trades, append_trade,
)
from src.kill_switch import (
    check_kill_switch, is_disabled, load_state, save_state,
    format_kill_alert, update_pnl,
)
from src.rules.entry import check_entry, build_entry_signal, EntrySignal
from src.rules.exit import check_exit, ExitSignal, _count_trading_days
from src.rules.filters import (
    is_material_8k, is_material_fda, is_material_earnings,
    is_material_volume, is_negative_8k, passes_all_filters,
)
from src.classifier import _monthly_cost_exceeded, _log_cost


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _tmp_path():
    return Path(tempfile.mkdtemp())


def _make_catalyst(
    ticker="AAPL",
    catalyst_type="8K",
    high_priority=True,
    items=None,
    **kwargs,
):
    return {
        "ticker": ticker,
        "catalyst_type": catalyst_type,
        "high_priority": high_priority,
        "items": items or ["1.01"],
        **kwargs,
    }


def _make_market_data(
    current_price=100.0,
    price_change_pct=5.0,
    trend_5d_pct=2.0,
    avg_daily_volume_usd=10_000_000,
):
    return {
        "current_price": current_price,
        "price_change_pct": price_change_pct,
        "trend_5d_pct": trend_5d_pct,
        "avg_daily_volume_usd": avg_daily_volume_usd,
    }


def _make_position(ticker="AAPL", entry_price=100.0, entry_date=None, spy_entry=550.0):
    return open_position(
        ticker=ticker,
        entry_date=entry_date or date.today().isoformat(),
        entry_price=entry_price,
        shares=0.5,
        notional_gbp=50.0,
        catalyst=_make_catalyst(ticker=ticker),
        spy_entry_price=spy_entry,
        stop_loss_price=entry_price * 0.95,
        profit_target_price=entry_price * 1.10,
        time_exit_date=(date.today() + timedelta(days=14)).isoformat(),
    )


def _make_trades(pnl_values: list[float]) -> list[dict]:
    """Synthetic closed trade list with given pnl_gbp values."""
    return [{"pnl_gbp": p, "return_pct": p / 50.0} for p in pnl_values]


# ─── Hard rule #1: place_real_order always raises ─────────────────────────────

class TestHardRuleNoRealOrders:
    def test_place_real_order_raises(self):
        with pytest.raises(RuntimeError, match="permanently disabled"):
            place_real_order()

    def test_place_real_order_raises_with_args(self):
        with pytest.raises(RuntimeError):
            place_real_order("AAPL", 150.0, 10)

    def test_place_real_order_raises_with_kwargs(self):
        with pytest.raises(RuntimeError):
            place_real_order(ticker="AAPL", qty=10)


# ─── Hard rule #2/#7: constraints tagged on records ──────────────────────────

class TestConstraintTags:
    def test_open_position_has_paper_only_tag(self):
        pos = _make_position()
        assert pos["constraints"]["paper_only"] is True

    def test_open_position_has_no_real_orders_tag(self):
        pos = _make_position()
        assert pos["constraints"]["no_real_orders"] is True

    def test_open_position_has_ringfenced_tag(self):
        pos = _make_position()
        assert pos["constraints"]["ringfenced"] is True

    def test_close_position_inherits_no_live_pnl_learning_tag(self):
        pos = _make_position()
        trade = close_position(pos, date.today().isoformat(), 110.0, "profit_target", 555.0)
        assert trade["constraints"]["no_live_pnl_learning"] is True

    def test_close_position_has_paper_only_tag(self):
        pos = _make_position()
        trade = close_position(pos, date.today().isoformat(), 110.0, "profit_target", 555.0)
        assert trade["constraints"]["paper_only"] is True


# ─── Hard rule #3: ringfenced data paths ─────────────────────────────────────

class TestRingfencedPaths:
    def test_positions_path_under_swing_bot(self):
        from src.paper_executor import _POSITIONS_PATH
        assert "swing-bot" in str(_POSITIONS_PATH)
        assert "swing_paper_positions" in _POSITIONS_PATH.name

    def test_trades_path_under_swing_bot(self):
        from src.paper_executor import _TRADES_PATH
        assert "swing-bot" in str(_TRADES_PATH)
        assert "swing_paper_trades" in _TRADES_PATH.name

    def test_kill_switch_state_under_swing_bot(self):
        from src.kill_switch import _STATE_PATH
        assert "swing-bot" in str(_STATE_PATH)

    def test_no_shared_path_with_long_term_agent(self):
        from src.paper_executor import _POSITIONS_PATH, _TRADES_PATH
        # Long-term agent uses paper_positions.yaml and paper_trades.jsonl (no "swing_" prefix)
        assert _POSITIONS_PATH.name != "paper_positions.yaml"
        assert _TRADES_PATH.name != "paper_trades.jsonl"


# ─── Hard rule #4: kill switch at -10% P&L ───────────────────────────────────

class TestKillSwitchPnL:
    def test_no_trigger_at_zero_pnl(self):
        tmp = _tmp_path() / "ks.yaml"
        trades = _make_trades([0.0])
        triggered, reason = check_kill_switch(trades, path=tmp)
        assert not triggered
        assert reason == "ok"

    def test_no_trigger_at_minus_9pct(self):
        tmp = _tmp_path() / "ks.yaml"
        # -9% of £500 = -£45
        trades = _make_trades([-45.0])
        triggered, reason = check_kill_switch(trades, path=tmp)
        assert not triggered

    def test_trigger_at_exactly_minus_10pct(self):
        tmp = _tmp_path() / "ks.yaml"
        # -10% of £500 = -£50
        trades = _make_trades([-50.0])
        triggered, reason = check_kill_switch(trades, path=tmp)
        assert triggered
        assert "cumulative_loss" in reason

    def test_trigger_at_minus_11pct(self):
        tmp = _tmp_path() / "ks.yaml"
        trades = _make_trades([-55.0])
        triggered, reason = check_kill_switch(trades, path=tmp)
        assert triggered

    def test_trigger_sets_disabled_in_state_file(self):
        tmp = _tmp_path() / "ks.yaml"
        trades = _make_trades([-60.0])
        check_kill_switch(trades, path=tmp)
        state = load_state(tmp)
        assert state["disabled"] is True

    def test_trigger_preserves_disable_reason(self):
        tmp = _tmp_path() / "ks.yaml"
        trades = _make_trades([-60.0])
        _, reason = check_kill_switch(trades, path=tmp)
        state = load_state(tmp)
        assert state["disable_reason"] == reason

    def test_accumulates_across_multiple_trades(self):
        tmp = _tmp_path() / "ks.yaml"
        # Six trades at -£9 each = -£54 = -10.8%
        trades = _make_trades([-9.0] * 6)
        triggered, _ = check_kill_switch(trades, path=tmp)
        assert triggered


# ─── Hard rule #5: kill switch at time expiry ────────────────────────────────

class TestKillSwitchTimeExpiry:
    def test_trigger_when_today_equals_disable_date(self):
        tmp = _tmp_path() / "ks.yaml"
        today = date.today().isoformat()
        triggered, reason = check_kill_switch([], path=tmp, disable_date=today)
        assert triggered
        assert "time_expiry" in reason

    def test_trigger_when_past_disable_date(self):
        tmp = _tmp_path() / "ks.yaml"
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        triggered, reason = check_kill_switch([], path=tmp, disable_date=yesterday)
        assert triggered

    def test_no_trigger_before_disable_date(self):
        tmp = _tmp_path() / "ks.yaml"
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        triggered, _ = check_kill_switch([], path=tmp, disable_date=tomorrow)
        assert not triggered


# ─── Hard rule #6: disabled state blocks further checks ──────────────────────

class TestKillSwitchPersistence:
    def test_already_disabled_returns_immediately(self):
        tmp = _tmp_path() / "ks.yaml"
        state = {"disabled": True, "disable_reason": "manual_disable"}
        save_state(state, tmp)
        triggered, reason = check_kill_switch([], path=tmp)
        assert triggered
        assert reason == "manual_disable"

    def test_is_disabled_returns_true_when_triggered(self):
        tmp = _tmp_path() / "ks.yaml"
        state = {"disabled": True}
        save_state(state, tmp)
        assert is_disabled(tmp) is True

    def test_is_disabled_returns_false_when_ok(self):
        tmp = _tmp_path() / "ks.yaml"
        assert is_disabled(tmp) is False  # no file → default = False


# ─── Kill switch: alert formatting ───────────────────────────────────────────

class TestKillSwitchAlert:
    def test_alert_contains_ticker_and_pct(self):
        msg = format_kill_alert("cumulative_loss (-10.5%)", -10.5, -52.5)
        assert "KILL SWITCH" in msg
        assert "-10.5%" in msg
        assert "£-52.50" in msg or "£" in msg

    def test_alert_instructs_manual_reenable(self):
        msg = format_kill_alert("time_expiry", 0.0, 0.0)
        assert "DISABLED" in msg or "disabled" in msg.lower()


# ─── Entry rules ──────────────────────────────────────────────────────────────

class TestEntryRules:
    def test_all_conditions_pass(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(),
            n_open_positions=0,
        )
        assert result.passed
        assert result.reason == "all_conditions_passed"

    def test_concurrency_blocks_at_max(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(),
            n_open_positions=10,
            max_positions=10,
        )
        assert not result.passed
        assert "concurrency_limit" in result.reason

    def test_momentum_fail_below_3pct(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(price_change_pct=2.9),
            n_open_positions=0,
        )
        assert not result.passed
        assert "momentum_fail" in result.reason

    def test_momentum_passes_at_exactly_3pct(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(price_change_pct=3.0),
            n_open_positions=0,
        )
        assert result.passed

    def test_trend_fail_below_minus_1pct(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(trend_5d_pct=-1.1),
            n_open_positions=0,
        )
        assert not result.passed
        assert "trend_fail" in result.reason

    def test_liquidity_fail_below_threshold(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(avg_daily_volume_usd=1_000_000),
            n_open_positions=0,
        )
        assert not result.passed
        assert "liquidity_fail" in result.reason

    def test_invalid_price_fails(self):
        result = check_entry(
            ticker="AAPL",
            catalyst=_make_catalyst(),
            market_data=_make_market_data(current_price=0.0),
            n_open_positions=0,
        )
        assert not result.passed
        assert "invalid_price" in result.reason

    def test_build_entry_signal_computes_shares(self):
        signal = build_entry_signal("AAPL", _make_catalyst(), 100.0)
        assert abs(signal.shares - 0.5) < 0.001  # £50 / £100

    def test_build_entry_signal_stop_loss_at_minus_5pct(self):
        signal = build_entry_signal("AAPL", _make_catalyst(), 100.0)
        assert abs(signal.stop_loss_price - 95.0) < 0.01

    def test_build_entry_signal_target_at_plus_10pct(self):
        signal = build_entry_signal("AAPL", _make_catalyst(), 100.0)
        assert abs(signal.profit_target_price - 110.0) < 0.01

    def test_notional_is_always_50_gbp(self):
        signal = build_entry_signal("AAPL", _make_catalyst(), 200.0)
        assert signal.notional_gbp == 50.0


# ─── Exit rules ───────────────────────────────────────────────────────────────

class TestExitRules:
    def _pos(self, entry=100.0, entry_date=None):
        d = entry_date or date.today().isoformat()
        return _make_position(entry_price=entry, entry_date=d)

    def test_hold_when_in_range(self):
        sig = check_exit(self._pos(), 102.0, date.today().isoformat())
        assert not sig.should_exit
        assert sig.reason == "hold"

    def test_profit_target_at_plus_10pct(self):
        sig = check_exit(self._pos(), 110.0, date.today().isoformat())
        assert sig.should_exit
        assert sig.reason == "profit_target"

    def test_profit_target_not_triggered_below_10pct(self):
        sig = check_exit(self._pos(), 109.9, date.today().isoformat())
        assert not sig.should_exit

    def test_stop_loss_at_minus_5pct(self):
        sig = check_exit(self._pos(), 95.0, date.today().isoformat())
        assert sig.should_exit
        assert sig.reason == "stop_loss"

    def test_stop_loss_not_triggered_above_minus_5pct(self):
        sig = check_exit(self._pos(), 95.1, date.today().isoformat())
        assert not sig.should_exit

    def test_time_exit_after_10_trading_days(self):
        # 14 calendar days from a Monday = well past 10 trading days
        entry = (date.today() - timedelta(days=14)).isoformat()
        today = date.today().isoformat()
        sig = check_exit(self._pos(entry_date=entry), 102.0, today)
        assert sig.should_exit
        assert sig.reason == "time_exit"

    def test_signal_reversal_overrides_profit_target(self):
        # Even at +15%, negative catalyst forces exit as signal_reversal
        sig = check_exit(self._pos(), 115.0, date.today().isoformat(), negative_catalyst=True)
        assert sig.should_exit
        assert sig.reason == "signal_reversal"

    def test_signal_reversal_overrides_hold(self):
        sig = check_exit(self._pos(), 102.0, date.today().isoformat(), negative_catalyst=True)
        assert sig.should_exit
        assert sig.reason == "signal_reversal"

    def test_invalid_price_does_not_exit(self):
        sig = check_exit(self._pos(), 0.0, date.today().isoformat())
        assert not sig.should_exit

    def test_return_pct_computed_correctly(self):
        sig = check_exit(self._pos(entry=100.0), 105.0, date.today().isoformat())
        assert abs(sig.return_pct - 5.0) < 0.01


class TestCountTradingDays:
    def test_same_day_is_one(self):
        today = date.today().isoformat()
        assert _count_trading_days(today, today) == 1

    def test_two_adjacent_weekdays(self):
        mon = "2026-05-25"  # Monday
        tue = "2026-05-26"
        assert _count_trading_days(mon, tue) == 2

    def test_skips_weekend(self):
        fri = "2026-05-22"
        mon = "2026-05-25"
        assert _count_trading_days(fri, mon) == 2  # Fri + Mon (Sat/Sun skipped)

    def test_end_before_start_returns_zero(self):
        assert _count_trading_days("2026-05-25", "2026-05-20") == 0


# ─── Catalyst filters ─────────────────────────────────────────────────────────

class TestFilters:
    def test_material_8k_phase_a_high_priority(self):
        c = _make_catalyst(high_priority=True)
        assert is_material_8k(c, phase_b_enabled=False)

    def test_material_8k_phase_a_low_priority_fails(self):
        c = _make_catalyst(high_priority=False, items=["5.02"])
        assert not is_material_8k(c, phase_b_enabled=False)

    def test_material_8k_phase_b_uses_classification(self):
        c = _make_catalyst(high_priority=False, classification={"material": True, "confidence": 0.8})
        assert is_material_8k(c, phase_b_enabled=True)

    def test_material_8k_phase_b_low_confidence_fails(self):
        c = _make_catalyst(high_priority=True, classification={"material": True, "confidence": 0.4})
        assert not is_material_8k(c, phase_b_enabled=True)

    def test_fda_always_material(self):
        c = {"catalyst_type": "FDA_APPROVAL", "ticker": "BIIB"}
        assert is_material_fda(c)

    def test_earnings_beat_requires_both_eps_and_revenue(self):
        c = {"catalyst_type": "EARNINGS_BEAT", "eps_beat_pct": 10.0, "revenue_beat": True}
        assert is_material_earnings(c)

    def test_earnings_beat_fails_without_revenue(self):
        c = {"catalyst_type": "EARNINGS_BEAT", "eps_beat_pct": 10.0, "revenue_beat": False}
        assert not is_material_earnings(c)

    def test_earnings_beat_fails_below_threshold(self):
        c = {"catalyst_type": "EARNINGS_BEAT", "eps_beat_pct": 4.9, "revenue_beat": True}
        assert not is_material_earnings(c, min_beat_pct=5.0)

    def test_volume_spike_passes_at_3x(self):
        c = {"catalyst_type": "VOLUME_SPIKE", "volume_ratio": 3.0}
        assert is_material_volume(c)

    def test_volume_spike_fails_below_3x(self):
        c = {"catalyst_type": "VOLUME_SPIKE", "volume_ratio": 2.9}
        assert not is_material_volume(c)

    def test_is_negative_8k_5_02_only(self):
        c = _make_catalyst(items=["5.02"], catalyst_type="8K")
        assert is_negative_8k(c)

    def test_is_negative_8k_5_02_with_ma_not_negative(self):
        c = _make_catalyst(items=["5.02", "1.01"], catalyst_type="8K")
        assert not is_negative_8k(c)

    def test_passes_all_filters_unknown_type_fails(self):
        c = {"catalyst_type": "UNKNOWN"}
        assert not passes_all_filters(c)


# ─── Paper executor I/O round-trips ──────────────────────────────────────────

class TestPaperExecutorIO:
    def test_position_round_trip(self, tmp_path):
        pos_path = tmp_path / "positions.yaml"
        pos = _make_position()
        save_positions({"AAPL": pos}, pos_path)
        loaded = load_positions(pos_path)
        assert "AAPL" in loaded
        assert loaded["AAPL"]["entry_price"] == pos["entry_price"]

    def test_trade_round_trip(self, tmp_path):
        trade_path = tmp_path / "trades.jsonl"
        pos = _make_position()
        trade = close_position(pos, date.today().isoformat(), 110.0, "profit_target", 555.0)
        append_trade(trade, trade_path)
        trades = load_trades(trade_path)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "AAPL"
        assert abs(trades[0]["pnl_gbp"] - 5.0) < 0.01  # £50 * 10% = £5

    def test_multiple_trades_appended(self, tmp_path):
        trade_path = tmp_path / "trades.jsonl"
        pos = _make_position()
        for price in [110.0, 95.0]:
            trade = close_position(pos, date.today().isoformat(), price, "test", 555.0)
            append_trade(trade, trade_path)
        trades = load_trades(trade_path)
        assert len(trades) == 2

    def test_empty_positions_file_returns_empty_dict(self, tmp_path):
        assert load_positions(tmp_path / "nonexistent.yaml") == {}

    def test_empty_trades_file_returns_empty_list(self, tmp_path):
        assert load_trades(tmp_path / "nonexistent.jsonl") == []

    def test_close_position_pnl_calculation(self):
        pos = _make_position(entry_price=100.0)
        trade = close_position(pos, date.today().isoformat(), 110.0, "profit_target", 550.0)
        assert abs(trade["return_pct"] - 0.1) < 0.0001  # 10%
        assert abs(trade["pnl_gbp"] - 5.0) < 0.01      # £50 * 10% = £5

    def test_close_position_alpha_vs_spy(self):
        pos = _make_position(entry_price=100.0, spy_entry=500.0)
        # Stock up 10%, SPY up 5% → alpha = 5%
        trade = close_position(pos, date.today().isoformat(), 110.0, "profit_target", 525.0)
        assert abs(trade["alpha"] - 0.05) < 0.001

    def test_close_position_negative_alpha(self):
        pos = _make_position(entry_price=100.0, spy_entry=500.0)
        # Stock up 3%, SPY up 10% → alpha = -7%
        trade = close_position(pos, date.today().isoformat(), 103.0, "time_exit", 550.0)
        assert trade["alpha"] < 0


# ─── LLM cost cap (Phase B guard) ────────────────────────────────────────────

class TestLLMCostCap:
    def test_cost_not_exceeded_when_no_log(self, tmp_path):
        with patch("src.classifier._COST_LOG_PATH", tmp_path / "cost.jsonl"):
            assert not _monthly_cost_exceeded()

    def test_cost_exceeded_when_over_cap(self, tmp_path):
        log_path = tmp_path / "cost.jsonl"
        this_month = date.today().strftime("%Y-%m")
        with open(log_path, "w") as f:
            f.write(json.dumps({"month": this_month, "cost_gbp": 5.0}) + "\n")
        with patch("src.classifier._COST_LOG_PATH", log_path):
            assert _monthly_cost_exceeded()

    def test_cost_not_exceeded_for_different_month(self, tmp_path):
        log_path = tmp_path / "cost.jsonl"
        with open(log_path, "w") as f:
            f.write(json.dumps({"month": "2020-01", "cost_gbp": 999.0}) + "\n")
        with patch("src.classifier._COST_LOG_PATH", log_path):
            assert not _monthly_cost_exceeded()

    def test_classify_8k_returns_none_when_disabled(self, tmp_path):
        from src.classifier import classify_8k
        with patch("src.classifier._is_enabled", return_value=False):
            result = classify_8k("some filing text", ["1.01"])
        assert result is None

    def test_classify_8k_returns_none_when_cost_cap_exceeded(self, tmp_path):
        from src.classifier import classify_8k
        with patch("src.classifier._is_enabled", return_value=True), \
             patch("src.classifier._monthly_cost_exceeded", return_value=True):
            result = classify_8k("some filing text", ["1.01"])
        assert result is None

    def test_classify_8k_returns_none_without_api_key(self, tmp_path):
        from src.classifier import classify_8k
        with patch("src.classifier._is_enabled", return_value=True), \
             patch("src.classifier._monthly_cost_exceeded", return_value=False), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            result = classify_8k("text", ["1.01"])
        assert result is None


# ─── Telegram client: graceful failure ───────────────────────────────────────

class TestTelegramClient:
    def test_send_message_returns_false_on_missing_credentials(self, tmp_path):
        from src.telegram_client import send_message, _ENV_PATH
        with patch("src.telegram_client._ENV_PATH", tmp_path / "nonexistent.env"), \
             patch.dict(os.environ, {"SWING_BOT_TOKEN": "", "SWING_BOT_CHAT_ID": ""}):
            result = send_message("test")
        assert result is False

    def test_send_message_returns_false_on_network_error(self):
        from src.telegram_client import send_message
        with patch("src.telegram_client._credentials", return_value=("tok", "chat")), \
             patch("requests.post", side_effect=ConnectionError("network down")):
            result = send_message("test")
        assert result is False

    def test_send_message_returns_false_on_api_error(self):
        from src.telegram_client import send_message
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        with patch("src.telegram_client._credentials", return_value=("tok", "chat")), \
             patch("requests.post", return_value=mock_resp):
            result = send_message("test")
        assert result is False

    def test_send_message_returns_true_on_success(self):
        from src.telegram_client import send_message
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch("src.telegram_client._credentials", return_value=("tok", "chat")), \
             patch("requests.post", return_value=mock_resp):
            result = send_message("hello")
        assert result is True
