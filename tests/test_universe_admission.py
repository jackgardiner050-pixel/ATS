"""Tests for src/universe/admission.py — market-cap admission band (PART A)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.universe.admission import (
    check_market_cap_admission,
    REASON_BELOW_MIN,
    REASON_ABOVE_MAX,
    REASON_UNVERIFIED,
)

# The documented band from config/settings.yaml (500M .. 200B).
SETTINGS = {"min_market_cap_usd": 500_000_000, "max_market_cap_usd": 200_000_000_000}


def test_below_floor_excluded():
    admitted, reason = check_market_cap_admission("TINY", 250_000_000, SETTINGS)
    assert admitted is False and reason == REASON_BELOW_MIN
    print("  ✓ below floor → excluded")


def test_above_cap_excluded():
    admitted, reason = check_market_cap_admission("MEGA", 5_000_000_000_000, SETTINGS)
    assert admitted is False and reason == REASON_ABOVE_MAX
    print("  ✓ above cap → excluded")


def test_within_band_admitted():
    admitted, reason = check_market_cap_admission("MID", 10_000_000_000, SETTINGS)
    assert admitted is True and reason is None
    print("  ✓ within band → admitted")


def test_boundary_values_inclusive():
    # exactly at the floor / cap is admitted (band is inclusive at the edges)
    assert check_market_cap_admission("F", 500_000_000, SETTINGS)[0] is True
    assert check_market_cap_admission("C", 200_000_000_000, SETTINGS)[0] is True
    print("  ✓ exact floor/cap are admitted")


def test_none_or_zero_mcap_admitted_but_flagged():
    for mc in (None, 0, -5):
        admitted, reason = check_market_cap_admission("UNK", mc, SETTINGS)
        assert admitted is True and reason == REASON_UNVERIFIED
    print("  ✓ None/0 market cap → admitted with mcap_unverified flag")


def test_settings_missing_key_raises():
    import pytest
    with pytest.raises(ValueError):
        check_market_cap_admission("X", 1_000_000_000, {"min_market_cap_usd": 5e8})
    with pytest.raises(ValueError):
        check_market_cap_admission("X", 1_000_000_000, {})
    print("  ✓ settings missing a cap key raises (never silently admits all)")


def test_underscore_string_settings_coerced():
    # some YAML loaders return '500_000_000' as a string — must still work
    s = {"min_market_cap_usd": "500_000_000", "max_market_cap_usd": "200_000_000_000"}
    assert check_market_cap_admission("TINY", 250_000_000, s)[1] == REASON_BELOW_MIN
    assert check_market_cap_admission("MID", 10_000_000_000, s)[0] is True
    print("  ✓ underscore-string thresholds are coerced")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All admission tests passed.")
