"""Unit and Integration Tests for Goal Timing & In-Play Interval Hazard Engine."""

from __future__ import annotations

import pytest

from sports_engine.models.goal_timing_engine import (
    GoalTimingEngine,
    PlayerGoalEvent,
    TeamTimingProfile,
    get_minute_interval,
    get_remaining_intervals,
)
from sports_engine.models.goal_anomaly_engine import (
    AnomalySignalTier,
    GoalAnomalyEngine,
    format_in_play_goal_anomaly_alert,
)


def test_minute_interval_mapping():
    """Verify correct 15-minute interval bucketing."""
    assert get_minute_interval(5) == "0-15"
    assert get_minute_interval(15) == "0-15"
    assert get_minute_interval(16) == "16-30"
    assert get_minute_interval(45) == "31-45"
    assert get_minute_interval(46) == "46-60"
    assert get_minute_interval(75) == "61-75"
    assert get_minute_interval(76) == "76-90+"
    assert get_minute_interval(93) == "76-90+"


def test_remaining_intervals():
    """Verify remaining interval sequences from given minutes."""
    assert get_remaining_intervals(10) == ["0-15", "16-30", "31-45", "46-60", "61-75", "76-90+"]
    assert get_remaining_intervals(50) == ["46-60", "61-75", "76-90+"]
    assert get_remaining_intervals(82) == ["76-90+"]


def test_team_timing_profile_normalization():
    """Verify custom team profile creates normalized distributions and second-half ratio."""
    engine = GoalTimingEngine()
    scored_raw = {"0-15": 10, "16-30": 10, "31-45": 10, "46-60": 20, "61-75": 20, "76-90+": 30}
    conceded_raw = {"0-15": 10, "16-30": 10, "31-45": 10, "46-60": 10, "61-75": 10, "76-90+": 10}

    prof = engine.create_team_profile("TestFC", scored_raw, conceded_raw)

    assert pytest.approx(sum(prof.scored_distribution.values()), rel=1e-2) == 1.0
    assert pytest.approx(sum(prof.conceded_distribution.values()), rel=1e-2) == 1.0
    assert prof.second_half_scored_ratio == 0.70  # (20 + 20 + 30) / 100
    assert prof.peak_scoring_interval == "76-90+"
    assert prof.clutch_index > 1.5  # 30% vs 16.67% uniform baseline


def test_evaluate_live_timing_hazard_crunch_time():
    """Verify crunch time (76-90+) urgency raises joint hazard index."""
    engine = GoalTimingEngine()
    # 82nd minute, 2-1 scoreline (tight 1-goal margin)
    eval_res = engine.evaluate_live_timing_hazard(
        home_team="Bayern Munich",
        away_team="Borussia Dortmund",
        elapsed_min=82,
        score_home=2,
        score_away=1,
        total_shots_rate=0.40,
    )

    assert eval_res.current_interval == "76-90+"
    assert eval_res.is_crunch_time_active is True
    assert eval_res.joint_hazard_index >= 65.0
    assert eval_res.is_high_pressure_window is True
    assert any("Tight 1-goal margin" in r for r in eval_res.timing_reasons)


def test_parse_espn_player_events_braces_and_burst():
    """Verify player event parser extracts scorer, brace detection, and rapid bursts."""
    engine = GoalTimingEngine()
    key_events = [
        {
            "type": {"text": "Goal"},
            "clock": {"displayValue": "22'"},
            "text": "Goal! Harry Kane (Bayern Munich) right footed shot from center of box to bottom right corner.",
        },
        {
            "type": {"text": "Goal"},
            "clock": {"displayValue": "27'"},  # 5 minute gap: Rapid burst!
            "text": "Goal! Harry Kane (Bayern Munich) header from six yard box to top right corner.",
        },
        {
            "type": {"text": "Goal"},
            "clock": {"displayValue": "68'"},
            "text": "Goal! Serhou Guirassy (Borussia Dortmund) right footed shot.",
        },
    ]

    ctx = engine.parse_espn_player_events(key_events, "Bayern Munich", "Borussia Dortmund")

    assert ctx.total_goals == 3
    assert "Harry Kane" in ctx.brace_scorers
    assert ctx.has_rapid_burst is True
    assert ctx.burst_window_minutes == 5
    assert "Brace Scorer: Harry Kane" in ctx.momentum_summary
    assert "Rapid Goal Burst: 2 goals in 5 mins" in ctx.momentum_summary


def test_goal_anomaly_engine_live_integration_with_timing_and_players():
    """Verify GoalAnomalyEngine integrates timing profile and player events in live match."""
    anomaly_engine = GoalAnomalyEngine()

    fixture = {
        "event_id": "test_ger_live_99",
        "home_team": "Bayern Munich",
        "away_team": "Borussia Dortmund",
        "league": "D1",
        "fav_odd": 1.75,
        "dog_odd": 3.80,
        "draw_odd": 3.90,
        "open_o25": 1.40,
        "close_o25": 1.35,
    }

    key_events = [
        {"type": {"text": "Goal"}, "clock": {"displayValue": "14'"}, "text": "Goal! Harry Kane (Bayern) right footed shot."},
        {"type": {"text": "Goal"}, "clock": {"displayValue": "38'"}, "text": "Goal! Leroy Sane (Bayern) left footed shot."},
    ]

    # Evaluate at HT (48' elapsed, 2 HT goals)
    live_res = anomaly_engine.evaluate_live_fixture(
        fixture=fixture,
        minute=48,
        ht_goals=2,
        score_home=2,
        score_away=0,
        total_shots_rate=0.38,
        key_events=key_events,
    )

    assert live_res.is_live_qualified is True
    assert live_res.tier == AnomalySignalTier.GOLD_TIER
    assert live_res.timing_evaluation is not None
    assert live_res.player_context is not None
    assert live_res.player_context.total_goals == 2

    # Verify Telegram message formatter
    tg_msg = format_in_play_goal_anomaly_alert(
        result=live_res,
        minute=48,
        current_score="2-0",
        ht_score="2-0",
        recommended_line="4.5 ÜST",
        market_odds=1.85,
    )

    assert "APE CANLI GOL ANOMALİSİ" in tg_msg
    assert "Bayern Munich vs Borussia Dortmund" in tg_msg
    assert "Zamanlama Dilimi" in tg_msg
    assert "SPEC-0015" in tg_msg
