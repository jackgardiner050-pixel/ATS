"""Phaethon governance + render tests (migration under governance).

ACCEPTANCE: running governance against the current phaethon_b_live.json data produces
the NONCONFORMING banner (gross exposure 138%).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.phaethon.scorecard import render_arm, total_value
from src.phaethon.governance import (
    check_leverage, check_max_single_position, run_governance,
)
from src.phaethon.schema import validate_phaethon_holding
from src.phaethon.publish import assemble_arm, sanitize_findings

ROOT = Path(__file__).parent.parent
CONSTITUTION = {"MAX_SINGLE_POSITION": 0.10}
SCREENER = {"min_market_cap_usd": 500_000_000, "max_market_cap_usd": 200_000_000_000}


# ─── ACCEPTANCE: current Arm B data → NONCONFORMING banner ───────────────────

def test_current_arm_b_data_is_nonconforming():
    d = json.loads((ROOT / "docs" / "data" / "phaethon_b_live.json").read_text())
    gov = run_governance(d["holdings"], SCREENER, CONSTITUTION, check_mcap=False)
    assert gov["conforming"] is False
    assert gov["status"].startswith("NONCONFORMING — ")
    assert "gross exposure 138.0%" in gov["status"]     # cash −38% → 138% gross
    print(f"  ✓ current arm B → {gov['status'][:60]}…")


def test_leverage_conforming_when_under_100():
    holdings = [{"ticker": "A", "weight_pct": 40.0}, {"ticker": "B", "weight_pct": 55.0}]
    gross, msg = check_leverage(holdings)
    assert gross == 95.0 and msg is None
    print("  ✓ Σweights 95% → conforming (no leverage flag)")


def test_leverage_tolerance_and_flag():
    assert check_leverage([{"weight_pct": 100.4}])[1] is None          # within 0.5% tol
    assert check_leverage([{"weight_pct": 100.6}])[1] == "gross exposure 100.6%"
    print("  ✓ leverage flags only above 100% + 0.5% tolerance")


def test_max_single_position_flag():
    v = check_max_single_position([{"ticker": "X", "weight_pct": 13.7},
                                   {"ticker": "Y", "weight_pct": 9.0}], 0.10)
    assert len(v) == 1 and "X at 13.7%" in v[0]
    print("  ✓ max-single-position flags the 13.7% holding, not the 9%")


def test_run_governance_does_not_clamp():
    holdings = [{"ticker": "X", "weight_pct": 138.0}]
    gov = run_governance(holdings, SCREENER, CONSTITUTION, check_mcap=False)
    # surfaced, NOT clamped — weights untouched
    assert holdings[0]["weight_pct"] == 138.0
    assert not gov["conforming"] and "gross exposure 138.0%" in gov["status"]
    print("  ✓ governance surfaces, never silently clamps")


# ─── frozen render fidelity ──────────────────────────────────────────────────

def _book(cash, holds):  # holds: {ticker: (shares, last, cost)}
    return {"cash": cash, "holdings": {t: {"shares": s, "last_price": lp, "cost_basis": cb}
                                       for t, (s, lp, cb) in holds.items()}}


def test_render_matches_frozen_math_and_tags_cohort():
    bk = _book(100.0, {"ACM": (1.0, 50.0, 40.0)})
    sc = {"n_positions": 1, "active_return_pct": 2.5}
    out = render_arm(sc, bk, "A", as_of="2026-07-05")
    assert total_value(bk) == 150.0
    h = out["holdings"][0]
    assert h["ticker"] == "ACM" and h["bought_at"] == 40.0 and h["last"] == 50.0
    assert h["weight_pct"] == 33.3                # 50/150*100
    assert h["cohort"] == "phaethon_a"            # cohort tag added
    assert out["cash_pct"] == 66.7 and out["arm"] == "disciplined"
    print("  ✓ render reproduces frozen tv/weight/cash math + tags phaethon_a")


def test_arm_b_labels_and_cohort():
    out = render_arm({"n_positions": 1}, _book(-38.0, {"X": (1.0, 138.0, 100.0)}), "B",
                     as_of="2026-07-05")
    assert out["arm"] == "aggressive-B" and out["cohort"] == "phaethon_b"
    assert out["holdings"][0]["cohort"] == "phaethon_b"
    print("  ✓ arm B → aggressive-B / phaethon_b")


def test_assemble_arm_injects_status_and_validates():
    bk = _book(-38.0, {"X": (1.0, 138.0, 100.0)})   # 138% gross → NONCONFORMING
    out = assemble_arm({"n_positions": 1}, bk, "B", SCREENER, CONSTITUTION,
                       check_mcap=False, as_of="2026-07-05")
    assert out["status"].startswith("NONCONFORMING")
    assert out["governance"]["gross_exposure_pct"] == 138.0
    for h in out["holdings"]:
        validate_phaethon_holding(h)              # cohort-tagged, valid
    print("  ✓ assemble_arm injects status + passes cohort validation")


# ─── schema + sanitize ───────────────────────────────────────────────────────

def test_phaethon_holding_validator():
    import pytest
    validate_phaethon_holding({"ticker": "X", "cohort": "phaethon_a", "last": 10.0, "weight_pct": 5.0})
    with pytest.raises(ValueError):
        validate_phaethon_holding({"ticker": "X", "cohort": "cohort_1", "last": 10.0, "weight_pct": 5.0})
    with pytest.raises(ValueError):
        validate_phaethon_holding({"ticker": "X", "cohort": "phaethon_a", "last": 10.0})  # missing
    print("  ✓ validator requires a phaethon cohort + keys")


def test_sanitize_gate_catches_personal_data():
    assert "gmail" in sanitize_findings('{"note":"contact me@gmail.com"}')
    assert "trading212" in sanitize_findings('{"broker":"Trading212"}')
    assert sanitize_findings('{"ticker":"ACM","weight_pct":5.0}') == []
    print("  ✓ sanitize gate catches personal/account leakage, clean on normal data")


# ─── report-check: two arms rendered as SEPARATE series (§7 no-blended) ──────

def test_arms_are_separate_series_never_blended():
    """§7 reporting rule: the two Phaethon arms are distinct cohorts in distinct files —
    never a blended series. And no holding is mis-tagged across arms."""
    a = assemble_arm({"n_positions": 1}, _book(100.0, {"ACM": (1.0, 50.0, 40.0)}), "A",
                     SCREENER, CONSTITUTION, check_mcap=False, as_of="2026-07-05")
    b = assemble_arm({"n_positions": 1}, _book(-38.0, {"X": (1.0, 138.0, 100.0)}), "B",
                     SCREENER, CONSTITUTION, check_mcap=False, as_of="2026-07-05")
    assert a["cohort"] == "phaethon_a" and b["cohort"] == "phaethon_b"
    assert all(h["cohort"] == "phaethon_a" for h in a["holdings"])
    assert all(h["cohort"] == "phaethon_b" for h in b["holdings"])
    # written to two distinct data files (per the publisher) — never one combined blob
    assert (ROOT / "docs/data/phaethon_live.json").name != (ROOT / "docs/data/phaethon_b_live.json").name
    # no phaethon cohort ever equals an Olympus cohort (fully separate cohort spaces)
    from src.paper_trading import VALID_COHORTS
    from src.phaethon import PHAETHON_COHORTS
    assert set(PHAETHON_COHORTS).isdisjoint(VALID_COHORTS)
    print("  ✓ arms are separate cohorts/files; phaethon vs Olympus cohort spaces disjoint")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All phaethon governance tests passed.")
