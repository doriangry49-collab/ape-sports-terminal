"""Root re-export for GoalAnomalyEngine."""
from sports_engine.models.goal_anomaly_engine import (
    AnomalyArchetype,
    AnomalySignalTier,
    GoalAnomalyEngine,
    GoalAnomalyResult,
    HIGH_OCTANE_TEAMS,
    HIGH_TEMPO_LEAGUES,
    LOW_TEMPO_VETO_LEAGUES,
    format_anomaly_telegram_alert,
    format_in_play_goal_anomaly_alert,
)

__all__ = [
    "AnomalyArchetype",
    "AnomalySignalTier",
    "GoalAnomalyEngine",
    "GoalAnomalyResult",
    "HIGH_OCTANE_TEAMS",
    "HIGH_TEMPO_LEAGUES",
    "LOW_TEMPO_VETO_LEAGUES",
    "format_anomaly_telegram_alert",
    "format_in_play_goal_anomaly_alert",
]
