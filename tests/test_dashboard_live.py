"""
Dashboard live-binding smoke tests.

Validates that:
  - ATS live JSON contains required fields with non-null values when prices are available
  - SCAI/Hermes live JSON contains required basket fields
  - Hermes v3 does not overwrite ATS/SCAI/Hermes fields
  - ATS index.html has correct element IDs and JS bindings
  - SCAI/Hermes index.html have correct element IDs
  - JSON null values produce "unavailable" text, not blank cells (via JS guard pattern)
  - posColor() handles null (null must not map to green)
"""

import json
import os
import pathlib
import re

import pytest

AGENT = pathlib.Path(__file__).parent.parent
DOCS = AGENT / "docs"
DATA = DOCS / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        pytest.skip(f"{name} not present — run fetch_live_prices.py first")
    return json.loads(p.read_text())


def _html(path: pathlib.Path) -> str:
    if not path.exists():
        pytest.skip(f"{path} not present")
    return path.read_text()


# ---------------------------------------------------------------------------
# ATS live JSON schema
# ---------------------------------------------------------------------------

class TestAtsLiveJson:
    def test_required_top_level_keys(self):
        d = _load("ats_live.json")
        for key in ("portfolio_return_pct", "spy_return_pct", "alpha_vs_spy_pct",
                    "portfolio_today_pct", "n_priced", "positions", "fetched_at_utc"):
            assert key in d, f"Missing key: {key}"

    def test_positions_have_required_fields(self):
        d = _load("ats_live.json")
        assert d.get("positions"), "positions array is empty"
        for p in d["positions"]:
            for field in ("ticker", "entry_price", "last_price", "return_pct", "day_change_pct"):
                assert field in p, f"Position missing field: {field}"

    def test_n_priced_matches_positions_with_prices(self):
        d = _load("ats_live.json")
        priced = sum(1 for p in d.get("positions", []) if p.get("last_price") is not None)
        assert d.get("n_priced") == priced

    def test_portfolio_return_not_null_when_priced(self):
        d = _load("ats_live.json")
        if d.get("n_priced", 0) > 0:
            assert d.get("portfolio_return_pct") is not None, \
                "portfolio_return_pct is null despite n_priced > 0"

    def test_spy_return_not_null_when_priced(self):
        d = _load("ats_live.json")
        if d.get("n_priced", 0) > 0:
            assert d.get("spy_return_pct") is not None, \
                "spy_return_pct is null despite n_priced > 0"


# ---------------------------------------------------------------------------
# SCAI live JSON schema
# ---------------------------------------------------------------------------

class TestScaiLiveJson:
    def test_required_top_level_keys(self):
        d = _load("scai_live.json")
        for key in ("portfolio_return_pct", "spy_return_pct", "alpha_vs_spy_pct",
                    "baskets", "fetched_at_utc", "spy_baseline_status"):
            assert key in d, f"Missing key: {key}"

    def test_baskets_have_required_fields(self):
        d = _load("scai_live.json")
        assert d.get("baskets"), "baskets array is empty"
        b = d["baskets"][0]
        for field in ("paper_id", "basket_return_pct", "spy_return_pct",
                      "spy_baseline_status", "last_prices", "returns"):
            assert field in b, f"Basket missing field: {field}"

    def test_spy_return_not_null_when_priced(self):
        d = _load("scai_live.json")
        if d.get("n_priced", 0) > 0:
            assert d.get("spy_return_pct") is not None


# ---------------------------------------------------------------------------
# Hermes live JSON schema
# ---------------------------------------------------------------------------

class TestHermesLiveJson:
    def test_required_top_level_keys(self):
        d = _load("hermes_live.json")
        for key in ("portfolio_return_pct", "spy_return_pct", "baskets", "fetched_at_utc"):
            assert key in d, f"Missing key: {key}"

    def test_baskets_have_spy_fields(self):
        d = _load("hermes_live.json")
        if d.get("baskets"):
            b = d["baskets"][0]
            assert "spy_return_pct" in b
            assert "spy_baseline_status" in b


# ---------------------------------------------------------------------------
# Hermes v3 does NOT overwrite ATS/SCAI/Hermes fields
# ---------------------------------------------------------------------------

class TestHermesV3Isolation:
    def test_hermes_v3_live_json_is_separate_file(self):
        assert (DATA / "hermes_v3_live.json").exists(), "hermes_v3_live.json missing"

    def test_hermes_v3_json_has_variants_key(self):
        d = _load("hermes_v3_live.json")
        assert "variants" in d, "hermes_v3_live.json missing 'variants'"

    def test_hermes_v3_json_does_not_have_ats_positions_key(self):
        """v3 JSON must not contain ATS position-level fields."""
        d = _load("hermes_v3_live.json")
        assert "positions" not in d or d.get("positions") is None

    def test_ats_json_unchanged_by_v3(self):
        """ATS JSON must still have its own portfolio_return_pct — not merged with v3."""
        ats = _load("ats_live.json")
        v3 = _load("hermes_v3_live.json")
        assert "portfolio_return_pct" in ats
        # v3 should not have positions array matching ATS tickers
        v3_tickers = {v.get("ticker") for v in v3.get("variants", [])}
        ats_tickers = {p["ticker"] for p in ats.get("positions", [])}
        assert not v3_tickers.intersection(ats_tickers), \
            "v3 variants array overlaps ATS tickers — possible schema pollution"


# ---------------------------------------------------------------------------
# HTML element IDs — ATS dashboard
# ---------------------------------------------------------------------------

# Note: test_live_port_return_id_exists, test_live_spy_return_id_exists,
# test_live_alpha_value_id_exists, test_pos_price_ids_exist,
# test_pos_return_ids_exist, test_pos_today_ids_exist were removed (commit f4dc996)
# — they tested ATS portfolio/position live-data HTML elements removed in the
# "retire old Research Systems table" dashboard redesign.

class TestAtsDashboardHtml:
    def test_ats_live_json_fetch_url(self):
        html = _html(DOCS / "index.html")
        assert "data/ats_live.json" in html, "ATS JS does not fetch ats_live.json"

    def test_poscolor_handles_null(self):
        """posColor must not return green for null — check the guard pattern."""
        html = _html(DOCS / "index.html")
        # The fix uses: if(v===null||v===undefined)return'#8b949e'
        assert "===null||v===undefined)return" in html.replace(" ", ""), \
            "posColor null guard not found in JS"

    def test_na_html_constant_defined(self):
        """NA_HTML constant must be present in ATS JS for unavailable display."""
        html = _html(DOCS / "index.html")
        assert "NA_HTML" in html or "unavailable" in html


# ---------------------------------------------------------------------------
# HTML element IDs — SCAI dashboard
# ---------------------------------------------------------------------------

class TestScaiDashboardHtml:
    def test_mc_port_ret_id_exists(self):
        html = _html(DOCS / "scai" / "index.html")
        assert 'id="mc-port-ret"' in html

    def test_mc_spy_ret_id_exists(self):
        html = _html(DOCS / "scai" / "index.html")
        assert 'id="mc-spy-ret"' in html

    def test_mc_alpha_id_exists(self):
        html = _html(DOCS / "scai" / "index.html")
        assert 'id="mc-alpha"' in html

    def test_scai_live_json_fetch_url(self):
        html = _html(DOCS / "scai" / "index.html")
        assert "../data/scai_live.json" in html

    def test_hermes_v3_nav_card_present(self):
        html = _html(DOCS / "scai" / "index.html")
        assert "hermes_v3" in html, "Hermes v3 nav card missing from SCAI dashboard"

    def test_unavailable_style_in_js(self):
        html = _html(DOCS / "scai" / "index.html")
        assert "unavailable" in html, "No 'unavailable' text in SCAI JS"

    def test_prices_unavailable_warning_in_js(self):
        html = _html(DOCS / "scai" / "index.html")
        assert "Prices unavailable" in html


# ---------------------------------------------------------------------------
# HTML element IDs — Hermes v1 dashboard
# ---------------------------------------------------------------------------

class TestHermesDashboardHtml:
    def test_mc_port_ret_id_exists(self):
        html = _html(DOCS / "hermes" / "index.html")
        assert 'id="mc-port-ret"' in html

    def test_mc_spy_ret_id_exists(self):
        html = _html(DOCS / "hermes" / "index.html")
        assert 'id="mc-spy-ret"' in html

    def test_hermes_live_json_fetch_url(self):
        html = _html(DOCS / "hermes" / "index.html")
        assert "../data/hermes_live.json" in html

    def test_hermes_v3_nav_card_present(self):
        html = _html(DOCS / "hermes" / "index.html")
        assert "hermes_v3" in html, "Hermes v3 nav card missing from Hermes v1 dashboard"

    def test_unavailable_style_in_js(self):
        html = _html(DOCS / "hermes" / "index.html")
        assert "unavailable" in html


# ---------------------------------------------------------------------------
# Hermes v3 dashboard
# ---------------------------------------------------------------------------

class TestHermesV3DashboardHtml:
    def test_hermes_v3_page_exists(self):
        assert (DOCS / "hermes_v3" / "index.html").exists()

    def test_hermes_v3_json_fetch_url(self):
        html = _html(DOCS / "hermes_v3" / "index.html")
        assert "hermes_v3_live.json" in html

    def test_hermes_v3_does_not_reference_ats_live(self):
        html = _html(DOCS / "hermes_v3" / "index.html")
        assert "ats_live.json" not in html, \
            "Hermes v3 dashboard references ats_live.json — possible schema pollution"

    def test_hermes_v3_nav_has_ats_link(self):
        html = _html(DOCS / "hermes_v3" / "index.html")
        assert "../index.html" in html, "Hermes v3 nav missing ATS link"
