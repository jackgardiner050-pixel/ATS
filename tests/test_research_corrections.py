"""bonferroni_alpha + deflated_sharpe (Bailey & López de Prado 2014)."""
import sys
from math import exp, sqrt
from pathlib import Path

from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.research.corrections import (
    bonferroni_alpha, deflated_sharpe, expected_max_sharpe,
    probabilistic_sharpe_ratio, EULER_MASCHERONI,
)


def test_bonferroni():
    assert bonferroni_alpha(1) == 0.05
    assert bonferroni_alpha(2) == 0.025      # ACCEPTANCE: m=2 → 0.025
    assert bonferroni_alpha(10) == 0.005
    print("  ✓ bonferroni 0.05/m")


def test_deflated_sharpe_matches_closed_form():
    """Independent recomputation of the DSR closed form (catches coding errors)."""
    sr, n, m, skew, kurt = 0.12, 240, 20, -0.3, 5.0
    var_term = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    var_sr = var_term / (n - 1)
    sr0 = sqrt(var_sr) * ((1 - EULER_MASCHERONI) * norm.ppf(1 - 1 / m)
                          + EULER_MASCHERONI * norm.ppf(1 - 1 / (m * exp(1))))
    expected = norm.cdf((sr - sr0) * sqrt(n - 1) / sqrt(var_term))
    assert abs(deflated_sharpe(sr, n, m, skew, kurt) - expected) < 1e-12
    assert abs(expected_max_sharpe(m, var_sr) - sr0) < 1e-12
    print("  ✓ deflated_sharpe reproduces the Bailey & LdP 2014 closed form")


def test_deflated_sharpe_properties():
    base = dict(n_obs=240, m=20, skew=0.0, kurt=3.0)
    assert 0.0 <= deflated_sharpe(sr=0.1, **base) <= 1.0
    # higher observed Sharpe → higher DSR
    assert deflated_sharpe(sr=0.2, **base) > deflated_sharpe(sr=0.1, **base)
    # more trials m → higher null bar → lower DSR
    assert deflated_sharpe(sr=0.1, n_obs=240, m=200, skew=0, kurt=3) < \
           deflated_sharpe(sr=0.1, n_obs=240, m=2, skew=0, kurt=3)
    # DSR (deflated benchmark >= 0) never exceeds PSR vs 0
    assert deflated_sharpe(sr=0.1, **base) <= probabilistic_sharpe_ratio(0.1, 240, 0.0, 3.0)
    print("  ✓ DSR: in [0,1], ↑ in SR, ↓ in m, ≤ PSR(0)")


def test_var_sr_override_used():
    """The paper supplies a separate cross-trial variance; it must be honored when passed."""
    a = deflated_sharpe(0.1, 240, 20, 0, 3, var_sr=0.01)
    b = deflated_sharpe(0.1, 240, 20, 0, 3)          # default estimator variance
    assert a != b
    print("  ✓ explicit var_sr overrides the default")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("corrections tests passed.")
