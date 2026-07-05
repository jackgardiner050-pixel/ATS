"""Tests for scripts/attribution_report.py — bucketing with honest n."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.attribution_report import bucket_by, render_dimension, build_report


def _trade(mom, ret, alpha):
    return {"return_pct": ret, "alpha": alpha,
            "entry_signals": {"momentum_quintile": mom, "revision_direction": "UP",
                              "confidence_after": "HIGH"}}


def test_bucket_by_groups_and_averages():
    trades = [_trade(5, 0.10, 0.05), _trade(5, 0.20, 0.15), _trade(1, -0.10, -0.12)]
    stats = bucket_by(trades, "momentum_quintile")
    assert stats[5]["n"] == 2
    assert abs(stats[5]["mean_return"] - 0.15) < 1e-9
    assert abs(stats[5]["mean_alpha"] - 0.10) < 1e-9
    assert stats[1]["n"] == 1
    print("  ✓ bucket_by groups by signal and averages return/alpha")


def test_small_bucket_prints_insufficient_data():
    stats = bucket_by([_trade(5, 0.1, 0.05)], "momentum_quintile")
    lines = render_dimension("Momentum quintile", stats, min_n=10)
    assert any("insufficient data (n<10)" in ln for ln in lines)
    assert not any("mean_return" in ln for ln in lines)   # no tiny-sample mean shown
    print("  ✓ n<10 bucket prints 'insufficient data', not a mean")


def test_large_bucket_shows_mean():
    trades = [_trade(5, 0.10, 0.05) for _ in range(12)]
    lines = render_dimension("Momentum quintile", bucket_by(trades, "momentum_quintile"), min_n=10)
    assert any("mean_return" in ln and "n=12" in ln for ln in lines)
    print("  ✓ n>=10 bucket shows the mean with n")


def test_build_report_handles_no_tagged_trades():
    out = build_report([{"return_pct": 0.1, "alpha": 0.05}])   # no entry_signals
    assert "no entry-tagged trades yet" in out
    print("  ✓ report is honest when no entry_signals recorded")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All attribution-report tests passed.")
