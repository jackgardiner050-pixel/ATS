"""Sleeve contract layer — a generalization of the single-cohort protocol machinery.

A "sleeve" is a self-contained, hypothesis-registered strategy with its own manifest,
cohort namespace ({sleeve_id}_c{n}), benchmark, and kill criteria. The existing Oracle
paper book is retrofitted as one sleeve (config/sleeves/oracle_v1.yaml). This layer
GENERALIZES config/protocol_lock.yaml, src/paper_trading.py, and
docs/OBSERVATION_PROTOCOL.md — it does not modify any of them (all are protocol-locked or
describe the running cohort). No locked file is touched.
"""
