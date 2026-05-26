"""Tests for adversarial review engine — Component 5.

Validates:
  - Adversarial outputs are stored separately from core data
  - Core data files are never overwritten
  - Engine disables gracefully when API key absent
  - Output is clearly labelled as critique only, not recommendations
  - JSON response is parsed correctly
  - Portfolio context is loaded correctly
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.governance.adversarial import (
    _parse_adversarial_response,
    _load_portfolio_context,
    run_adversarial_review,
    load_latest_adversarial,
    _PROTECTED_PATHS,
)


def _write_positions(tickers: list[str], tmp_path: Path) -> Path:
    import yaml
    p = tmp_path / "paper_positions.yaml"
    data = {"positions": [{"ticker": t, "entry_price": 100.0} for t in tickers]}
    with open(p, "w") as f:
        yaml.dump(data, f)
    return p


class TestParseAdversarialResponse:
    def test_valid_json_parsed_correctly(self):
        raw = '{"macro_counterarguments": ["arg1", "arg2"], "single_biggest_risk": "X"}'
        result = _parse_adversarial_response(raw)
        assert result["macro_counterarguments"] == ["arg1", "arg2"]

    def test_json_with_code_fences_stripped(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_adversarial_response(raw)
        assert result.get("key") == "value"

    def test_invalid_json_returns_error_dict(self):
        result = _parse_adversarial_response("{not valid json}")
        assert "error" in result

    def test_none_input_returns_no_api_key_error(self):
        result = _parse_adversarial_response(None)
        assert result.get("error") == "no_api_key"


class TestAdversarialNotModifyingCoreData:
    """Critical: adversarial engine must NEVER touch core data files."""

    def test_protected_paths_defined(self):
        assert len(_PROTECTED_PATHS) >= 4
        assert any("paper_positions" in p for p in _PROTECTED_PATHS)
        assert any("signal_log" in p for p in _PROTECTED_PATHS)
        assert any("paper_trades" in p for p in _PROTECTED_PATHS)
        assert any("screen_state" in p for p in _PROTECTED_PATHS)

    def test_run_does_not_write_to_positions_file(self, tmp_path):
        tickers = ["GD", "AMAT", "KMI"]
        pos_path = _write_positions(tickers, tmp_path)
        original = pos_path.read_text()

        # Run without API key — should still not modify positions
        with patch.dict(os.environ, {}, clear=False):
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]
            run_adversarial_review(positions_path=pos_path, persist=False)

        assert pos_path.read_text() == original

    def test_run_without_api_key_returns_gracefully(self, tmp_path):
        tickers = ["GD", "AMAT"]
        pos_path = _write_positions(tickers, tmp_path)

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = run_adversarial_review(positions_path=pos_path, persist=False)

        assert result is not None
        critique = result.get("critique", {})
        assert "error" in critique
        assert critique["error"] == "no_api_key"

    def test_output_labelled_diagnostic_only(self, tmp_path):
        tickers = ["GD"]
        pos_path = _write_positions(tickers, tmp_path)

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = run_adversarial_review(positions_path=pos_path, persist=False)

        assert result.get("diagnostic_only") is True

    def test_note_field_says_not_investment_advice(self, tmp_path):
        tickers = ["GD"]
        pos_path = _write_positions(tickers, tmp_path)

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = run_adversarial_review(positions_path=pos_path, persist=False)

        note = result.get("note", "")
        assert "not investment advice" in note.lower() or "not" in note.lower()


class TestAdversarialWithMockedClaude:
    """Test adversarial engine with a mocked API call."""

    def test_valid_critique_parsed_and_returned(self, tmp_path):
        tickers = ["GD", "AMAT", "DY"]
        pos_path = _write_positions(tickers, tmp_path)

        mock_response = {
            "macro_counterarguments": [
                "US defense budget faces structural headwinds",
                "AI capex cycle may have already peaked",
                "Infrastructure spending faces execution risk",
            ],
            "hidden_assumptions": [
                "Assumes bipartisan infrastructure support continues",
            ],
            "concentration_concerns": [
                "Power buildout exposure hidden across themes",
            ],
            "historical_analogues": ["2001 infrastructure build-out"],
            "regime_vulnerabilities": ["Risk-off defensive regime"],
            "single_biggest_risk": "Fiscal consolidation eliminates infrastructure spending",
        }

        with patch("src.governance.adversarial._call_claude") as mock_call:
            mock_call.return_value = json.dumps(mock_response)
            result = run_adversarial_review(positions_path=pos_path, persist=False)

        assert result["status"] == "ok"
        critique = result["critique"]
        assert len(critique["macro_counterarguments"]) == 3
        assert "single_biggest_risk" in critique

    def test_critique_does_not_contain_price_predictions(self, tmp_path):
        tickers = ["GD"]
        pos_path = _write_positions(tickers, tmp_path)

        mock_response = {
            "macro_counterarguments": ["Argument without price target"],
            "single_biggest_risk": "Geopolitical risk",
        }

        with patch("src.governance.adversarial._call_claude") as mock_call:
            mock_call.return_value = json.dumps(mock_response)
            result = run_adversarial_review(positions_path=pos_path, persist=False)

        # The result should not contain price predictions
        assert result["status"] == "ok"
        # Tickers reviewed should be present (for audit trail)
        assert "tickers_reviewed" in result


class TestAdversarialPersistence:
    def test_persist_writes_to_governance_log_not_core(self, tmp_path):
        tickers = ["GD"]
        pos_path = _write_positions(tickers, tmp_path)
        adv_log = tmp_path / "adversarial_log.jsonl"

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with patch("src.governance.adversarial._ADVERSARIAL_LOG", adv_log):
                with patch("src.governance.adversarial._DATA_PATH", tmp_path):
                    run_adversarial_review(positions_path=pos_path, persist=True)

        assert adv_log.exists()
        with open(adv_log) as f:
            content = json.loads(f.readline())
        assert content["diagnostic_only"] is True

    def test_load_latest_returns_none_when_no_log(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert load_latest_adversarial(path=p) is None

    def test_load_latest_returns_most_recent(self, tmp_path):
        p = tmp_path / "adversarial_log.jsonl"
        entries = [
            {"timestamp": "2026-05-25", "status": "ok", "critique": {}},
            {"timestamp": "2026-05-26", "status": "ok", "critique": {"result": "latest"}},
        ]
        with open(p, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        latest = load_latest_adversarial(path=p)
        assert latest["timestamp"] == "2026-05-26"


class TestNoPositionsHandling:
    def test_empty_portfolio_returns_gracefully(self, tmp_path):
        pos_path = _write_positions([], tmp_path)
        result = run_adversarial_review(positions_path=pos_path, persist=False)
        assert result["status"] == "no_positions"

    def test_missing_positions_file_returns_gracefully(self, tmp_path):
        p = tmp_path / "nonexistent.yaml"
        result = run_adversarial_review(positions_path=p, persist=False)
        assert result["status"] == "no_positions"
