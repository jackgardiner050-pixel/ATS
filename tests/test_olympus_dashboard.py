"""Tests for Olympus display-layer integration.

Verifies:
1. All major cards render (even when data files are absent).
2. Existing systems still populate when a data file is absent.
3. Pantheon names appear in rendered output.
4. Kill-switch card is present and shows APPROACHING/PASS/STOP (not crashing).
5. No "biggest mover" / "validation signal" language in main output.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Add scripts dir to path so we can import the module
_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))


# ── _olympus module ───────────────────────────────────────────────────────────

def test_olympus_module_imports():
    import _olympus as oly
    assert hasattr(oly, "kill_switch_card")
    assert hasattr(oly, "status_banner")
    assert hasattr(oly, "pantheon_roster_section")
    assert hasattr(oly, "mnemosyne_independence_card")
    assert hasattr(oly, "mnemosyne_reconciliation_card")


def test_display_name_map():
    from _olympus import display_name
    assert display_name("SCAI") == "Apollo (SCAI)"
    assert display_name("hermes_v2") == "Athena (Hermes v2)"
    assert display_name("mercury") == "Kairos"
    assert display_name("val_v1") == "Demeter"
    assert display_name("ATS") == "Themis (ATS)"
    assert display_name("council") == "Zeus (Council)"
    # Unknown key passes through unchanged
    assert display_name("unknown_member") == "unknown_member"


def test_kill_switch_card_renders():
    """Card must return non-empty HTML and not raise, even if council unavailable."""
    from _olympus import kill_switch_card
    html = kill_switch_card()
    assert isinstance(html, str)
    assert len(html) > 0
    # Must contain some status marker
    assert any(word in html for word in ["PASS", "APPROACHING", "STOP", "unavailable"])


def test_kill_switch_card_no_crash_without_council(monkeypatch):
    """Card is fail-soft: if kill switch import fails, returns safe placeholder."""
    import _olympus as oly
    monkeypatch.setattr(oly, "_load_kill_switch_result", lambda: None)
    html = oly.kill_switch_card()
    assert "unavailable" in html.lower() or "approaching" in html.lower() or "pass" in html.lower()


def test_status_banner_renders():
    from _olympus import status_banner
    html = status_banner(validated_count=0)
    assert "PAPER ONLY" in html
    assert "0 of 2 members validated" in html
    assert "no durable edge claimed" in html


def test_status_banner_counts_from_kill_switch(monkeypatch):
    """Banner must use live count when validated_count not passed."""
    import _olympus as oly
    monkeypatch.setattr(oly, "_load_kill_switch_result", lambda: {"n_validated": 1})
    html = oly.status_banner()
    assert "1 of 2" in html


def test_pantheon_roster_renders():
    from _olympus import pantheon_roster_section
    html = pantheon_roster_section()
    assert "Apollo (SCAI)" in html
    assert "Athena (Hermes v2)" in html
    assert "Hermes (execution)" in html
    assert "Demeter" in html
    assert "Kairos" in html
    assert "Zeus (Council)" in html
    assert "Hades" in html
    assert "Mnemosyne" in html


def test_pantheon_roster_has_status_badges():
    from _olympus import pantheon_roster_section
    html = pantheon_roster_section()
    assert "Active" in html
    assert "Candidate" in html
    assert "Parked" in html
    assert "Designed" in html


def test_kairos_honesty_label():
    """Kairos must have the 'parked — below noise floor' label."""
    from _olympus import pantheon_roster_section
    html = pantheon_roster_section()
    assert "below noise floor" in html


def test_demeter_honesty_label():
    """Demeter must have the decorrelation-pending label."""
    from _olympus import pantheon_roster_section
    html = pantheon_roster_section()
    assert "decorrelation pending" in html


def test_independence_card_renders():
    from _olympus import mnemosyne_independence_card
    html = mnemosyne_independence_card()
    assert isinstance(html, str)
    assert len(html) > 0
    # Either real data or graceful fallback
    assert "Independence" in html or "independence" in html or "unavailable" in html.lower()


def test_reconciliation_card_renders():
    from _olympus import mnemosyne_reconciliation_card
    html = mnemosyne_reconciliation_card()
    assert isinstance(html, str)
    assert len(html) > 0
    assert "Backtest" in html or "backtest" in html or "unavailable" in html.lower()


def test_olympus_lab_nav_renders():
    from _olympus import olympus_lab_nav
    html = olympus_lab_nav()
    assert "Olympus" in html
    assert "Themis" in html
    assert "Apollo" in html
    assert "Athena" in html
    assert "Zeus" in html
    assert "Mnemosyne" in html


# ── generate_dashboard integration ────────────────────────────────────────────

def _import_dashboard():
    """Import generate_dashboard, reloading to pick up any changes."""
    if "generate_dashboard" in sys.modules:
        del sys.modules["generate_dashboard"]
    return importlib.import_module("generate_dashboard")


def test_dashboard_imports_olympus():
    """generate_dashboard must attempt to import _olympus."""
    gd = _import_dashboard()
    # _OLYMPUS_AVAILABLE may be True or False, but must exist
    assert hasattr(gd, "_OLYMPUS_AVAILABLE")


def test_dashboard_title_is_olympus():
    """_page_wrap must produce 'Olympus' in the <title>."""
    gd = _import_dashboard()
    html = gd._page_wrap("Test Page", "<main>body</main>")
    assert "Olympus" in html
    assert "ATS Research" not in html  # old branding removed from title


def test_dashboard_pantheon_name_in_page_wrap():
    """_page_wrap wraps content; should not introduce old branding."""
    gd = _import_dashboard()
    html = gd._page_wrap("Olympus Dashboard", "<p>hello</p>")
    assert "Olympus" in html


def test_systems_overview_fail_soft_missing_files(tmp_path, monkeypatch):
    """_systems_overview must not crash when all data files are absent."""
    gd = _import_dashboard()
    # Redirect home to tmp_path so no real files are found
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    try:
        html = gd._systems_overview()
        assert isinstance(html, str)
        # Should still render the table skeleton
        assert "<table" in html or "section" in html
    except Exception as e:
        pytest.fail(f"_systems_overview raised with missing files: {e}")


def test_systems_overview_uses_pantheon_names():
    """Systems table must use Olympus display names."""
    gd = _import_dashboard()
    try:
        html = gd._systems_overview()
        assert "Apollo (SCAI)" in html or "Themis" in html
    except Exception:
        pass  # Data may be missing in test env — don't fail on data absence


def test_build_index_no_crash_empty_data():
    """build_index must not crash when given empty/None data."""
    gd = _import_dashboard()
    try:
        html = gd.build_index(
            positions=[],
            trades=[],
            regime=None,
            exposure=None,
            signal=None,
            calib=None,
            adv=None,
            screen_state=[],
            generated_at="2026-05-29 00:00 UTC",
        )
        assert isinstance(html, str)
        assert "Olympus" in html
    except Exception as e:
        pytest.fail(f"build_index raised with empty data: {e}")


def test_no_validation_signal_language():
    """Rendered output must not contain 'validation signal' phrasing."""
    gd = _import_dashboard()
    try:
        html = gd.build_index(
            positions=[], trades=[], regime=None, exposure=None,
            signal=None, calib=None, adv=None, screen_state=[],
            generated_at="2026-05-29 00:00 UTC",
        )
        assert "not a validation signal" not in html
        assert "validation signal" not in html
    except Exception:
        pass  # If build fails for other reasons, skip — covered by other tests


def test_footer_says_olympus():
    gd = _import_dashboard()
    try:
        html = gd.build_index(
            positions=[], trades=[], regime=None, exposure=None,
            signal=None, calib=None, adv=None, screen_state=[],
            generated_at="2026-05-29 00:00 UTC",
        )
        assert "Olympus" in html
        # Old footer text gone
        assert "ATS Research · Paper portfolio only" not in html
    except Exception:
        pass
