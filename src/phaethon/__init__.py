"""Phaethon — isolated forward-only LLM idea-generation experiment (paper, two arms).

Migrated under governance from the off-repo droplet publisher
(/root/phaethon-panel-publish.sh). The STRATEGY logic (the trader that produces
scorecard_public.json / book.json) is FROZEN and stays where it is — this package
only owns the *publish path*: the scorecard/holdings render, the governance checks
run on every publish, and cohort tagging. See scripts/phaethon/publish.sh (thin
cron wrapper) and phaethon_design_note.md.
"""

PHAETHON_COHORTS = ("phaethon_a", "phaethon_b")
ARM_COHORT = {"A": "phaethon_a", "B": "phaethon_b"}
