"""ATS Phase II — Governance and uncertainty-management layer.

Sits ABOVE the research agent. Purpose: reduce delusion, not find alpha.

Components:
  constitution   — immutable portfolio laws (Component 6)
  regime         — probabilistic market environment classification (Component 1)
  exposure       — portfolio concentration and factor analysis (Component 2)
  calibration    — empirical confidence tier performance (Component 3)
  signal_tracker — rolling signal reliability by regime (Component 4)
  adversarial    — LLM-powered thesis critique (Component 5)
  dashboard      — anti-delusion report aggregator (Component 7)

Hard constraints (inherited from ATS constitution):
  - No real trading
  - No autonomous execution
  - No self-modifying risk rules
  - No learning from realised P&L
  - All financial calculations deterministic and reproducible
"""
