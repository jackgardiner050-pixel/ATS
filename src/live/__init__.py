"""Live-pilot guard layer.

Human-executed (E1) live-pilot limits and admissibility/breaker checks. This layer holds
NO broker libraries and imports NO decision math (src/engine, src/signals) — it only
guards. Enforced by tests/test_constitutional_guards.py.
"""
