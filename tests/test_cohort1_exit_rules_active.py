"""Cohort-1 day-0 activation guard (2026-07-05).

exit_rules_v2 is ACTIVE for the Cohort-1 window with parameters frozen at inception.
These tests guard against the config, the frozen protocol doc, and the code defaults
silently diverging later in the window (a §6 protocol-breaking change if they do).
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.paper_trading import DEFAULT_EXIT_V2_PARAMS

# The values frozen at Cohort-1 inception (docs/OBSERVATION_PROTOCOL.md §2.2).
FROZEN = {"pt_fraction": 1.0, "max_hold_days": 270, "stale_days": 28}


def test_exit_rules_v2_flag_is_true():
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text()) or {}
    assert settings.get("exit_rules_v2") is True, "exit_rules_v2 must be activated for Cohort-1"


def test_protocol_doc_records_frozen_param_block():
    """§2.2 must state the frozen parameters verbatim (config↔doc drift guard)."""
    doc = (ROOT / "docs" / "OBSERVATION_PROTOCOL.md").read_text().replace(" ", "")
    assert "pt_fraction=1.0" in doc
    assert "max_hold_days=270" in doc
    assert "stale_days=28" in doc


def test_code_defaults_match_frozen_values():
    """DEFAULT_EXIT_V2_PARAMS must equal the frozen block (config↔code drift guard)."""
    for k, v in FROZEN.items():
        assert DEFAULT_EXIT_V2_PARAMS[k] == v, f"{k}: code {DEFAULT_EXIT_V2_PARAMS[k]} != frozen {v}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All Cohort-1 exit-rules-active tests passed.")
