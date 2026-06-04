"""The three growth arms (v2) — same pipeline, different DISCOVERY FILTER, each its own paper book.

  A — obvious theme leaders only.
  B — leaders + second-order bottleneck names.
  C — second-order bottleneck names only.

Each arm is scored independently vs the growth ETF (QQQ) and vs each other, so we learn which
edge-focus actually wins. Definitions are read from the LOCKED growth_mandate_v1 pre-registration.
"""
from __future__ import annotations

from olympus.preregistration.spec import load_spec

_SPEC = load_spec("growth_mandate_v1")
BENCHMARK_ETF = _SPEC["benchmark"]["primary_etf"]          # QQQ
_ARMS_SPEC = _SPEC["arms"]

ARM_IDS = ("A", "B", "C")


def allowed_roles(arm_id: str) -> list[str]:
    return list(_ARMS_SPEC[arm_id]["allowed_roles"])


def label(arm_id: str) -> str:
    return _ARMS_SPEC[arm_id]["label"]


def all_arms() -> list[dict]:
    return [{"id": a, "label": label(a), "allowed_roles": allowed_roles(a)} for a in ARM_IDS]
