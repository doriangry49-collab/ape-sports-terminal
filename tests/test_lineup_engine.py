"""Unit tests for LineupEngine (v1.0)."""

import pytest
from sports_engine.models.lineup_engine import (
    LineupEngine,
    LineupEvaluation,
    LineupStatus,
    MatchLineupImpact,
    PlayerProfile,
    TacticalStance,
    TeamLineup,
)


@pytest.fixture
def arsenal_squad() -> list[PlayerProfile]:
    return [
        PlayerProfile("Raya", "GK", is_regular_starter=True, season_goals=0, season_minutes=2500, rating=7.8),
        PlayerProfile("Neto", "GK", is_regular_starter=False, season_goals=0, season_minutes=180, rating=6.2),
        PlayerProfile("Saliba", "DEF", is_regular_starter=True, season_goals=2, season_minutes=2400, rating=8.0),
        PlayerProfile("Gabriel", "DEF", is_regular_starter=True, season_goals=4, season_minutes=2300, rating=8.0),
        PlayerProfile("White", "DEF", is_regular_starter=True, season_goals=1, season_minutes=2100, rating=7.4),
        PlayerProfile("Timber", "DEF", is_regular_starter=True, season_goals=0, season_minutes=1800, rating=7.3),
        PlayerProfile("Rice", "MID", is_regular_starter=True, season_goals=5, season_minutes=2500, rating=8.2),
        PlayerProfile("Odegaard", "MID", is_regular_starter=True, season_goals=10, season_minutes=2400, rating=8.5),
        PlayerProfile("Partey", "MID", is_regular_starter=True, season_goals=2, season_minutes=1900, rating=7.2),
        PlayerProfile("Saka", "FWD", is_regular_starter=True, season_goals=16, season_minutes=2400, rating=8.6),
        PlayerProfile("Havertz", "FWD", is_regular_starter=True, season_goals=14, season_minutes=2200, rating=7.9),
        PlayerProfile("Martinelli", "FWD", is_regular_starter=True, season_goals=8, season_minutes=1800, rating=7.5),
        # Reserves
        PlayerProfile("Trossard", "FWD", is_regular_starter=False, season_goals=6, season_minutes=1100, rating=7.4),
        PlayerProfile("Jesus", "FWD", is_regular_starter=False, season_goals=3, season_minutes=700, rating=7.0),
        PlayerProfile("Jorginho", "MID", is_regular_starter=False, season_goals=1, season_minutes=600, rating=6.8),
    ]


def test_full_strength_lineup(arsenal_squad: list[PlayerProfile]):
    lineup = TeamLineup(
        team_name="Arsenal",
        formation="4-3-3",
        starters=["Raya", "Saliba", "Gabriel", "White", "Timber", "Rice", "Odegaard", "Partey", "Saka", "Havertz", "Martinelli"],
        bench=["Neto", "Trossard", "Jesus", "Jorginho"],
        starting_gk="Raya",
    )
    eval_res = LineupEngine.evaluate_team_lineup(lineup, arsenal_squad)

    assert eval_res.status == LineupStatus.FULL_STRENGTH
    assert eval_res.squad_strength_retention == 1.0
    assert eval_res.is_backup_gk is False
    assert eval_res.missing_goal_share < 0.15
    assert eval_res.tactical_stance == TacticalStance.ATTACKING
    assert eval_res.scoring_lambda_mult >= 1.0


def test_missing_key_strikers_under_tilt(arsenal_squad: list[PlayerProfile]):
    # Saka (16 goals) and Havertz (14 goals) absent -> 30 goals out of ~62 goals missing (almost 50%)
    lineup = TeamLineup(
        team_name="Arsenal",
        formation="4-3-3",
        starters=["Raya", "Saliba", "Gabriel", "White", "Timber", "Rice", "Odegaard", "Partey", "Trossard", "Jesus", "Martinelli"],
        bench=["Neto", "Jorginho"],
        starting_gk="Raya",
    )
    eval_res = LineupEngine.evaluate_team_lineup(lineup, arsenal_squad)

    assert eval_res.missing_goal_share > 0.40
    assert eval_res.scoring_lambda_mult <= 0.85
    assert eval_res.status == LineupStatus.KEY_STRIKER_ABSENT


def test_backup_goalkeeper_penalty(arsenal_squad: list[PlayerProfile]):
    lineup = TeamLineup(
        team_name="Arsenal",
        formation="4-3-3",
        starters=["Neto", "Saliba", "Gabriel", "White", "Timber", "Rice", "Odegaard", "Partey", "Saka", "Havertz", "Martinelli"],
        bench=["Trossard", "Jesus"],
        starting_gk="Neto",
    )
    eval_res = LineupEngine.evaluate_team_lineup(lineup, arsenal_squad)

    assert eval_res.is_backup_gk is True
    assert eval_res.conceding_lambda_mult >= 1.15
    assert eval_res.status == LineupStatus.BACKUP_GOALKEEPER


def test_ultra_defensive_formation_suppression(arsenal_squad: list[PlayerProfile]):
    lineup = TeamLineup(
        team_name="Arsenal",
        formation="5-4-1",
        starters=["Raya", "Saliba", "Gabriel", "White", "Timber", "Rice", "Odegaard", "Partey", "Jorginho", "Havertz", "Martinelli"],
        starting_gk="Raya",
    )
    eval_res = LineupEngine.evaluate_team_lineup(lineup, arsenal_squad)

    assert eval_res.tactical_stance == TacticalStance.ULTRA_DEFENSIVE
    assert eval_res.scoring_lambda_mult < 1.0


def test_match_impact_and_veto_rule(arsenal_squad: list[PlayerProfile]):
    # Heavy rotation home team
    home_lineup = TeamLineup(
        team_name="Arsenal",
        formation="4-3-3",
        starters=["Neto", "Jorginho", "Jesus", "Trossard", "Reserve1", "Reserve2", "Reserve3", "Reserve4", "Reserve5", "Reserve6", "Reserve7"],
        starting_gk="Neto",
    )
    home_eval = LineupEngine.evaluate_team_lineup(home_lineup, arsenal_squad)
    assert home_eval.status == LineupStatus.HEAVY_ROTATION
    assert home_eval.squad_strength_retention < 0.50

    away_eval = LineupEvaluation(
        team_name="Chelsea",
        formation="4-2-3-1",
        tactical_stance=TacticalStance.BALANCED,
        squad_strength_retention=1.0,
        missing_goal_share=0.0,
        is_backup_gk=False,
        status=LineupStatus.FULL_STRENGTH,
        scoring_lambda_mult=1.0,
        conceding_lambda_mult=1.0,
    )

    impact = LineupEngine.evaluate_match_impact(home_eval, away_eval, base_home_lambda=1.8, base_away_lambda=1.2)

    # Should trigger veto because home squad strength retention < 0.50
    assert impact.is_veto_recommended is True
    assert "Extreme squad dilution" in impact.veto_reason
