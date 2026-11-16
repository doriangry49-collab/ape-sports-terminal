"""
Unit tests for sports_engine.src.advanced_devig.
Verifies mathematical invariants, error handling, and Shin/Dixon-Coles algorithms.
"""

import os
import sys

import numpy as np
import pytest

# Ensure src directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from advanced_devig import DevigError, devig_odds_multi, devig_odds_shin, fit_dixon_coles_model


def test_devig_odds_shin_standard_1x2():
    odds = [2.10, 3.40, 3.80]
    res = devig_odds_shin(odds)

    assert res["method"] == "shin"
    assert "probabilities" in res
    probs = res["probabilities"]
    assert len(probs) == 3

    # Invariant 1: Sum strictly equals 1.0
    assert np.isclose(sum(probs), 1.0, atol=1e-5)

    # Invariant 2: Positive probabilities strictly in (0, 1)
    assert all(0.0 < p < 1.0 for p in probs)

    # Invariant 3: Monotonicity (2.10 < 3.40 < 3.80 => P(home) > P(draw) > P(away))
    assert probs[0] > probs[1] > probs[2]

    # Margin and z parameter
    assert res["margin"] > 0.0
    assert res["z"] >= 0.0


def test_devig_odds_multi_methods():
    odds = [1.90, 3.60, 4.20]
    for method in ["shin", "power", "multiplicative", "additive", "logarithmic"]:
        res = devig_odds_multi(odds, method=method)
        assert res["method"] == method
        probs = res["probabilities"]
        assert np.isclose(sum(probs), 1.0, atol=1e-4)
        assert len(probs) == 3
        assert probs[0] > probs[1] > probs[2]


def test_devig_odds_fail_closed_invalid_odds():
    # Odd <= 1.0 must fail
    with pytest.raises(DevigError, match="All odds must be strictly > 1.0"):
        devig_odds_shin([1.0, 3.5, 4.0])

    with pytest.raises(DevigError, match="All odds must be strictly > 1.0"):
        devig_odds_shin([0.9, 3.5, 4.0])

    with pytest.raises(DevigError, match="At least 2 odds required"):
        devig_odds_shin([2.1])


def test_devig_odds_fail_closed_underround():
    # Sum of 1/odds <= 1.0 (arbitrage market without overround)
    with pytest.raises(DevigError, match="Market has no overround"):
        devig_odds_shin([3.0, 3.5, 4.0])  # 1/3 + 1/3.5 + 1/4 = 0.333 + 0.286 + 0.25 = 0.869 < 1.0


def test_fit_dixon_coles_model():
    # 20 balanced sample matches between 4 teams
    home_teams = ["Galatasaray", "Fenerbahce", "Besiktas", "Trabzonspor"] * 5
    away_teams = ["Fenerbahce", "Besiktas", "Trabzonspor", "Galatasaray"] * 5
    goals_h = [1, 2, 0, 1, 2, 0, 3, 1, 1, 2, 0, 1, 2, 1, 0, 3, 1, 2, 0, 1]
    goals_a = [1, 0, 2, 1, 0, 1, 0, 2, 1, 1, 2, 0, 1, 0, 1, 1, 0, 1, 2, 0]

    res = fit_dixon_coles_model(
        goals_home=goals_h,
        goals_away=goals_a,
        teams_home=home_teams,
        teams_away=away_teams,
        target_home="Galatasaray",
        target_away="Fenerbahce",
    )

    assert res["model"] == "dixon_coles"
    assert "home_win" in res
    assert "draw" in res
    assert "away_win" in res

    total = res["home_win"] + res["draw"] + res["away_win"]
    assert np.isclose(total, 1.0, atol=1e-4)
    assert res["home_exp_goals"] > 0
    assert res["away_exp_goals"] > 0


def test_fit_dixon_coles_insufficient_data():
    with pytest.raises(DevigError, match="Insufficient match history"):
        fit_dixon_coles_model(
            goals_home=[1, 2],
            goals_away=[0, 1],
            teams_home=["A", "B"],
            teams_away=["B", "A"],
            target_home="A",
            target_away="B",
        )
