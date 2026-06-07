"""Gaia rebalancing + glidepath — LOCKED discipline tests. Paper/research, no personal data."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discipline as D  # noqa: E402


def main() -> int:
    rules = D.load_rules()

    # ── lock (pre-registered, no silent tuning) ──
    assert D.verify_lock(rules), "rules must verify as locked + untampered"
    tampered = {**rules, "rebalancing": {**rules["rebalancing"], "band_pp": 10}}
    assert not D.verify_lock(tampered), "tampering with the band must break the lock"
    band = rules["rebalancing"]["band_pp"]
    assert band == 5
    print(f"  [lock] locked + hash-verified ({rules['lock_sha']}); tampering detected ✓")

    # ── rebalancing: a >5pp drift triggers; a <5pp drift does not ──
    target = {"global_equity": 0.70, "global_bonds": 0.25, "real_asset": 0.05}   # the 6/10 core
    drifted = {"global_equity": 0.77, "global_bonds": 0.18, "real_asset": 0.05}  # equity +7pp, bonds -7pp
    assert D.needs_rebalance(target, drifted, band), "a >5pp sleeve drift must trigger a rebalance"
    dp = D.drift_pp(target, drifted)
    assert max(abs(v) for v in dp.values()) > band
    reb = D.rebalanced_weights(target)
    assert reb == target and not D.needs_rebalance(target, reb, band), "rebalance resets to target"
    small = {"global_equity": 0.73, "global_bonds": 0.22, "real_asset": 0.05}    # +3pp / -3pp — within band
    assert not D.needs_rebalance(target, small, band), "a <5pp drift must NOT trigger"
    grown = D.drifted_weights(target, {"global_equity": 25.0, "global_bonds": -8.0, "real_asset": -8.0})
    assert grown["global_equity"] > target["global_equity"], "equity outperformance grows its weight (drift sim)"
    print(f"  [rebalance] drift {dp} (>{band}pp) → rebalance to target; +3pp drift → hold ✓")

    # ── glidepath: off holds the tier; on steps down on schedule (calendar-driven, not market) ──
    assert rules["glidepath"]["enabled"] is False
    assert D.target_tier(date(2045, 1, 1), rules) == 8, "while OFF the target stays the current tier (8)"
    on = {**rules, "glidepath": {**rules["glidepath"], "enabled": True}}
    assert D.target_tier(date(2030, 1, 1), on) == 8, "before the first step → current tier 8"
    assert D.target_tier(date(2036, 1, 1), on) == 7, "after the 2035 step → tier 7"
    assert D.target_tier(date(2041, 1, 1), on) == 6, "after the 2040 step → tier 6"
    print("  [glidepath] OFF holds 8 (even 2045); ON steps 8→7(2036)→6(2041) on its schedule ✓")

    print("\n  GAIA RULES TESTS PASSED — rebalance band + glidepath LOCKED, rules-based, not condition-timing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
