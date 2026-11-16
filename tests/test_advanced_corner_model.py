"""Unit tests for Advanced Negative Binomial & Game-State Corner Pricing Engine."""

import math

from advanced_corner_model import (
    AdvancedCornerEngine,
    neg_binomial_cdf,
    neg_binomial_pmf,
)


def test_neg_binomial_distribution():
    # Test PMF probabilities sum to ~1.0
    mu = 9.5
    kappa = 0.14
    total_p = sum(neg_binomial_pmf(k, mu, kappa) for k in range(35))
    assert math.isclose(total_p, 1.0, rel_tol=1e-2)

    # Test CDF monotonicity
    cdf_8 = neg_binomial_cdf(8, mu, kappa)
    cdf_9 = neg_binomial_cdf(9, mu, kappa)
    cdf_10 = neg_binomial_cdf(10, mu, kappa)
    assert 0.0 < cdf_8 < cdf_9 < cdf_10 < 1.0


def test_gamestate_blowout_discount():
    engine = AdvancedCornerEngine()

    # Heavy favorite (1.20 odds) should trigger blowout decay
    mu_blowout, diag_blowout = engine.estimate_corner_mu(
        home_team="Heavy Fav FC",
        away_team="Underdog FC",
        league_key="japan_j1",
        odds_1x2=(1.20, 6.00, 11.00),
    )
    assert diag_blowout["blowout_risk"] > 0.0
    assert diag_blowout["gamestate_adj"] < 1.0

    # Balanced match (2.30 vs 2.40 odds) should have no blowout decay
    mu_balanced, diag_balanced = engine.estimate_corner_mu(
        home_team="Team A",
        away_team="Team B",
        league_key="japan_j1",
        odds_1x2=(2.30, 3.10, 2.40),
    )
    assert diag_balanced["blowout_risk"] == 0.0
    assert diag_balanced["gamestate_adj"] == 1.0
    # Blowout match expected corners must be lower than balanced match
    assert mu_blowout < mu_balanced


def test_price_lines_output():
    engine = AdvancedCornerEngine()
    lines_res = engine.price_lines(
        mu=9.5,
        nesine_corners={"9.5": {"under": 1.90, "over": 1.65}},
    )
    assert "9.5" in lines_res["lines"]
    assert len(lines_res["edges"]) == 2
    assert lines_res["distribution"] == "NegativeBinomial"
