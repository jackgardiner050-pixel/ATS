"""Olympus paths + cross-repo seam wiring.

Olympus is an ORCHESTRATION layer: it wraps members that live in their own repos in place,
it does not copy them. This module puts those repos on sys.path so the adapters import the
REAL code (no stubs):
  - ~/agent/src/governance, src/portfolio   → governance limits, exposure, survivability
  - ~/labs/oracle                           → the thesis engine + its hash-chained forward-test ledger
  - ~/labs/awareness                        → Athena pre-mortem critic
  - ~/labs/experimental_pot_engine          → the real pit_ledger primitive
"""
from __future__ import annotations

import sys
from pathlib import Path

# config.py = .../agent/olympus/olympus/core/config.py
_THIS = Path(__file__).resolve()
OLYMPUS_REPO = _THIS.parents[2]          # ~/agent/olympus
AGENT_ROOT = _THIS.parents[3]            # ~/agent      (home of src.governance / src.portfolio)
LABS_ROOT = AGENT_ROOT.parent / "labs"   # ~/labs       (oracle, awareness, experimental_pot_engine)
TRADING_ROOT = AGENT_ROOT.parent / "trading"

DATA_DIR = OLYMPUS_REPO / "data"
LEDGER_DIR = DATA_DIR / "ledgers"
REPORTS_DIR = DATA_DIR / "reports"
_POLICY_DIR = OLYMPUS_REPO / "olympus" / "config"
PORTFOLIO_POLICY = _POLICY_DIR / "portfolio_policy.yaml"            # EXAMPLE core — committed
PORTFOLIO_POLICY_REAL = _POLICY_DIR / "portfolio_policy.real.yaml"  # REAL core — gitignored, never committed


def portfolio_policy_path():
    """Prefer the gitignored real-holdings file if present; else the committed example."""
    return PORTFOLIO_POLICY_REAL if PORTFOLIO_POLICY_REAL.exists() else PORTFOLIO_POLICY

# the real satellite paper book (the 12-stock Themis/ATS portfolio)
SATELLITE_POSITIONS = AGENT_ROOT / "data" / "paper_positions.yaml"
# the real constitution config consumed by src.governance.constitution
CONSTITUTION_YAML = AGENT_ROOT / "config" / "constitution.yaml"


def wire_paths() -> None:
    """Idempotently place the member repos on sys.path so adapters import the real code."""
    for p in (AGENT_ROOT, LABS_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


for _d in (DATA_DIR, LEDGER_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

wire_paths()
