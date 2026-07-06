"""Live-pilot guard + advisory-live (Hermes E1) layer.

Human-executed (E1) live pilot: the system PROPOSES order cards; a human places every
order and reports fills. This layer holds NO broker libraries, imports NO decision math
(src/engine, src/signals), does NOT import swing-bot code (ringfence), and NEVER writes
to a paper cohort's positions or trades files. Enforced by tests/test_constitutional_guards.py
and the filesystem-sandbox test.
"""
from pathlib import Path

LIVE_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "live"
