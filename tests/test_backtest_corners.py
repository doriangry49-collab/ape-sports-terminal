"""Unit tests for Corner Backtest Engine."""

from __future__ import annotations

import math

from backtest_corners import poisson_cdf


def test_corner_backtest_math_properties():
    lmbda = 9.5
    # CDF monotonic
    c8 = poisson_cdf(8, lmbda)
    c9 = poisson_cdf(9, lmbda)
    c10 = poisson_cdf(10, lmbda)

    assert 0.0 < c8 < c9 < c10 < 1.0

    # Over probability
    p_over_95 = 1.0 - c9
    assert math.isclose(c9 + p_over_95, 1.0)
    assert 0.40 < p_over_95 < 0.60
