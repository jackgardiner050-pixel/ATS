"""Gaia — rules-based diversified-core constructor + fee analysis.  RESEARCH TOOL, NOT ADVICE.

Loads the PUBLIC cores.yaml (generic cheap broad ETFs) and, if present, the PRIVATE (gitignored)
current_allocation.real.yaml. Computes each core's blended ongoing fee, the fee saving vs the
current thematic stack, and the long-run compounding effect of that saving. No personal data is
emitted by the public path — the current allocation only flows into the private fee comparison.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
CORES = _HERE / "cores.yaml"
CURRENT = _HERE / "current_allocation.real.yaml"   # PRIVATE / gitignored — may be absent


def load_cores() -> dict:
    return yaml.safe_load(CORES.read_text())


def load_current() -> dict | None:
    """The PRIVATE current allocation, or None if the gitignored file isn't present."""
    if not CURRENT.exists():
        return None
    return yaml.safe_load(CURRENT.read_text())


def core_blended_ocf(core: dict, sleeves: dict) -> float:
    """Weighted ongoing charge of a core (%) — sum(weight x sleeve OCF)."""
    return round(sum(w * sleeves[s]["ocf_pct"] for s, w in core["weights"].items()), 4)


def current_blended_ocf(current: dict) -> float:
    return round(sum(h["weight"] * h["ocf_pct"] for h in current["holdings"]), 4)


def expand_core_to_etfs(core: dict, sleeves: dict) -> dict:
    """Core -> {ticker: weight} using the chosen lowest-cost ETF per sleeve."""
    return {sleeves[s]["ticker"]: w for s, w in core["weights"].items()}


def compounding_uplift_pct(core_ocf: float, cur_ocf: float, years: int) -> float:
    """Extra terminal wealth (%) from the fee saving ALONE over `years`, assuming equal gross
    returns — fees compound: (1 - core/100)^Y / (1 - cur/100)^Y - 1."""
    if cur_ocf is None:
        return 0.0
    ratio = ((1 - core_ocf / 100) ** years) / ((1 - cur_ocf / 100) ** years)
    return round((ratio - 1) * 100, 2)


def current_platform_pct(current) -> float:
    """Platform/account fee (%/yr) of the current setup — 0 if none recorded."""
    return float((current.get("platform") or {}).get("fee_pct", 0.0)) if current else 0.0


def current_fixed_gbp(current) -> float:
    """Flat account fee (currency/yr) — a fixed cost on top of the % fees."""
    return float((current.get("platform") or {}).get("fixed_fee_gbp", 0.0)) if current else 0.0


def current_all_in_pct(current) -> float | None:
    """TRUE all-in %/yr of the current setup = blended fund OCF + platform fee % (excl. the flat fee)."""
    if not current:
        return None
    return round(current_blended_ocf(current) + current_platform_pct(current), 4)


def fee_analysis(years: int = 30) -> dict:
    """Per-core blended fee + the TRUE all-in saving vs current (fund OCF + platform), with the
    long-run compounding effect. A Gaia core on a commission-free broker pays fund OCF only (NO
    platform fee)."""
    cfg = load_cores()
    sleeves = cfg["sleeves"]
    current = load_current()
    cur_ocf = current_blended_ocf(current) if current else None          # fund OCF only
    cur_platform = current_platform_pct(current) if current else None
    cur_fixed = current_fixed_gbp(current) if current else None
    cur_all_in = current_all_in_pct(current)                             # fund OCF + platform %
    cur_is_example = bool(current.get("is_example")) if current else None

    rows = []
    for core in cfg["cores"]:
        ocf = core_blended_ocf(core, sleeves)                            # commission-free broker: fund OCF, NO platform
        all_in_saving_bps = round((cur_all_in - ocf) * 100, 1) if cur_all_in is not None else None
        fund_saving_bps = round((cur_ocf - ocf) * 100, 1) if cur_ocf is not None else None
        rows.append({
            "id": core["id"], "risk": core["risk"], "label": core["label"],
            "weights": core["weights"], "etfs": expand_core_to_etfs(core, sleeves),
            "blended_ocf_pct": ocf,
            "fund_saving_vs_current_bps": fund_saving_bps,               # funds only (cheaper ETFs)
            "all_in_saving_vs_current_bps": all_in_saving_bps,          # funds + dropping the platform fee
            "saving_vs_current_bps": all_in_saving_bps,                 # primary = the TRUE all-in saving
            "compounding_uplift_pct_30y": compounding_uplift_pct(ocf, cur_all_in, years) if cur_all_in else None,
        })
    return {
        "cores": rows, "sleeves": sleeves, "benchmark": cfg["benchmark"],
        "benchmark_ocf_pct": cfg["benchmark"]["ocf_pct"],
        "current_blended_ocf_pct": cur_ocf,            # PRIVATE — do not publish
        "current_platform_pct": cur_platform,          # PRIVATE
        "current_fixed_fee_gbp": cur_fixed,            # PRIVATE
        "current_all_in_pct": cur_all_in,              # PRIVATE
        "current_is_example": cur_is_example,
        "years": years, "framing": cfg.get("framing", []),
    }


def _print_report() -> None:
    fa = fee_analysis()
    print("Gaia — rules-based diversified cores (RESEARCH, NOT ADVICE)\n")
    for c in fa["cores"]:
        etfs = " · ".join(f"{t} {w:.0%}" for t, w in c["etfs"].items())
        print(f"  {c['label']}: {etfs}")
        print(f"     blended OCF {c['blended_ocf_pct']}%"
              + (f" · saving vs current {c['saving_vs_current_bps']}bps"
                 f" · ~+{c['compounding_uplift_pct_30y']}% wealth over 30y (fees alone)"
                 if c['saving_vs_current_bps'] is not None else " · (no current file — saving n/a)"))
    cur = fa["current_blended_ocf_pct"]
    if cur is not None:
        tag = " [EXAMPLE — replace current_allocation.real.yaml]" if fa["current_is_example"] else ""
        print(f"\n  Current allocation blended OCF (PRIVATE): {cur}%{tag}")
    print(f"  Benchmark {fa['benchmark']['ticker']} OCF {fa['benchmark_ocf_pct']}%")


if __name__ == "__main__":
    _print_report()
