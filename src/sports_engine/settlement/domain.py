"""TASK-020: Settlement & Performance Domain Models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SettlementStatus(str, Enum):
    """Lifecycle status of an individual prediction outcome."""

    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    PUSH = "PUSH"
    UNSETTLEABLE = "UNSETTLEABLE"
    CANCELLED = "CANCELLED"


class MatchStatus(str, Enum):
    """Status of the match fixture itself."""

    UPCOMING = "UPCOMING"
    FINISHED = "FINISHED"
    LIVE = "LIVE"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class MatchResult:
    """Canonical match score and final outcome."""

    event_id: str
    home_team: str
    away_team: str
    kickoff: str
    home_score: int | None = None
    away_score: int | None = None
    ht_home_score: int | None = None
    ht_away_score: int | None = None
    status: MatchStatus = MatchStatus.UNKNOWN
    result_source: str = "UNKNOWN"
    fetched_at: str = ""

    @property
    def final_score_str(self) -> str | None:
        if self.home_score is not None and self.away_score is not None:
            return f"{self.home_score}-{self.away_score}"
        return None

    @property
    def ht_score_str(self) -> str | None:
        if self.ht_home_score is not None and self.ht_away_score is not None:
            return f"{self.ht_home_score}-{self.ht_away_score}"
        return None


@dataclass
class SettlementRecord:
    """Immutable record representing a settled or pending prediction."""

    settlement_id: str
    event_id: str
    match: str
    competition: str
    kickoff: str
    market: str
    selection: str
    bookmaker: str
    bookmaker_odds: float
    model_probability: float
    model_fair_odds: float
    model_ev_percent: float
    status: SettlementStatus
    final_score: str | None = None
    halftime_score: str | None = None
    stake: float = 1.0
    profit: float = 0.0
    realized_roi_percent: float = 0.0
    result_source: str = "PENDING_KICKOFF"
    settled_at: str = ""
    notes: str | None = None
