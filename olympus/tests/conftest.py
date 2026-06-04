"""Shared test fixtures.

Tests must NEVER read the user's private real holdings (portfolio_policy.real.yaml). Force the
committed EXAMPLE core for every test so results are deterministic and private data stays out.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from olympus.core import config   # noqa: E402


@pytest.fixture(autouse=True)
def _example_policy_only():
    config.set_standalone(True)    # use the example core (core_supplied:false), not real holdings
    yield
    config.set_standalone(False)
