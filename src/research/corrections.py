"""Multiple-testing corrections for the hypothesis registry.

Every Stage-1 report template must call BOTH of these — the point of the registry is that
the denominator (m = every hypothesis ever tested) is honest, so the bar rises with each
new test.

References
----------
Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality." The Journal of Portfolio
Management, 40(5), 94–107. The closed forms below are Eqs. (in that paper) for the
Probabilistic Sharpe Ratio and its deflated benchmark SR0 (expected maximum Sharpe under
the null across m independent trials).
"""
from __future__ import annotations

from math import exp, sqrt

from scipy.stats import norm

EULER_MASCHERONI = 0.5772156649015329


def bonferroni_alpha(m: int) -> float:
    """Bonferroni-corrected significance level for m tests: 0.05 / m."""
    if m < 1:
        raise ValueError("m (total entries ever) must be >= 1")
    return 0.05 / m


def _sr_variance_term(sr: float, skew: float, kurt: float) -> float:
    """1 − γ3·SR + (γ4−1)/4·SR²  — the non-normality-adjusted variance term (PSR denom²)."""
    return 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr


def probabilistic_sharpe_ratio(sr: float, n_obs: int, skew: float, kurt: float,
                               sr_benchmark: float = 0.0) -> float:
    """PSR: P(true SR > sr_benchmark) given observed sr over n_obs returns, adjusting for
    skew/kurtosis (Bailey & López de Prado 2012/2014)."""
    denom = sqrt(_sr_variance_term(sr, skew, kurt))
    return float(norm.cdf((sr - sr_benchmark) * sqrt(n_obs - 1) / denom))


def expected_max_sharpe(m: int, var_sr: float) -> float:
    """SR0: expected maximum Sharpe under the null across m independent trials, given the
    cross-trial variance of the Sharpe estimates (Bailey & López de Prado 2014)."""
    if m < 2:
        raise ValueError("expected_max_sharpe needs m >= 2 trials")
    z1 = norm.ppf(1.0 - 1.0 / m)
    z2 = norm.ppf(1.0 - 1.0 / (m * exp(1)))
    return float(sqrt(var_sr) * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2))


def deflated_sharpe(sr: float, n_obs: int, m: int, skew: float, kurt: float,
                    var_sr: float | None = None) -> float:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014): PSR evaluated against the
    deflated benchmark SR0 = expected max Sharpe under the null over m trials.

    DSR = Φ( (SR − SR0)·√(n−1) / √(1 − γ3·SR + (γ4−1)/4·SR²) )

    var_sr is the variance of the Sharpe estimates ACROSS the m trials. When it is not
    separately available it defaults to the sampling variance of THIS Sharpe estimator,
    Var(ŜR) ≈ (1 − γ3·SR + (γ4−1)/4·SR²)/(n−1) — documented, conservative fallback so the
    required signature (sr, n_obs, m, skew, kurt) is self-contained.
    """
    if var_sr is None:
        var_sr = _sr_variance_term(sr, skew, kurt) / (n_obs - 1)
    sr0 = expected_max_sharpe(m, var_sr)
    return probabilistic_sharpe_ratio(sr, n_obs, skew, kurt, sr_benchmark=sr0)
