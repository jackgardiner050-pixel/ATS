"""Tests for the market-neutral variant in fetch_live_prices._build_hermes_v3_json.

Covers:
  - Short position MtM is positive when price falls (direction="short")
  - Long position MtM unchanged by the fix
  - market_neutral_spread excluded from best/worst ranking
  - spread_metrics passed through to the live JSON
  - alpha_vs_spy_pct is None for market_neutral (not compared to SPY)
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_live_prices import _build_hermes_v3_json


# ── helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 5, 29, 22, 0, 0)


def _prices(*tickers, price: float = 100.0, prev: float = 99.0) -> dict:
    return {t: {"last_price": price, "prev_close": prev} for t in tickers}


def _make_open_pos(ticker: str, entry: float, direction: str = "long") -> dict:
    return {
        "variant_id": "market_neutral_spread",
        "ticker": ticker,
        "entry_price_net": entry,
        "shares": 10.0,
        "direction": direction,
        "is_open": True,
    }


_BASE_SUMMARY = {
    "variants": [
        {
            "variant_id": "baseline_current_governance",
            "current_pot": 5100.0,
            "net_return_pct": 2.0,
            "open_positions": 1,
            "closed_trades": 4,
            "sharpe_proxy": 1.1,
            "max_drawdown_pct": 2.0,
            "win_rate_pct": 60.0,
            "spy_return_pct": 1.0,
            "dsr": None,
            "dsr_cleared": False,
            "pbo_estimate": None,
            "promotion_gate_cleared": False,
            "promotion_gate_reason": "",
            "spread_metrics": None,
        },
        {
            "variant_id": "market_neutral_spread",
            "current_pot": 5000.0,
            "net_return_pct": 0.0,
            "open_positions": 2,
            "closed_trades": 4,
            "sharpe_proxy": None,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": None,
            "spy_return_pct": None,
            "dsr": None,
            "dsr_cleared": False,
            "pbo_estimate": None,
            "promotion_gate_cleared": False,
            "promotion_gate_reason": "market-neutral evaluated on spread factor regression",
            "spread_metrics": {
                "long_leg_return_pct": 8.5,
                "short_leg_return_pct": 6.2,
                "spread_return_pct": 14.7,
                "net_spread_return_pct": 14.7,
                "borrow_cost_drag_pct": 0.35,
                "beta_long": 1.1,
                "beta_short": 0.9,
                "net_beta": 0.2,
                "n_long_trades": 4,
                "n_short_trades": 4,
            },
        },
    ],
}


def _build(positions=None, summary=None):
    import json
    import tempfile
    from pathlib import Path
    import unittest.mock as mock

    summary = summary or _BASE_SUMMARY
    positions = positions or []

    # Patch the variant summary file read inside _build_hermes_v3_json
    with mock.patch(
        "fetch_live_prices._HERMES_V3_VARIANTS_DIR",
        new_callable=lambda: type("P", (), {"__truediv__": lambda self, x: _MockSummaryPath(summary)})(),
    ):
        return _build_hermes_v3_json(positions, _prices("SPY", "QQQ", "NVDA", "SMCI"), _NOW)


class _MockSummaryPath:
    def __init__(self, summary):
        import json
        self._text = json.dumps(summary)

    def exists(self):
        return True

    def read_text(self):
        return self._text


def _build_direct(positions=None, summary=None, extra_prices: dict | None = None):
    """Build the live JSON by directly patching the file read."""
    import json
    import unittest.mock as mock

    summary = summary or _BASE_SUMMARY
    positions = positions or []

    base = _prices("SPY", "QQQ", "NVDA", "SMCI")
    if extra_prices:
        base.update(extra_prices)

    mock_path = mock.MagicMock()
    mock_path.__truediv__ = mock.MagicMock(return_value=mock_path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = json.dumps(summary)

    import fetch_live_prices as flp
    orig = flp._HERMES_V3_VARIANTS_DIR
    flp._HERMES_V3_VARIANTS_DIR = mock_path
    try:
        return flp._build_hermes_v3_json(positions, base, _NOW)
    finally:
        flp._HERMES_V3_VARIANTS_DIR = orig


# ── Short position MtM ─────────────────────────────────────────────────────────

class TestShortPositionLiveReturn:
    def test_short_return_positive_when_price_falls(self):
        """Short entered at $100, now at $80 → return = +20%, unrealised > 0."""
        pos = _make_open_pos("SMCI", entry=100.0, direction="short")
        result = _build_direct(
            positions=[pos],
            extra_prices={"SMCI": {"last_price": 80.0, "prev_close": 90.0}},
        )
        mn = next(v for v in result["variants"] if v["variant_id"] == "market_neutral_spread")
        smci_pos = next((p for p in mn["positions"] if p["ticker"] == "SMCI"), None)
        assert smci_pos is not None
        assert smci_pos["return_pct"] > 0, (
            f"Short profit should be positive when price falls; got {smci_pos['return_pct']}"
        )
        assert abs(smci_pos["return_pct"] - 20.0) < 0.1
        assert smci_pos["unrealised_pnl"] > 0

    def test_short_return_negative_when_price_rises(self):
        """Short entered at $100, now at $120 → return = -20%, unrealised < 0."""
        pos = _make_open_pos("SMCI", entry=100.0, direction="short")
        result = _build_direct(
            positions=[pos],
            extra_prices={"SMCI": {"last_price": 120.0, "prev_close": 110.0}},
        )
        mn = next(v for v in result["variants"] if v["variant_id"] == "market_neutral_spread")
        smci_pos = next((p for p in mn["positions"] if p["ticker"] == "SMCI"), None)
        assert smci_pos is not None
        assert smci_pos["return_pct"] < 0
        assert abs(smci_pos["return_pct"] - (-20.0)) < 0.1
        assert smci_pos["unrealised_pnl"] < 0

    def test_long_return_unchanged(self):
        """Long position MtM must be unaffected by the short-sign fix."""
        pos = {
            "variant_id": "baseline_current_governance",
            "ticker": "NVDA",
            "entry_price_net": 100.0,
            "shares": 10.0,
            "direction": "long",
            "is_open": True,
        }
        result = _build_direct(
            positions=[pos],
            extra_prices={"NVDA": {"last_price": 110.0, "prev_close": 100.0}},
        )
        base = next(v for v in result["variants"] if v["variant_id"] == "baseline_current_governance")
        nvda_pos = next((p for p in base["positions"] if p["ticker"] == "NVDA"), None)
        assert nvda_pos is not None
        assert nvda_pos["return_pct"] > 0
        assert abs(nvda_pos["return_pct"] - 10.0) < 0.1

    def test_direction_field_in_position(self):
        """direction field must be present in live position output."""
        pos = _make_open_pos("SMCI", entry=100.0, direction="short")
        result = _build_direct(positions=[pos])
        mn = next(v for v in result["variants"] if v["variant_id"] == "market_neutral_spread")
        smci_pos = next((p for p in mn["positions"] if p["ticker"] == "SMCI"), None)
        assert smci_pos is not None
        assert smci_pos.get("direction") == "short"


# ── market_neutral excluded from best/worst ────────────────────────────────────

class TestMNExcludedFromRanking:
    def test_best_variant_is_not_market_neutral(self):
        """best_variant_id must never be market_neutral_spread."""
        result = _build_direct()
        assert result["best_variant_id"] != "market_neutral_spread", (
            "market_neutral_spread must be excluded from best/worst ranking"
        )

    def test_worst_variant_is_not_market_neutral(self):
        result = _build_direct()
        assert result["worst_variant_id"] != "market_neutral_spread"

    def test_alpha_vs_spy_is_none_for_mn(self):
        """alpha_vs_spy_pct must be None for market_neutral — it is not compared to SPY."""
        result = _build_direct()
        mn = next(v for v in result["variants"] if v["variant_id"] == "market_neutral_spread")
        assert mn["alpha_vs_spy_pct"] is None
        assert mn["spy_return_pct"] is None

    def test_spread_metrics_passed_through(self):
        """spread_metrics dict from variant_summary must appear in live JSON."""
        result = _build_direct()
        mn = next(v for v in result["variants"] if v["variant_id"] == "market_neutral_spread")
        assert "spread_metrics" in mn
        sm = mn["spread_metrics"]
        assert sm is not None
        assert sm.get("spread_return_pct") == 14.7
        assert sm.get("n_long_trades") == 4

    def test_long_only_variants_still_ranked(self):
        """Long-only variants still participate in best/worst ranking."""
        result = _build_direct()
        assert result["best_variant_id"] == "baseline_current_governance"
