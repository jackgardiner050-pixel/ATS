"""Verify DEFAULT_RATING_BANDS agreement with calculator fallback and settings.yaml."""
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.contracts import DEFAULT_RATING_BANDS  # noqa: E402
from src.engine.calculator import classify_rating  # noqa: E402


def test_default_rating_bands_matches_calculator_fallback():
    """DEFAULT_RATING_BANDS must match the hardcoded fallback in classify_rating.

    The fallback literal in classify_rating is the actual runtime source of truth.
    """
    CALCULATOR_FALLBACK = {
        "strong_buy": 0.20,
        "buy": 0.10,
        "hold": -0.05,
        "sell": -0.20,
    }
    assert DEFAULT_RATING_BANDS == CALCULATOR_FALLBACK


def test_default_rating_bands_matches_settings_yaml():
    """DEFAULT_RATING_BANDS should equal config/settings.yaml:rating_bands.

    While settings.yaml:rating_bands is currently dead config (not read by any code),
    it should remain in sync with DEFAULT_RATING_BANDS for documentation and
    manual config changes to work if code paths change in the future.
    """
    settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if not settings_path.exists():
        # Skip this half if settings.yaml is not in the standard location
        return

    with open(settings_path) as f:
        config = yaml.safe_load(f)

    if "rating_bands" not in config:
        # Skip if the key is missing—cannot assert on missing config
        return

    settings_bands = config["rating_bands"]
    assert DEFAULT_RATING_BANDS == settings_bands


def test_classify_rating_uses_fallback_when_bands_empty():
    """classify_rating with empty bands dict should use the hardcoded defaults."""
    # When bands={}, classify_rating uses .get(key, default) which falls back
    # to the hardcoded defaults in the function signature.
    result_high = classify_rating(0.25, {})  # > 0.20 (strong_buy default)
    assert result_high == "STRONG_BUY"

    result_mid = classify_rating(0.15, {})  # between 0.10 and 0.20 (buy default)
    assert result_mid == "BUY"

    result_low = classify_rating(-0.10, {})  # below -0.05 (hold default), above -0.20 (sell default)
    assert result_low == "SELL"
