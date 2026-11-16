"""Unit tests for Poisson & Dixon-Coles Corner Pricing Engine."""

from __future__ import annotations

import math

from corner_poisson_engine import (
    estimate_match_corner_lambda,
    poisson_cdf,
    poisson_pmf,
    price_corner_lines,
)


def test_poisson_pmf_and_cdf_basic_properties() -> None:
    lmbda = 10.0
    # Sum of PMFs from 0 to 50 should equal 1.0 (within float precision)
    total_p = sum(poisson_pmf(k, lmbda) for k in range(50))
    assert math.isclose(total_p, 1.0, rel_tol=1e-5)

    # CDF should be strictly monotonic increasing
    cdf_8 = poisson_cdf(8, lmbda)
    cdf_9 = poisson_cdf(9, lmbda)
    cdf_10 = poisson_cdf(10, lmbda)
    assert 0.0 < cdf_8 < cdf_9 < cdf_10 < 1.0


def test_estimate_match_corner_lambda_adjusts_for_tempo_and_dominance() -> None:
    base_lmbda = estimate_match_corner_lambda("brazil_serie_a")
    assert math.isclose(base_lmbda, 10.20, abs_tol=0.01)

    # High over tempo (2.5 Over at 1.40, Under at 2.70)
    high_tempo = estimate_match_corner_lambda(
        "brazil_serie_a",
        odds_ou25=(1.40, 2.70),
    )
    assert high_tempo > base_lmbda

    # Heavy favorite (1.25)
    heavy_fav = estimate_match_corner_lambda(
        "brazil_serie_a",
        odds_1x2=(1.25, 5.0, 9.0),
    )
    assert heavy_fav > base_lmbda


def test_price_corner_lines_detects_edge() -> None:
    lmbda = 10.0
    # For lambda=10.0, P(Corners <= 9) is approx 45.8% (fair under = 2.18, fair over = 1.84)
    # If a soft bookmaker offers 9.5 Over at 2.10, there is positive EV edge
    nesine_corners = {
        "9.5": {"under": 1.70, "over": 2.10},
    }
    res = price_corner_lines(lmbda, nesine_corners)

    assert "9.5" in res["lines"]
    edges = res["edges"]
    assert len(edges) == 2

    over_edge = next(e for e in edges if e["side"] == "ÜST")
    assert over_edge["edge_pct"] > 0
    assert res["best_edge"] == over_edge

