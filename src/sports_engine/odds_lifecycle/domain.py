"""TASK-021: Odds Lifecycle and Multi-Snapshot Domain Models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class LifecycleState(str, Enum):
    """Prediction lifecycle transition states."""

    PREDICTED = "PREDICTED"
    SNAPSHOT_TRACKED = "SNAPSHOT_TRACKED"
    LAST_PREMATCH_CAPTURED = "LAST_PREMATCH_CAPTURED"
    KICKOFF_PASSED = "KICKOFF_PASSED"
    SETTLED = "SETTLED"


class KickoffProximity(str, Enum):
    """Proximity to kickoff timestamp."""

    T_PLUS_72H = "T>72h"
    T_72H = "T-72h"
    T_48H = "T-48h"
    T_24H = "T-24h"
    T_12H = "T-12h"
    T_6H = "T-6h"
    T_2H = "T-2h"
    T_1H = "T-1h"
    POST_KICKOFF = "POST_KICKOFF"


class MovementDirection(str, Enum):
    """Direction of bookmaker line movement."""

    SHORTENED = "SHORTENED"          # Odds dropped (probability increased)
    DRIFTED = "DRIFTED"              # Odds increased (probability decreased)
    STABLE = "STABLE"                # Movement < 1%
    SIGNIFICANT_MOVE = "SIGNIFICANT" # Absolute movement >= 5%


def calculate_kickoff_proximity(kickoff_iso: str, ref_time: datetime) -> KickoffProximity:
    """Classify temporal distance to kickoff into standardized bands."""
    try:
        ko_dt = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
        if ko_dt.tzinfo is None:
            ko_dt = ko_dt.replace(tzinfo=UTC)
        diff_hours = (ko_dt - ref_time).total_seconds() / 3600.0

        if diff_hours < 0:
            return KickoffProximity.POST_KICKOFF
        elif diff_hours <= 1.0:
            return KickoffProximity.T_1H
        elif diff_hours <= 2.0:
            return KickoffProximity.T_2H
        elif diff_hours <= 6.0:
            return KickoffProximity.T_6H
        elif diff_hours <= 12.0:
            return KickoffProximity.T_12H
        elif diff_hours <= 24.0:
            return KickoffProximity.T_24H
        elif diff_hours <= 48.0:
            return KickoffProximity.T_48H
        elif diff_hours <= 72.0:
            return KickoffProximity.T_72H
        else:
            return KickoffProximity.T_PLUS_72H
    except Exception:
        return KickoffProximity.T_PLUS_72H


@dataclass
class SnapshotPoint:
    """Single point in time odds snapshot."""

    snapshot_id: str
    timestamp: str
    odds: float
    implied_probability: float
    proximity: KickoffProximity


@dataclass
class OddsMovementSummary:
    """Mathematical movement summary across a time series of snapshots."""

    initial_odds: float
    latest_odds: float
    last_prematch_odds: float
    delta_odds: float
    pct_change: float
    initial_implied_prob: float
    latest_implied_prob: float
    delta_implied_prob: float
    direction: MovementDirection
    is_significant: bool
    snapshots_count: int
    preliminary_clv_ratio: float
    clv_label: str = "PRE_CLOSING_LINE_VALUE"


@dataclass
class SelectionLifecycleRecord:
    """Full lifecycle tracking record for an individual predicted selection."""

    lifecycle_id: str
    event_id: str
    fixture: str
    competition: str
    kickoff: str
    market: str
    selection: str
    bookmaker: str
    model_probability: float
    model_fair_odds: float
    model_ev_percent: float
    lifecycle_state: LifecycleState
    kickoff_proximity: KickoffProximity
    movement: OddsMovementSummary
    snapshots_timeline: list[SnapshotPoint] = field(default_factory=list)
    last_updated: str = ""
