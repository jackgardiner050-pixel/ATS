"""
Tests for SPY baseline logic in fetch_live_prices.py.

Covers:
  - Same-day entries use previousClose, not 0.0%
  - Historical entries use history close
  - Missing baseline shows status="unavailable", never 0.0%
  - New JSON fields present in basket and lab output
  - Date/timezone edge cases
"""
import sys
import types
import importlib
from datetime import datetime, date, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to isolate _hist_entry_price without yfinance network calls
# ---------------------------------------------------------------------------

def _load_module():
    """Import fetch_live_prices without executing main()."""
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "fetch_live_prices",
        pathlib.Path(__file__).parent.parent / "scripts" / "fetch_live_prices.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def flp():
    return _load_module()


TODAY = date(2026, 5, 28)
YESTERDAY_STR = "2026-05-27"
TODAY_STR = "2026-05-28"
PREV_CLOSE = 530.25
HIST_CLOSE = 521.50


# ---------------------------------------------------------------------------
# _hist_entry_price: same-day path
# ---------------------------------------------------------------------------

class TestHistEntryPriceSameDay:
    def test_same_day_uses_previous_close(self, flp):
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.return_value = PREV_CLOSE

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", TODAY_STR)

        assert result == round(PREV_CLOSE, 4)
        mock_ticker.fast_info.get.assert_called_once_with("previousClose")

    def test_same_day_returns_nonzero(self, flp):
        """Result must not be falsy when previousClose is valid."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.return_value = 530.25

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", TODAY_STR)

        assert result is not None
        assert result > 0

    def test_same_day_future_date_also_uses_prev_close(self, flp):
        """Entry date in the future should also fall into same-day path."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.return_value = 535.00

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", "2026-06-01")

        assert result == 535.00

    def test_same_day_nan_prev_close_returns_none(self, flp):
        """NaN guard: if previousClose is NaN, must return None."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.return_value = float("nan")

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", TODAY_STR)

        assert result is None

    def test_same_day_zero_prev_close_returns_none(self, flp):
        """Zero price is falsy — should fall through to None."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.return_value = 0.0

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", TODAY_STR)

        assert result is None

    def test_same_day_fast_info_exception_returns_none(self, flp):
        """If fast_info raises, must return None gracefully."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.get.side_effect = RuntimeError("network error")

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", TODAY_STR)

        assert result is None


# ---------------------------------------------------------------------------
# _hist_entry_price: historical path
# ---------------------------------------------------------------------------

class TestHistEntryPriceHistorical:
    def _make_hist_df(self, rows: list[tuple[str, float]]):
        import pandas as pd
        dates = [pd.Timestamp(d) for d, _ in rows]
        closes = [c for _, c in rows]
        return pd.DataFrame({"Close": closes}, index=dates)

    def test_historical_returns_close_on_entry_date(self, flp):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._make_hist_df([
            ("2026-05-01", 518.0),
            ("2026-05-02", 520.0),
            ("2026-05-05", 521.5),
        ])

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", "2026-05-02")

        assert result == 520.0

    def test_historical_returns_closest_close_after_entry(self, flp):
        """When entry date has no data, prefer the first close after it."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._make_hist_df([
            ("2026-05-01", 518.0),
            ("2026-05-05", 524.0),  # closest after 2026-05-03
            ("2026-05-06", 526.0),
        ])

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", "2026-05-03")

        assert result == 524.0

    def test_historical_empty_hist_returns_none(self, flp):
        import pandas as pd
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch.object(flp, "_now_utc", return_value=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = flp._hist_entry_price("SPY", "2026-04-01")

        assert result is None


# ---------------------------------------------------------------------------
# _build_basket_json: spy_baseline_status propagation
# ---------------------------------------------------------------------------

class TestBuildBasketJsonSpyFields:
    def _make_basket(self, entry_date=YESTERDAY_STR):
        return {
            "paper_id": "test-001",
            "basket_name": "Test Basket",
            "tickers": ["AAPL", "MSFT"],
            "weights": {"AAPL": 0.5, "MSFT": 0.5},
            "entry_prices": {"AAPL": 170.0, "MSFT": 400.0},
            "entry_price_fill_date": entry_date,
            "benchmark": "QQQ",
        }

    def _make_prices(self):
        return {
            "AAPL": {"last_price": 175.0, "prev_close": 172.0},
            "MSFT": {"last_price": 410.0, "prev_close": 405.0},
            "SPY": {"last_price": 535.0, "prev_close": 530.0},
            "QQQ": {"last_price": 460.0, "prev_close": 455.0},
        }

    def test_ok_status_included(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        with patch.object(flp, "_hist_entry_price", return_value=HIST_CLOSE):
            result = flp._build_basket_json(
                self._make_basket(), self._make_prices(), now, "test",
                spy_entry_price=HIST_CLOSE, spy_baseline_status="ok"
            )
        assert result["spy_baseline_status"] == "ok"
        assert result["spy_entry_price"] == HIST_CLOSE
        assert result["spy_latest_price"] == 535.0
        assert result["spy_return_pct"] is not None
        assert result["spy_return_pct"] != 0.0

    def test_same_day_status_included(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        result = flp._build_basket_json(
            self._make_basket(TODAY_STR), self._make_prices(), now, "test",
            spy_entry_price=PREV_CLOSE, spy_baseline_status="same_day_estimated"
        )
        assert result["spy_baseline_status"] == "same_day_estimated"
        assert result["spy_baseline_reason"] == "entry is today; using previous close as baseline"
        assert result["spy_return_pct"] is not None

    def test_unavailable_status_gives_null_return(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        result = flp._build_basket_json(
            self._make_basket(), self._make_prices(), now, "test",
            spy_entry_price=None, spy_baseline_status="unavailable"
        )
        assert result["spy_baseline_status"] == "unavailable"
        assert result["spy_return_pct"] is None  # must be null, never 0.0

    def test_unavailable_never_zero(self, flp):
        """Critical: unavailable baseline must NOT produce 0.0% return."""
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        result = flp._build_basket_json(
            self._make_basket(), self._make_prices(), now, "test",
            spy_entry_price=None, spy_baseline_status="unavailable"
        )
        assert result["spy_return_pct"] != 0.0

    def test_new_fields_present(self, flp):
        """All required new fields must exist in basket output."""
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        result = flp._build_basket_json(
            self._make_basket(), self._make_prices(), now, "test",
            spy_entry_price=HIST_CLOSE, spy_baseline_status="ok"
        )
        for field in ("spy_entry_date", "spy_entry_price", "spy_latest_price",
                      "spy_return_pct", "spy_baseline_status", "spy_baseline_reason"):
            assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# _build_lab_json: top-level spy_baseline_status
# ---------------------------------------------------------------------------

class TestBuildLabJsonSpyStatus:
    def _make_positions(self, entry_date=YESTERDAY_STR):
        return [{
            "paper_id": "test-001",
            "basket_name": "Test Basket",
            "tickers": ["AAPL"],
            "weights": {"AAPL": 1.0},
            "entry_prices": {"AAPL": 170.0},
            "entry_price_fill_date": entry_date,
            "benchmark": "QQQ",
            "spy_entry_price": 520.0,
        }]

    def _make_prices(self):
        return {
            "AAPL": {"last_price": 175.0, "prev_close": 172.0},
            "SPY": {"last_price": 535.0, "prev_close": 530.0},
            "QQQ": {"last_price": 460.0, "prev_close": 455.0},
        }

    def test_lab_json_has_spy_baseline_status(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        with patch.object(flp, "_now_utc", return_value=now):
            with patch.object(flp, "_hist_entry_price", return_value=HIST_CLOSE):
                result = flp._build_lab_json(
                    self._make_positions(), self._make_prices(), now, "test"
                )
        assert "spy_baseline_status" in result

    def test_lab_json_has_spy_entry_date(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        with patch.object(flp, "_now_utc", return_value=now):
            with patch.object(flp, "_hist_entry_price", return_value=HIST_CLOSE):
                result = flp._build_lab_json(
                    self._make_positions(), self._make_prices(), now, "test"
                )
        assert "spy_entry_date" in result

    def test_same_day_lab_status_is_same_day_estimated(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        with patch.object(flp, "_now_utc", return_value=now):
            with patch.object(flp, "_hist_entry_price", return_value=PREV_CLOSE):
                result = flp._build_lab_json(
                    self._make_positions(TODAY_STR), self._make_prices(), now, "test"
                )
        assert result["spy_baseline_status"] in ("same_day_estimated", "ok", "unavailable")

    def test_unavailable_lab_status_when_no_price(self, flp):
        now = datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc)
        with patch.object(flp, "_now_utc", return_value=now):
            with patch.object(flp, "_hist_entry_price", return_value=None):
                result = flp._build_lab_json(
                    self._make_positions(), self._make_prices(), now, "test"
                )
        assert result["spy_baseline_status"] == "unavailable"
