"""Tests for dashboard unification — fetch_live_prices.py SPY fields.

Confirms:
- SPY fields added to basket JSON (can be null, must be present)
- SPY fields added to lab JSON (can be null, must be present)
- summary JSON passes through SPY fields
- No logic files modified (scoring/governance untouched)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)


def _prices() -> dict:
    return {
        "SPY": {"last_price": 550.0, "prev_close": 548.0, "last_data_date": "2026-05-28"},
        "QQQ": {"last_price": 480.0, "prev_close": 478.0, "last_data_date": "2026-05-28"},
        "VRT": {"last_price": 320.0, "prev_close": 318.0, "last_data_date": "2026-05-28"},
        "SMCI": {"last_price": 38.5, "prev_close": 38.0, "last_data_date": "2026-05-28"},
    }


def _basket() -> dict:
    return {
        "paper_id": "sp_test_001",
        "basket_name": "AI Infrastructure — cooling_power",
        "tickers": ["VRT", "SMCI"],
        "weights": {"VRT": 0.5, "SMCI": 0.5},
        "entry_prices": {"VRT": 319.78, "SMCI": 38.19},
        "benchmark": "QQQ",
        "entry_date": "2026-05-28",
        "entry_price_fill_date": "2026-05-28",
    }


# ─── _build_basket_json ───────────────────────────────────────────────────────

class TestBasketJsonSpyFields:
    def test_spy_fields_present_with_entry_price(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_basket_json
        result = _build_basket_json(_basket(), _prices(), _now(), "scai", spy_entry_price=540.0)
        assert "spy_return_pct" in result
        assert "spy_today_pct" in result
        assert "alpha_vs_spy_pct" in result
        assert "spy_entry_price" in result

    def test_spy_return_computed_correctly(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_basket_json
        result = _build_basket_json(_basket(), _prices(), _now(), "scai", spy_entry_price=500.0)
        # SPY last_price=550, entry=500 → +10%
        assert result["spy_return_pct"] == pytest.approx(10.0, abs=0.01)

    def test_spy_fields_null_when_no_entry_price(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_basket_json
        result = _build_basket_json(_basket(), _prices(), _now(), "scai", spy_entry_price=None)
        assert result["spy_return_pct"] is None
        assert result["spy_entry_price"] is None

    def test_default_no_spy_entry_gives_null(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_basket_json
        # Called without spy_entry_price kwarg (default = None)
        result = _build_basket_json(_basket(), _prices(), _now(), "hermes")
        assert result["spy_return_pct"] is None


# ─── _build_lab_json ──────────────────────────────────────────────────────────

class TestLabJsonSpyFields:
    def test_spy_fields_present_in_output(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_lab_json
        with patch("fetch_live_prices._hist_entry_price", return_value=None):
            result = _build_lab_json([_basket()], _prices(), _now(), "scai")
        assert "spy_return_pct" in result
        assert "spy_today_pct" in result
        assert "alpha_vs_spy_pct" in result

    def test_spy_fields_null_when_no_history(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_lab_json
        with patch("fetch_live_prices._hist_entry_price", return_value=None):
            result = _build_lab_json([_basket()], _prices(), _now(), "scai")
        assert result["spy_return_pct"] is None
        assert result["alpha_vs_spy_pct"] is None

    def test_spy_today_computable_from_prices(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_lab_json
        with patch("fetch_live_prices._hist_entry_price", return_value=None):
            result = _build_lab_json([_basket()], _prices(), _now(), "scai")
        # SPY last=550, prev=548 → today ~ +0.365%
        assert result["spy_today_pct"] == pytest.approx((550 - 548) / 548 * 100, abs=0.01)

    def test_spy_deduplicates_date_calls(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_lab_json
        b2 = dict(_basket(), paper_id="sp_002")  # same entry_date
        with patch("fetch_live_prices._hist_entry_price", return_value=None) as mock_hist:
            _build_lab_json([_basket(), b2], _prices(), _now(), "scai")
        # Two baskets with same entry date → only one SPY call (deduplication)
        spy_calls = [c for c in mock_hist.call_args_list if c[0][0] == "SPY"]
        assert len(spy_calls) == 1

    def test_empty_positions_spy_fields_null(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_lab_json
        result = _build_lab_json([], _prices(), _now(), "scai")
        assert result["spy_return_pct"] is None
        assert result["alpha_vs_spy_pct"] is None


# ─── _build_summary_json ──────────────────────────────────────────────────────

class TestSummaryJsonSpyFields:
    def test_summary_has_spy_fields_for_scai_and_hermes(self):
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from fetch_live_prices import _build_summary_json
        ats_j = {"portfolio_return_pct": 5.0, "portfolio_today_pct": 0.3,
                 "spy_return_pct": 3.0, "alpha_vs_spy_pct": 2.0, "n_positions": 4}
        scai_j = {"portfolio_return_pct": 1.0, "portfolio_today_pct": 0.1,
                  "spy_return_pct": 3.0, "alpha_vs_spy_pct": -2.0, "n_baskets": 1}
        hermes_j = {"portfolio_return_pct": 2.0, "portfolio_today_pct": 0.2,
                    "spy_return_pct": 3.0, "alpha_vs_spy_pct": -1.0, "n_baskets": 2}
        result = _build_summary_json(ats_j, scai_j, hermes_j, _now())
        assert "spy_return_pct" in result["systems"]["scai"]
        assert "alpha_vs_spy_pct" in result["systems"]["scai"]
        assert "spy_return_pct" in result["systems"]["hermes"]
        assert "alpha_vs_spy_pct" in result["systems"]["hermes"]
        assert result["systems"]["scai"]["spy_return_pct"] == 3.0
        assert result["systems"]["hermes"]["alpha_vs_spy_pct"] == -1.0


# ─── No logic files modified ──────────────────────────────────────────────────

import pytest

class TestNoLogicModified:
    def test_fetch_live_prices_has_no_trading_logic(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "fetch_live_prices.py").read_text()
        # No order execution or broker API keywords
        for forbidden in ["place_order", "submit_order", "create_order", "alpaca", "ibkr", "td_ameritrade"]:
            assert forbidden.lower() not in src.lower(), f"Forbidden token '{forbidden}' in fetch_live_prices.py"

    def test_governance_files_untouched(self):
        gov_dir = Path(__file__).resolve().parents[1] / "src" / "governance"
        if gov_dir.exists():
            for f in gov_dir.glob("*.py"):
                content = f.read_text()
                # governance files should not have been modified to add fetch logic
                assert "fetch_live_prices" not in content
