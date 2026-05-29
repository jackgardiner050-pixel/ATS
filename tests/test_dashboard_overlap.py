"""Tests for the cross-system overlap block in generate_dashboard.py.

Confirms:
- "validation signal" and "independent confirmation" language never appears in output
- Holdings overlap percentage renders when systems share clusters
- High-overlap warning fires when Jaccard > 80%
- Side-by-side selection scores render for shared clusters
- Zero overlap renders without a high-overlap warning
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_dashboard import _compute_overlap_html


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _write_scai(tmp_path: Path, marks: list[dict]) -> Path:
    p = tmp_path / "structural_paper_summary.json"
    p.write_text(json.dumps({"marks": marks, "n_open": len(marks)}))
    return p


def _write_hermes(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / "journal.jsonl"
    lines = [json.dumps(r) for r in records]
    p.write_text("\n".join(lines))
    return p


def _scai_mark(cluster: str, score: float, tickers: list[str] | None = None) -> dict:
    return {
        "paper_id": f"sp_{cluster}",
        "basket_name": f"AI Infrastructure — {cluster}",
        "tickers": tickers or [],
        "selection_score": score,
        "status": "open",
    }


def _hermes_record(cluster: str, score: float) -> dict:
    return {
        "paper_id": f"hp_{cluster}",
        "basket_name": f"AI Infrastructure — {cluster}",
        "selection_score": score,
        "status": "open",
    }


# ─── Language guardrail ───────────────────────────────────────────────────────

FORBIDDEN_PHRASES = [
    "validation signal",
    "independent confirmation",
    "independent convergence",
]


class TestForbiddenLanguage:
    def test_no_forbidden_phrases_with_full_overlap(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.081, ["VRT", "SMCI"])])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.117)])
        html = _compute_overlap_html(scai, jrnl)
        for phrase in FORBIDDEN_PHRASES:
            assert phrase.lower() not in html.lower(), (
                f'Forbidden phrase "{phrase}" found in overlap HTML'
            )

    def test_no_forbidden_phrases_with_zero_overlap(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0, ["VRT"])])
        jrnl = _write_hermes(tmp_path, [_hermes_record("semiconductors", 2.5)])
        html = _compute_overlap_html(scai, jrnl)
        for phrase in FORBIDDEN_PHRASES:
            assert phrase.lower() not in html.lower(), (
                f'Forbidden phrase "{phrase}" found in overlap HTML'
            )

    def test_no_forbidden_phrases_when_files_missing(self, tmp_path):
        html = _compute_overlap_html(tmp_path / "no_scai.json", tmp_path / "no_jrnl.jsonl")
        for phrase in FORBIDDEN_PHRASES:
            assert phrase.lower() not in html.lower()


# ─── Overlap percentage renders ───────────────────────────────────────────────

class TestOverlapPercentage:
    def test_100_pct_overlap_single_cluster(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0, ["VRT"])])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "100%" in html
        assert "1/1" in html

    def test_50_pct_overlap_two_clusters(self, tmp_path):
        scai = _write_scai(tmp_path, [
            _scai_mark("cooling_power", 5.0, ["VRT"]),
            _scai_mark("semiconductors", 4.0, ["NVDA"]),
        ])
        jrnl = _write_hermes(tmp_path, [
            _hermes_record("cooling_power", 3.0),
            _hermes_record("cloud_infra", 2.0),
        ])
        html = _compute_overlap_html(scai, jrnl)
        # intersection=1 (cooling_power), union=3 → 33% Jaccard
        assert "33%" in html
        assert "1/3" in html

    def test_zero_overlap_shows_zero(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0)])
        jrnl = _write_hermes(tmp_path, [_hermes_record("semiconductors", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "0%" in html
        assert "0/2" in html

    def test_empty_returns_empty_string(self, tmp_path):
        html = _compute_overlap_html(tmp_path / "missing.json", tmp_path / "missing.jsonl")
        assert html == ""


# ─── High-overlap warning ─────────────────────────────────────────────────────

class TestHighOverlapWarning:
    def test_warning_fires_above_80_pct(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0)])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "Treat as one bet" in html
        assert "mechanical" in html.lower()

    def test_no_warning_below_threshold(self, tmp_path):
        # 1/3 Jaccard ≈ 33% → no warning
        scai = _write_scai(tmp_path, [
            _scai_mark("cooling_power", 5.0),
            _scai_mark("semis", 4.0),
        ])
        jrnl = _write_hermes(tmp_path, [
            _hermes_record("cooling_power", 3.0),
            _hermes_record("cloud_infra", 2.0),
        ])
        html = _compute_overlap_html(scai, jrnl)
        assert "Treat as one bet" not in html

    def test_warning_uses_mechanical_language(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0)])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "mechanical" in html.lower()
        assert "constraint" in html.lower()


# ─── Side-by-side score comparison ───────────────────────────────────────────

class TestSideBySideScores:
    def test_scores_shown_for_shared_cluster(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.081, ["VRT", "SMCI"])])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.117)])
        html = _compute_overlap_html(scai, jrnl)
        assert "5.081" in html
        assert "3.117" in html
        assert "SCAI-II" in html
        assert "Hermes" in html

    def test_scores_not_shown_when_no_shared_clusters(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0)])
        jrnl = _write_hermes(tmp_path, [_hermes_record("semis", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "5.0" not in html or "cooling_power" not in html

    def test_score_table_labels_constraint_driven(self, tmp_path):
        scai = _write_scai(tmp_path, [_scai_mark("cooling_power", 5.0)])
        jrnl = _write_hermes(tmp_path, [_hermes_record("cooling_power", 3.0)])
        html = _compute_overlap_html(scai, jrnl)
        assert "constraint" in html.lower()
