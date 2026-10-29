"""Domain schemas for Betting Universe and Active Fixture Market Coverage."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    """Validate that datetime has timezone information."""
    if dt is not None:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(f"Datetime '{dt}' must be timezone-aware.")
    return dt


class MarketStatus(str, Enum):
    """Taxonomy of market offering vs model coverage."""

    MODEL_ONLY = "MODEL_ONLY"
    OFFERED = "OFFERED"
    OFFERED_AND_MODELLED = "OFFERED_AND_MODELLED"
    OFFERED_BUT_UNMODELLED = "OFFERED_BUT_UNMODELLED"
    UNKNOWN = "UNKNOWN"


from sports_engine.domain.odds_contract import TimestampLayers


class MarketEvidence(BaseModel):
    """Granular evidence for a single market in an active fixture."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    market_name: str = Field(..., description="Canonical market identifier, e.g. '1X2', 'BTTS'")
    market_exists: bool = Field(default=False, description="Market is offered by bookmakers for this fixture")
    odds_exists: bool = Field(default=False, description="Numeric odds are actively published for this market")
    model_exists: bool = Field(default=False, description="Our model derives probabilities for this market")
    legal_evidence_exists: bool = Field(
        default=False, description="Observed in official Turkish legal betting bülteni"
    )
    status: MarketStatus = Field(default=MarketStatus.UNKNOWN)
    source: str = Field(default="UNKNOWN", description="'PROP_LINE', 'XIDDAA', 'API_FOOTBALL', 'BZZOIRO', 'MODEL', 'UNKNOWN'")
    classification: str = Field(default="UNKNOWN", description="'BOOKMAKER_OFFERED', 'MODEL_DERIVED', 'BOTH'")
    odds_timestamp: str = Field(default="UNKNOWN", description="Timestamp of odds quote or 'UNKNOWN'")
    timestamps: TimestampLayers = Field(default_factory=TimestampLayers, description="4 distinct timestamp layers")
    bookmaker_count: int = Field(default=0, description="Count of bookmakers quoting this market")
    sample_best_odds: float | None = Field(default=None)


class ActiveFixtureRegistryEntry(BaseModel):
    """Canonical active fixture with fixture-level betting and market presence evidence."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    fixture_id: str = Field(..., description="Canonical fixture identifier")
    canonical_competition_id: str = Field(..., description="Canonical competition identifier")
    competition_name: str = Field(..., description="Human readable competition name")
    canonical_home_team: str = Field(..., description="Canonical home team name")
    canonical_away_team: str = Field(..., description="Canonical away team name")
    kickoff: datetime = Field(..., description="Scheduled kickoff timestamp (timezone-aware)")
    country: str = Field(..., description="Country of competition")
    competition_type: str = Field(default="League", description="'League', 'Cup', 'Youth', etc.")
    stage: str | None = Field(default=None, description="Stage or round name")
    match_phase: str = Field(default="PREMATCH", description="'PREMATCH', 'LIVE', 'UNKNOWN'")
    provider_presence: list[str] = Field(default_factory=list)
    betting_presence: dict[str, Any] = Field(
        default_factory=dict, description="Summary of betting availability for this fixture"
    )
    market_presence: dict[str, MarketEvidence] = Field(
        default_factory=dict, description="18 standard markets with exact status"
    )
    turkey_legal_status: str = Field(
        default="UNKNOWN",
        description="'VERIFIED' only if fixture-level evidence exists in xiddaa; otherwise 'UNKNOWN'",
    )
    competition_catalog_present: bool = Field(
        default=True, description="Competition exists in xiddaa catalog"
    )
    fixture_evidence_present: bool = Field(
        default=False, description="Concrete fixture record exists in xiddaa event feed"
    )
    model_coverage: float = Field(
        default=0.0, description="modelled_offered_markets / offered_markets"
    )
    market_availability: float = Field(
        default=0.0, description="offered_markets / 18_standard_markets"
    )
    market_coverage_score: float = Field(
        default=0.0, description="Legacy alias for model_coverage"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("kickoff", "created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)
