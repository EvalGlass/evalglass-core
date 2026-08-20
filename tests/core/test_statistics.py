"""Reference-value tests for the honest interval estimators (M7 T1, G1).

Expected numbers are external references (standard normal/t tables and the Wilson
formula), not values read back from the implementation, so they are a genuine
check. See src/evalglass/core/statistics.py and docs/TETA_REDESIGN.md §5.
"""

from __future__ import annotations

import math

import pytest

from evalglass.core._validation import ContractError
from evalglass.core.statistics import (
    mean_interval,
    rule_of_three_upper,
    student_t_ppf,
    wilson_interval,
    z_for_level,
)


def _close(a: float, b: float, tol: float = 1e-4) -> bool:
    return math.isclose(a, b, abs_tol=tol)


# --- normal quantile -------------------------------------------------------


def test_z_for_common_levels() -> None:
    assert _close(z_for_level(0.95), 1.959964)
    assert _close(z_for_level(0.90), 1.644854)
    assert _close(z_for_level(0.99), 2.575829)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, True])
def test_z_rejects_bad_level(bad: object) -> None:
    with pytest.raises(ContractError):
        z_for_level(bad)  # type: ignore[arg-type]


# --- Student-t quantile (external table values) ----------------------------


@pytest.mark.parametrize(
    ("df", "expected"),
    [
        (1, 12.706205),
        (2, 4.302653),
        (3, 3.182446),
        (4, 2.776445),
        (5, 2.570582),
        (10, 2.228139),
        (30, 2.042272),
        (100, 1.983972),
    ],
)
def test_student_t_ppf_975(df: int, expected: float) -> None:
    assert _close(student_t_ppf(0.975, df), expected, tol=1e-4)


def test_student_t_symmetry_and_median() -> None:
    assert student_t_ppf(0.5, 7) == 0.0
    assert _close(student_t_ppf(0.025, 5), -student_t_ppf(0.975, 5))


def test_student_t_approaches_normal_for_large_df() -> None:
    assert _close(student_t_ppf(0.975, 100000), 1.959964, tol=1e-3)


@pytest.mark.parametrize(("p", "df"), [(0.0, 5), (1.0, 5), (-0.1, 5), (0.5, 0), (0.5, -3)])
def test_student_t_rejects_bad_args(p: float, df: float) -> None:
    with pytest.raises(ContractError):
        student_t_ppf(p, df)


# --- Wilson interval -------------------------------------------------------


def test_wilson_never_degenerates_at_boundaries() -> None:
    # Three-for-three is NOT proof: the interval retains real width and stays <= 1.
    lo, hi = wilson_interval(3, 3)
    assert _close(lo, 0.438499, tol=1e-4)
    assert hi == 1.0
    assert lo > 0.0  # not zero-width, unlike the naive SEM band

    lo0, hi0 = wilson_interval(0, 3)
    assert lo0 == 0.0
    assert _close(hi0, 0.561501, tol=1e-4)


def test_wilson_one_for_one_is_wide() -> None:
    lo, hi = wilson_interval(1, 1)
    assert _close(lo, 0.206543, tol=1e-4)
    assert hi == 1.0


def test_wilson_half() -> None:
    # Plain (non-continuity-corrected) Wilson 95% for 50/100.
    lo, hi = wilson_interval(50, 100)
    assert _close(lo, 0.403832, tol=1e-4)
    assert _close(hi, 0.596168, tol=1e-4)


@pytest.mark.parametrize(
    ("k", "n"),
    [(0, 0), (2, 1), (-1, 5), (True, 3), (3, True)],
)
def test_wilson_rejects_bad_args(k: object, n: object) -> None:
    with pytest.raises(ContractError):
        wilson_interval(k, n)  # type: ignore[arg-type]


# --- mean interval ---------------------------------------------------------


def test_mean_interval_small_n_uses_t() -> None:
    # values with mean 0.95, sample sd 0.05, n=3 -> t_{.975,2}=4.302653
    lo, hi = mean_interval([0.90, 0.95, 1.00])  # type: ignore[misc]
    half = 4.302653 * 0.05 / math.sqrt(3)
    assert _close(lo, 0.95 - half, tol=1e-4)
    assert _close(hi, 0.95 + half, tol=1e-4)


def test_mean_interval_none_below_two() -> None:
    assert mean_interval([0.5]) is None
    assert mean_interval([]) is None


def test_mean_interval_zero_variance_is_a_point() -> None:
    result = mean_interval([0.7, 0.7, 0.7])
    assert result is not None
    lo, hi = result
    assert _close(lo, 0.7)
    assert _close(hi, 0.7)


# --- rule of three ---------------------------------------------------------


def test_rule_of_three_capped_at_one() -> None:
    assert rule_of_three_upper(3) == 1.0  # 3/3
    assert rule_of_three_upper(1) == 1.0  # 3/1 -> capped
    assert _close(rule_of_three_upper(30), 0.1)
    assert _close(rule_of_three_upper(100), 0.03)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_rule_of_three_rejects_bad_n(bad: object) -> None:
    with pytest.raises(ContractError):
        rule_of_three_upper(bad)  # type: ignore[arg-type]
