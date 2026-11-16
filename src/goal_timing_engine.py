"""Root re-export for GoalTimingEngine and timing dataclasses."""

from sports_engine.models.goal_timing_engine import (
    DEFAULT_CONCEDING_BASELINE,
    DEFAULT_SCORING_BASELINE,
    MATCH_INTERVALS,
    GoalTimingEngine,
    LivePlayerThreatContext,
    LiveTimingEvaluation,
    PlayerGoalEvent,
    TeamTimingProfile,
    get_minute_interval,
    get_remaining_intervals,
)

__all__ = [
    "DEFAULT_CONCEDING_BASELINE",
    "DEFAULT_SCORING_BASELINE",
    "MATCH_INTERVALS",
    "GoalTimingEngine",
    "LivePlayerThreatContext",
    "LiveTimingEvaluation",
    "PlayerGoalEvent",
    "TeamTimingProfile",
    "get_minute_interval",
    "get_remaining_intervals",
]

