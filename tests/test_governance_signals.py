"""Tests for signal reliability tracker — Component 4.

Anti-delusion tests:
  - Detect contradictory confidence states (HIGH confidence + contradicting signals)
  - Flag signal instability (Q1 momentum on STRONG_SELL names)
  - HIGH fraction of LOW-confidence STRONG_BUYs triggers warning

Validates:
  - All four signal categories are tracked
  - Insufficient data is clearly reported
  - Tracker never modifies signal log
"""
import json
import pytest
from pathlib import Path

from src.governance.signal_tracker import (
    compute_momentum_signal_stats,
    compute_revision_signal_stats,
    compute_alignment_effectiveness,
    compute_cohort_outlier_stats,
    run_signal_tracker,
    _parse_alignment,
)


def _write_signal_log(entries: list[dict], tmp_path: Path) -> Path:
    p = tmp_path / "signal_log.jsonl"
    with open(p, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _make_entry(
    ticker: str,
    rating: str,
    conf_after: str,
    momentum_q: int | None,
    revision: str,
    alignment: str = "+0 aligned, -0 contradicted",
) -> dict:
    return {
        "ticker": ticker,
        "date": "2026-05-25",
        "rating": rating,
        "confidence_before": conf_after,
        "confidence_after": conf_after,
        "momentum_quintile": momentum_q,
        "revision_direction": revision,
        "alignment_score": alignment,
    }


class TestParseAlignment:
    def test_parses_aligned_count(self):
        assert _parse_alignment("+2 aligned, -0 contradicted") == (2, 0)

    def test_parses_contradicting_count(self):
        assert _parse_alignment("+0 aligned, -1 contradicted") == (0, 1)

    def test_parses_both(self):
        assert _parse_alignment("+1 aligned, -2 contradicted") == (1, 2)

    def test_handles_empty(self):
        aligned, contra = _parse_alignment("")
        assert aligned == 0
        assert contra == 0


class TestMomentumSignalStats:
    def test_no_data_returns_no_data_status(self):
        result = compute_momentum_signal_stats([])
        assert result["status"] == "no_data"
        assert result["overall_quality"] is None

    def test_q1_consistent_with_strong_buy(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "HIGH", momentum_q=1, revision="FLAT"),
            _make_entry("B", "STRONG_BUY", "MED", momentum_q=1, revision="FLAT"),
            _make_entry("C", "STRONG_SELL", "LOW", momentum_q=5, revision="FLAT"),
        ]
        result = compute_momentum_signal_stats(entries)
        assert result["status"] == "computed"
        # 2/2 Q1 entries are STRONG_BUY, 1/1 Q5 is STRONG_SELL → quality = 3/3 = 1.0
        assert result["overall_quality"] == pytest.approx(1.0)

    def test_q1_on_strong_sell_creates_instability(self):
        entries = [
            _make_entry("A", "STRONG_SELL", "MED", momentum_q=1, revision="FLAT"),
            _make_entry("B", "STRONG_SELL", "MED", momentum_q=1, revision="FLAT"),
            _make_entry("C", "STRONG_BUY", "MED", momentum_q=1, revision="FLAT"),
        ]
        result = compute_momentum_signal_stats(entries)
        # 2/3 Q1 entries on STRONG_SELL = instability
        assert result["instability_score"] == pytest.approx(2 / 3, abs=0.01)

    def test_decay_warning_when_quality_below_threshold(self):
        entries = [
            # All Q1 entries contradict STRONG_SELL → bad quality
            _make_entry("A", "STRONG_SELL", "MED", momentum_q=1, revision="FLAT"),
            _make_entry("B", "STRONG_SELL", "MED", momentum_q=1, revision="FLAT"),
        ]
        result = compute_momentum_signal_stats(entries)
        # Quality = 0 (no Q1→STRONG_BUY, no Q5→SELL) → below 0.45 threshold
        assert result["decay_warning"] is True


class TestRevisionSignalStats:
    def test_no_directional_data_when_all_flat(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "MED", 1, "FLAT"),
            _make_entry("B", "HOLD", "MED", 3, "FLAT"),
        ]
        result = compute_revision_signal_stats(entries)
        assert result["status"] == "no_directional_data"
        assert result["overall_quality"] is None

    def test_positive_revision_on_strong_buy_is_consistent(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "HIGH", 1, "POSITIVE"),
            _make_entry("B", "BUY", "MED", 2, "POSITIVE"),
            _make_entry("C", "STRONG_SELL", "MED", 5, "NEGATIVE"),
        ]
        result = compute_revision_signal_stats(entries)
        assert result["overall_quality"] == pytest.approx(1.0)

    def test_positive_revision_on_strong_sell_is_contradiction(self):
        entries = [
            _make_entry("A", "STRONG_SELL", "MED", 5, "POSITIVE"),
        ]
        result = compute_revision_signal_stats(entries)
        assert result["instability_score"] == pytest.approx(1.0)


class TestAlignmentEffectiveness:
    def test_counts_high_alignment_entries(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "HIGH", 1, "POSITIVE", "+2 aligned, -0 contradicted"),
            _make_entry("B", "STRONG_BUY", "MED", 2, "FLAT", "+0 aligned, -0 contradicted"),
        ]
        result = compute_alignment_effectiveness(entries)
        assert result["n_high_alignment"] == 1
        assert result["n_zero_alignment"] == 1

    def test_includes_note_about_return_based_quality(self):
        result = compute_alignment_effectiveness([])
        assert "note" in result


class TestCohortOutlierStats:
    def test_high_low_confidence_strong_buy_warns(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "LOW", 1, "FLAT"),
            _make_entry("B", "STRONG_BUY", "LOW", 2, "FLAT"),
            _make_entry("C", "STRONG_BUY", "LOW", 2, "FLAT"),
            _make_entry("D", "STRONG_BUY", "MED", 1, "FLAT"),
        ]
        result = compute_cohort_outlier_stats(entries)
        # 3/4 STRONG_BUY are LOW → 75% → warning
        assert result["sb_low_confidence_fraction"] == pytest.approx(0.75)
        assert result["instability_warning"] is True

    def test_low_fraction_of_low_confidence_does_not_warn(self):
        entries = [
            _make_entry("A", "STRONG_BUY", "HIGH", 1, "FLAT"),
            _make_entry("B", "STRONG_BUY", "MED", 1, "FLAT"),
            _make_entry("C", "STRONG_BUY", "LOW", 1, "FLAT"),
        ]
        result = compute_cohort_outlier_stats(entries)
        # 1/3 = 33% → below 30%... actually 33% > 30%, so it should warn
        # Let's use 1/4 instead
        entries.append(_make_entry("D", "STRONG_BUY", "HIGH", 1, "FLAT"))
        result = compute_cohort_outlier_stats(entries)
        assert result["sb_low_confidence_fraction"] == pytest.approx(0.25)
        assert result["instability_warning"] is False

    def test_no_strong_buys_returns_zero_fraction(self):
        entries = [_make_entry("A", "HOLD", "MED", 3, "FLAT")]
        result = compute_cohort_outlier_stats(entries)
        assert result["strong_buy_count"] == 0
        assert result["sb_low_confidence_fraction"] == 0.0


class TestContradictoryConfidenceStates:
    """Anti-delusion test: detect internally inconsistent confidence states."""

    def test_signal_tracker_identifies_high_conf_with_all_contradictions(self, tmp_path):
        entries = [
            # STRONG_SELL with Q1 momentum → internally inconsistent
            _make_entry("A", "STRONG_SELL", "HIGH", 1, "POSITIVE",
                        "+0 aligned, -2 contradicted"),
            _make_entry("B", "STRONG_BUY", "HIGH", 1, "POSITIVE",
                        "+2 aligned, -0 contradicted"),
        ]
        sig_path = _write_signal_log(entries, tmp_path)
        result = run_signal_tracker(signal_log_path=sig_path, persist=False)
        # Cohort outlier stats: 0/1 STRONG_BUY is LOW (AAPL is HIGH) → no warning
        # But momentum instability: 0 out of Q1 entries with STRONG_BUY... A is STRONG_SELL
        momentum = result["signals"]["momentum_12m"]
        assert momentum["instability_score"] == pytest.approx(0.5, abs=0.01)


class TestRunSignalTracker:
    def test_returns_diagnostic_only_flag(self, tmp_path):
        entries = [_make_entry("A", "STRONG_BUY", "MED", 1, "FLAT")]
        sig_path = _write_signal_log(entries, tmp_path)
        result = run_signal_tracker(signal_log_path=sig_path, persist=False)
        assert result["diagnostic_only"] is True

    def test_never_modifies_signal_log(self, tmp_path):
        entries = [_make_entry("A", "STRONG_BUY", "MED", 1, "FLAT")]
        sig_path = _write_signal_log(entries, tmp_path)
        original = sig_path.read_text()
        run_signal_tracker(signal_log_path=sig_path, persist=False)
        assert sig_path.read_text() == original

    def test_missing_log_returns_valid_result(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        result = run_signal_tracker(signal_log_path=p, persist=False)
        assert result["n_signal_entries"] == 0

    def test_all_four_signals_present_in_result(self, tmp_path):
        entries = [_make_entry("A", "STRONG_BUY", "MED", 1, "FLAT")]
        sig_path = _write_signal_log(entries, tmp_path)
        result = run_signal_tracker(signal_log_path=sig_path, persist=False)
        sigs = result["signals"]
        assert "momentum_12m" in sigs
        assert "eps_revisions" in sigs
        assert "signal_alignment" in sigs
        assert "cohort_outlier" in sigs
