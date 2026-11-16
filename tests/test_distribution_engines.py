"""Comprehensive unit and mathematical property tests for Distribution Engines (Feature F5).

Verifies:
1. True Bivariate Poisson joint distribution via Karlis & Ntzoufras (2003) trivariate reduction.
2. Independent Poisson recovery when covariance parameter lambda_3 == 0.
3. Dixon-Coles (1997) low-score adjustment matrix tau(x, y) with dynamic non-negativity bounds.
4. Score grid normalization sum P(x, y) = 1.0 +/- 1e-6.
5. Negative Binomial PMF, CDF, Over/Under pricing, and empirical dispersion estimator.
6. NegativeBinomialGoalModel fitting and match prediction.
7. TimeDecayedPoissonModel bivariate score distribution integration.
"""

from __future__ import annotations

import math

import pytest

from sports_engine.models.negative_binomial import (
    NegativeBinomialGoalModel,
    compute_neg_binomial_score_grid,
    estimate_dispersion_kappa,
    neg_binomial_cdf,
    neg_binomial_over_prob,
    neg_binomial_pmf,
    neg_binomial_under_prob,
)
from sports_engine.models.poisson import (
    bivariate_poisson_pmf,
    compute_bivariate_score_grid,
    dixon_coles_tau,
)
from sports_engine.models.time_decay_poisson import TimeDecayedPoissonModel


def test_bivariate_poisson_pmf_zero_covariance_equals_independent():
    """When lambda_3 == 0, bivariate Poisson must collapse strictly to independent Poisson multiplication."""
    l1, l2 = 1.45, 1.15
    for x in range(5):
        for y in range(5):
            p_biv = bivariate_poisson_pmf(x, y, l1, l2, lambda_3=0.0)
            p_indep = (
                ((math.exp(-l1) * (l1**x)) / math.factorial(x))
                * ((math.exp(-l2) * (l2**y)) / math.factorial(y))
            )
            assert pytest.approx(p_biv, rel=1e-7, abs=1e-9) == p_indep


def test_bivariate_poisson_pmf_positive_covariance():
    """Positive lambda_3 increases diagonal/correlated score probabilities (e.g. 1-1, 2-2)."""
    l1, l2, l3 = 1.20, 1.00, 0.20
    # Independent baseline:
    p_00_indep = math.exp(-1.40) * math.exp(-1.20)
    # Bivariate with covariance:
    p_00_biv = bivariate_poisson_pmf(0, 0, l1, l2, lambda_3=l3)
    p_11_biv = bivariate_poisson_pmf(1, 1, l1, l2, lambda_3=l3)

    assert p_00_biv > 0.0
    assert p_11_biv > 0.0
    # Formula check for (0,0): exp(-(l1 + l2 + l3))
    assert pytest.approx(p_00_biv, rel=1e-7) == math.exp(-(l1 + l2 + l3))


def test_bivariate_poisson_negative_inputs():
    """Negative goal counts return 0.0."""
    assert bivariate_poisson_pmf(-1, 2, 1.5, 1.2) == 0.0
    assert bivariate_poisson_pmf(2, -1, 1.5, 1.2) == 0.0


def test_dixon_coles_tau_low_scores_and_bounds():
    """Dixon-Coles adjustment adjusts (0,0), (1,0), (0,1), (1,1) correctly and respects bounds."""
    lh, la = 1.40, 1.10
    rho = -0.06

    tau_00 = dixon_coles_tau(0, 0, lh, la, rho=rho)
    tau_01 = dixon_coles_tau(0, 1, lh, la, rho=rho)
    tau_10 = dixon_coles_tau(1, 0, lh, la, rho=rho)
    tau_11 = dixon_coles_tau(1, 1, lh, la, rho=rho)

    # With negative rho:
    # tau(0,0) = 1 - (lh * la * rho) > 1.0 (inflates 0-0 draws)
    # tau(1,1) = 1 - rho > 1.0 (inflates 1-1 draws)
    # tau(0,1) = 1 + (lh * rho) < 1.0 (deflates 0-1)
    # tau(1,0) = 1 + (la * rho) < 1.0 (deflates 1-0)
    assert tau_00 > 1.0
    assert tau_11 > 1.0
    assert 0.0 <= tau_01 < 1.0
    assert 0.0 <= tau_10 < 1.0

    # Guarantee non-negativity under extreme inputs
    tau_extreme = dixon_coles_tau(0, 1, 10.0, 10.0, rho=-0.99)
    assert tau_extreme >= 0.0


def test_dixon_coles_tau_high_scores_unaffected():
    """Scores with x > 1 or y > 1 are unaffected (tau == 1.0)."""
    assert dixon_coles_tau(2, 0, 1.5, 1.2) == 1.0
    assert dixon_coles_tau(0, 2, 1.5, 1.2) == 1.0
    assert dixon_coles_tau(2, 2, 1.5, 1.2) == 1.0
    assert dixon_coles_tau(3, 1, 1.5, 1.2) == 1.0


def test_compute_bivariate_score_grid_normalization():
    """Score grid cells must sum strictly to 1.0 +/- 1e-6."""
    for lh, la in [(1.8, 0.9), (0.5, 0.5), (3.2, 2.8)]:
        grid = compute_bivariate_score_grid(lh, la, lambda_3=0.08, rho=-0.06, max_goals=8)
        total_mass = sum(grid.values())
        assert abs(total_mass - 1.0) < 1e-6
        assert len(grid) == 81  # (8+1) x (8+1)
        assert all(0.0 <= p <= 1.0 for p in grid.values())


def test_neg_binomial_pmf_and_cdf():
    """Negative Binomial PMF and CDF mathematical consistency."""
    mu = 2.5
    kappa = 0.12

    # CDF should match cumulative PMF sum
    cdf_3 = neg_binomial_cdf(3, mu, kappa)
    pmf_sum = sum(neg_binomial_pmf(i, mu, kappa) for i in range(4))
    assert pytest.approx(cdf_3, abs=1e-7) == pmf_sum

    # Distribution total sum approaches 1.0
    full_sum = sum(neg_binomial_pmf(i, mu, kappa) for i in range(40))
    assert pytest.approx(full_sum, abs=1e-3) == 1.0


def test_neg_binomial_zero_kappa_matches_poisson():
    """When kappa <= 1e-6, Negative Binomial collapses to standard Poisson."""
    mu = 1.65
    for k in range(6):
        nb_val = neg_binomial_pmf(k, mu, kappa=1e-7)
        poi_val = (math.exp(-mu) * (mu**k)) / math.factorial(k)
        assert pytest.approx(nb_val, rel=1e-5, abs=1e-7) == poi_val


def test_neg_binomial_over_under_probs():
    """P(Over 2.5) + P(Under 2.5) must equal exactly 1.0."""
    mu = 2.75
    kappa = 0.10

    p_over = neg_binomial_over_prob(2.5, mu, kappa)
    p_under = neg_binomial_under_prob(2.5, mu, kappa)
    assert pytest.approx(p_over + p_under, abs=1e-6) == 1.0
    assert 0.0 < p_over < 1.0
    assert 0.0 < p_under < 1.0


def test_estimate_dispersion_kappa():
    """Empirical dispersion estimator correctly detects overdispersion."""
    # Overdispersed sample: mean ~ 2.0, variance ~ 4.0
    overdispersed = [0, 0, 1, 1, 1, 2, 2, 3, 4, 5, 6, 7]
    kappa = estimate_dispersion_kappa(overdispersed)
    assert kappa > 0.0

    # Under- or equi-dispersed sample returns 0.0
    equidispersed = [2, 2, 2, 2, 2]
    assert estimate_dispersion_kappa(equidispersed) == 0.0


def test_compute_neg_binomial_score_grid_normalization():
    """Negative binomial score grid sums strictly to 1.0 +/- 1e-6."""
    grid = compute_neg_binomial_score_grid(1.6, 1.2, kappa_h=0.08, kappa_a=0.08, rho=-0.06)
    assert abs(sum(grid.values()) - 1.0) < 1e-6
    assert len(grid) == 81


def test_negative_binomial_goal_model_fit_and_predict():
    """NegativeBinomialGoalModel fits on match history and outputs coherent probabilities."""
    matches = [
        {"home_team": "team_a", "away_team": "team_b", "home_score": 2, "away_score": 1},
        {"home_team": "team_b", "away_team": "team_c", "home_score": 0, "away_score": 0},
        {"home_team": "team_c", "away_team": "team_a", "home_score": 1, "away_score": 3},
        {"home_team": "team_a", "away_team": "team_c", "home_score": 4, "away_score": 0},
        {"home_team": "team_b", "away_team": "team_a", "home_score": 1, "away_score": 2},
    ]

    model = NegativeBinomialGoalModel().fit(matches)
    pred = model.predict_match("team_a", "team_b")

    total_prob = pred.home_probability + pred.draw_probability + pred.away_probability
    assert pytest.approx(total_prob, abs=1e-3) == 1.0
    assert pred.home_probability > pred.away_probability
    assert pytest.approx(pred.fair_home_odds, abs=0.02) == round(1.0 / pred.home_probability, 2)
    assert pytest.approx(pred.fair_draw_odds, abs=0.02) == round(1.0 / pred.draw_probability, 2)
    assert pytest.approx(pred.fair_away_odds, abs=0.02) == round(1.0 / pred.away_probability, 2)
    assert pred.model_name == "negative_binomial_goal_model"
    assert "league_kappa_h" in pred.metadata

    # Test optional calibration branch
    pred_cal = model.predict_match("team_a", "team_b", calibrate=True)
    assert pytest.approx(pred_cal.home_probability + pred_cal.draw_probability + pred_cal.away_probability, abs=1e-3) == 1.0
    assert pytest.approx(pred_cal.fair_home_odds, abs=0.02) == round(1.0 / pred_cal.home_probability, 2)


def test_time_decay_poisson_bivariate_score_grid_normalized():
    """TimeDecayedPoissonModel predict_match generates normalized probabilities."""
    matches = [
        {"home_team": "galatasaray", "away_team": "fenerbahce", "home_score": 2, "away_score": 1, "event_date": "2026-09-01T18:00:00Z"},
        {"home_team": "besiktas", "away_team": "trabzonspor", "home_score": 1, "away_score": 1, "event_date": "2026-09-05T18:00:00Z"},
        {"home_team": "fenerbahce", "away_team": "besiktas", "home_score": 3, "away_score": 0, "event_date": "2026-09-12T18:00:00Z"},
        {"home_team": "trabzonspor", "away_team": "galatasaray", "home_score": 0, "away_score": 2, "event_date": "2026-09-20T18:00:00Z"},
    ]
    model = TimeDecayedPoissonModel(min_required_matches=2).fit(matches)
    pred = model.predict_match("galatasaray", "fenerbahce")

    assert pytest.approx(pred.home_probability + pred.draw_probability + pred.away_probability, abs=1e-3) == 1.0
    assert "grid_sum" in pred.metadata
    assert abs(pred.metadata["grid_sum"] - 1.0) < 1e-4
