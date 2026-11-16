"""Unit tests for PlayerProp Pricing Engine (Anytime & First Goalscorer)."""

from __future__ import annotations

import pytest

from sports_engine.models.player_props_engine import PlayerPropsEngine


def test_player_goal_share_fuzzy_lookup():
    """Verify known strikers resolve correct goal shares."""
    engine = PlayerPropsEngine()
    assert engine.get_player_goal_share("Harry Kane") == 0.38
    assert engine.get_player_goal_share("Erling Haaland") == 0.42
    assert engine.get_player_goal_share("Victor Osimhen") == 0.35
    assert engine.get_player_goal_share("Unknown Striker") == 0.22  # default


def test_evaluate_anytime_scorer_value_detection():
    """Verify value is detected when offered odds exceed Poisson fair odds."""
    engine = PlayerPropsEngine()
    # Kane in Bayern (team_mu = 2.50 goals)
    # Kane lambda = 2.50 * 0.38 = 0.95
    # P(Kane >= 1) = 1 - exp(-0.95) = 1 - 0.3867 = 0.6133
    # Fair odds = 1 / 0.6133 = ~1.63
    # If offered 1.95, edge = (0.6133 * 1.95 - 1) = +19.6%
    eval_res = engine.evaluate_anytime_scorer(
        player_name="Harry Kane",
        team_name="Bayern Munich",
        opponent_name="Augsburg",
        team_mu=2.50,
        offered_odds=1.95,
        is_goal_anomaly=False,
    )

    assert eval_res.is_value is True
    assert eval_res.edge_pct > 15.0
    assert eval_res.kelly_stake >= 50.0  # SPEC-0015


def test_evaluate_first_scorer():
    """Verify first goalscorer probability and fair pricing."""
    engine = PlayerPropsEngine()
    eval_res = engine.evaluate_first_scorer(
        player_name="Erling Haaland",
        team_name="Manchester City",
        opponent_name="Everton",
        team_mu=2.40,
        opponent_mu=0.60,
        offered_odds=4.20,
    )

    assert eval_res.prob > 0.20
    assert eval_res.fair_odds < 4.50
    assert eval_res.market == "FIRST_GOALSCORER"
