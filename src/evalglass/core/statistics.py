"""Honest interval estimators for metric aggregation (M7 T1, G1).

Alpha aggregated to a bare point estimate with no uncertainty of any kind. This
module supplies the *non-degenerate* intervals a decision policy can compare a
threshold against, without leaving the Evaluation Core: pure functions over
``math`` and ``statistics`` only, deterministic, effect-free.

Two estimands matter for EvalGlass metrics:

* **Proportion** (binary / pass-rate metrics) — the **Wilson score interval**.
  Unlike the naive ``p ± z·sqrt(p(1-p)/n)`` band it never collapses to zero width
  at ``p ∈ {0, 1}`` (the exact case observed in the field: three-for-three is *not* proof), and
  it stays inside ``[0, 1]``.
* **Mean** (continuous metrics) — a **Student-t** interval, honest at small ``n``
  (a t-quantile at ``n=3`` is far wider than the normal ``z`` alpha never even
  computed). The t-quantile is obtained from the regularized incomplete beta
  function, so no third-party dependency is needed.

Every interval names the ``method`` it used; the caller records it so a reader can
see which assumptions licensed the width. See ``docs/TETA_REDESIGN.md`` §5.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from evalglass.core._validation import ContractError

DEFAULT_LEVEL = 0.95

#: Computed interval bounds are rounded to this many decimal places before they enter
#: typed artifacts. ``sqrt`` / t-quantile results carry platform-dependent noise in their
#: last ULP (macOS arm64 and Linux x86_64 disagree at ~1e-16), which would make
#: ``RunRecord`` / ``Scorecard`` JSON non-portable and cross-platform baseline comparisons
#: show spurious deltas. Twelve places keeps far more precision than any confidence interval
#: needs while erasing that noise. See ADR 0044.
_STABLE_DP = 12


def _stable(x: float) -> float:
    """Round a computed interval bound to a platform-independent precision (:data:`_STABLE_DP`)."""
    return round(x, _STABLE_DP)


# --------------------------------------------------------------------------- #
# Quantiles
# --------------------------------------------------------------------------- #


def z_for_level(level: float = DEFAULT_LEVEL) -> float:
    """Two-sided standard-normal quantile for a confidence ``level`` (e.g. 1.96)."""
    _check_level(level)
    return statistics.NormalDist().inv_cdf(0.5 + level / 2.0)


def _check_level(level: float) -> None:
    if not (isinstance(level, float | int) and not isinstance(level, bool)):
        raise ContractError(f"confidence level must be a number, got {level!r}")
    if not (0.0 < level < 1.0):
        raise ContractError(f"confidence level must be in (0, 1), got {level!r}")


def _reg_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)`` (Numerical Recipes ``betai``)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) + ln_beta)
    # Use the continued fraction on whichever tail converges quickly.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 300
    eps = 3.0e-14
    fpmin = 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _student_t_sf(t: float, df: float) -> float:
    """Upper-tail survival ``P(T > t)`` for Student's t with ``df`` degrees of freedom."""
    x = df / (df + t * t)
    tail = 0.5 * _reg_incomplete_beta(x, df / 2.0, 0.5)
    return tail if t >= 0.0 else 1.0 - tail


def student_t_ppf(p: float, df: float) -> float:
    """Inverse CDF of Student's t: the ``t`` with ``P(T ≤ t) = p``.

    Solved by bisection on the (monotone) survival function; accurate to ~1e-10.
    Used for two-sided mean intervals at ``p = 0.5 + level/2``.
    """
    if not (0.0 < p < 1.0):
        raise ContractError(f"t-quantile probability must be in (0, 1), got {p!r}")
    if df <= 0.0:
        raise ContractError(f"degrees of freedom must be positive, got {df!r}")
    if p == 0.5:
        return 0.0
    upper = p > 0.5
    target = (1.0 - p) if upper else p  # survival value we solve _student_t_sf(t)=target
    lo, hi = 0.0, 1.0
    while _student_t_sf(hi, df) > target:
        hi *= 2.0
        if hi > 1.0e12:
            break
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _student_t_sf(mid, df) > target:
            lo = mid
        else:
            hi = mid
    t = 0.5 * (lo + hi)
    return t if upper else -t


# --------------------------------------------------------------------------- #
# Intervals
# --------------------------------------------------------------------------- #


def wilson_interval(successes: int, n: int, level: float = DEFAULT_LEVEL) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, clamped to ``[0, 1]``.

    Non-degenerate at ``p ∈ {0, 1}`` — the reason it replaces the naive SEM band.
    """
    _check_level(level)
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ContractError(f"wilson_interval: n must be a positive integer, got {n!r}")
    if isinstance(successes, bool) or not isinstance(successes, int) or not (0 <= successes <= n):
        raise ContractError(f"wilson_interval: successes must be in [0, {n}], got {successes!r}")
    z = z_for_level(level)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (_stable(max(0.0, center - half)), _stable(min(1.0, center + half)))


def mean_interval(
    values: Sequence[float], level: float = DEFAULT_LEVEL
) -> tuple[float, float] | None:
    """Two-sided Student-t confidence interval for a mean; ``None`` when ``n < 2``.

    Domain-agnostic: it does not clamp to a metric's declared range — that is the
    caller's decision, because a mean can legitimately sit anywhere in the range.
    """
    _check_level(level)
    n = len(values)
    if n < 2:
        return None
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    if sd == 0.0:
        return (_stable(mean), _stable(mean))
    t = student_t_ppf(0.5 + level / 2.0, df=n - 1)
    half = t * sd / math.sqrt(n)
    return (_stable(mean - half), _stable(mean + half))


def rule_of_three_upper(n: int) -> float:
    """Upper 95% bound on an unobserved event rate given ``n`` clean trials, capped at 1.0.

    When ``p̂ = 0`` (or ``1`` for the complementary rate) the empirical band has zero
    width; the rule of three (``3/n``) states what the sample could still hide. Capped
    at 1.0 so it can never read as a probability above one (beta-improved A-lesson).
    """
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ContractError(f"rule_of_three_upper: n must be a positive integer, got {n!r}")
    return min(1.0, 3.0 / n)
