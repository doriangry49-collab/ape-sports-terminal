"""Domain entities and canonical schemas for Sports Intelligence Engine."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    """Validate that datetime has timezone information."""
    if dt is not None:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(f"Datetime '{dt}' must be timezone-aware (tzinfo is required).")
    return dt


class BaseDomainModel(BaseModel):
    """Base domain model enforcing strict validation and frozen immutability where desired."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
    )


class TimeSensitiveRecord(BaseDomainModel):
    """Base schema for time-sensitive records requiring exact temporal lineage."""

    event_time: datetime = Field(
        ...,
        description="Kickoff or scheduled time of the event (timezone-aware).",
    )
    source_time: datetime | None = Field(
        default=None,
        description="Timestamp provided by the upstream data provider if available (timezone-aware).",
    )
    fetched_at: datetime = Field(
        ...,
        description="Timestamp when the payload was downloaded/fetched from the external source (timezone-aware).",
    )
    ingested_at: datetime = Field(
        ...,
        description="Timestamp when the record was processed into the system (timezone-aware).",
    )
    available_at: datetime | None = Field(
        default=None,
        description="Point-in-time when this data became observable for feature generation (timezone-aware).",
    )

    @field_validator(
        "event_time",
        "source_time",
        "fetched_at",
        "ingested_at",
        "available_at",
        mode="after",
    )
    @classmethod
    def check_tz_awareness(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class League(BaseDomainModel):
    """Canonical representation of a sports league or competition."""

    canonical_league_id: str = Field(
        ..., description="Unique canonical league identifier, e.g. 'tr_super_lig'"
    )
    name: str = Field(..., description="Canonical league name, e.g. 'Süper Lig'")
    country: str = Field(default="Turkey", description="Country of the competition")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of league creation in canonical registry.",
    )

    @field_validator("created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class Team(BaseDomainModel):
    """Canonical representation of a team."""

    canonical_team_id: str = Field(
        ..., description="Unique canonical team identifier, e.g. 'galatasaray_sk'"
    )
    canonical_league_id: str = Field(..., description="Canonical ID of the primary league")
    name: str = Field(..., description="Canonical team name")
    short_name: str | None = Field(
        default=None, description="Optional abbreviation or short display name"
    )
    country: str = Field(default="Turkey", description="Country")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of team creation in canonical registry.",
    )

    @field_validator("created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class Player(BaseDomainModel):
    """Canonical representation of a player."""

    canonical_player_id: str = Field(..., description="Unique canonical player identifier")
    canonical_team_id: str | None = Field(
        default=None, description="Current canonical team ID if known"
    )
    name: str = Field(..., description="Canonical player name")
    position: str | None = Field(default=None, description="Primary playing position")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of player creation in canonical registry.",
    )

    @field_validator("created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class Fixture(TimeSensitiveRecord):
    """Canonical representation of a match fixture with point-in-time metadata."""

    canonical_fixture_id: str = Field(..., description="Unique canonical fixture identifier")
    canonical_league_id: str = Field(..., description="Associated canonical league ID")
    season: str = Field(..., description="Season representation, e.g. '2024-2025'")
    round: str | None = Field(default=None, description="Matchday round or phase")
    home_team_id: str = Field(..., description="Canonical home team ID")
    away_team_id: str = Field(..., description="Canonical away team ID")
    status: str = Field(
        default="SCHEDULED",
        description="Current fixture status (e.g. SCHEDULED, IN_PLAY, FINISHED, POSTPONED, CANCELLED)",
    )


class Bookmaker(BaseDomainModel):
    """Bookmaker or odds source provider entity."""

    bookmaker_id: str = Field(
        ..., description="Unique identifier for bookmaker, e.g. 'iddaa', 'pinnacle'"
    )
    name: str = Field(..., description="Display name of the bookmaker")
    is_active: bool = Field(default=True, description="Whether this bookmaker is currently tracked")


class Market(BaseDomainModel):
    """Betting market definition."""

    market_id: str = Field(..., description="Market identifier, e.g. '1x2', 'over_under_2_5'")
    market_type: str = Field(..., description="Market category, e.g. 'MATCH_ODDS', 'TOTAL_GOALS'")
    description: str | None = Field(
        default=None, description="Human-readable description of market rules"
    )


class OddsSnapshot(TimeSensitiveRecord):
    """Time-stamped odds snapshot from a specific bookmaker for a fixture market selection.

    NOTE: As per system constraints, 'is_closing_line' is NOT stored as a primary field.
    Closing line status must be derived dynamically from timestamps and event_time.
    """

    odds_id: str = Field(..., description="Unique snapshot identifier")
    fixture_id: str = Field(..., description="Canonical fixture identifier")
    bookmaker_id: str = Field(..., description="Bookmaker identifier")
    market_type: str = Field(..., description="Market type, e.g. '1X2', 'TOTAL_GOALS_2.5'")
    selection: str = Field(
        ..., description="Selection outcome, e.g. 'HOME', 'DRAW', 'AWAY', 'OVER', 'UNDER'"
    )
    decimal_odds: float = Field(..., gt=1.0, description="Decimal odds value (must be > 1.0)")
    source: str = Field(..., description="Source name where odds were collected")


def is_closing_line(
    odds: OddsSnapshot,
    threshold_seconds: int = 300,
    reference_cutoff: datetime | None = None,
) -> bool:
    """Derive whether an odds snapshot qualifies as a closing line based on timestamps and event_time.

    Rule:
    - An odds quote qualifies as a closing line if its source_time (or fetched_at)
      occurs within `threshold_seconds` (default 5 minutes) prior to kickoff (`event_time`),
      and before or at `event_time`.
    """
    ts = odds.source_time or odds.fetched_at
    event_start = odds.event_time

    if reference_cutoff is not None and ts > reference_cutoff:
        return False

    delta_seconds = (event_start - ts).total_seconds()
    # Snapshots between [0, threshold_seconds] before kickoff are closing lines
    return 0 <= delta_seconds <= threshold_seconds


class MatchResult(TimeSensitiveRecord):
    """Canonical match result with scorelines and finishing status."""

    result_id: str = Field(..., description="Unique result identifier")
    fixture_id: str = Field(..., description="Canonical fixture identifier")
    home_score: int = Field(..., ge=0, description="Full-time goals scored by home team")
    away_score: int = Field(..., ge=0, description="Full-time goals scored by away team")
    halftime_home_score: int | None = Field(
        default=None, ge=0, description="Half-time goals by home team"
    )
    halftime_away_score: int | None = Field(
        default=None, ge=0, description="Half-time goals by away team"
    )
    status: str = Field(default="FINISHED", description="Result status, e.g. FINISHED, ABANDONED")


class ModelPrediction(BaseDomainModel):
    """Immutable model prediction record for pre-match intelligence."""

    prediction_id: str = Field(..., description="Unique prediction identifier")
    fixture_id: str = Field(..., description="Target canonical fixture ID")
    generated_at: datetime = Field(
        ..., description="Timestamp when prediction was calculated (timezone-aware)"
    )
    data_cutoff: datetime = Field(
        ..., description="Strict point-in-time timestamp: no data after this was used"
    )
    model_name: str = Field(..., description="Name of the model generating this prediction")
    model_version: str = Field(..., description="Version of the model artifact or code")
    market_type: str = Field(
        ..., description="Market type evaluated (e.g. '1X2', 'TOTAL_GOALS_2.5')"
    )
    selection: str = Field(..., description="Predicted selection (e.g. 'HOME', 'DRAW', 'AWAY')")
    predicted_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model estimated probability between 0.0 and 1.0",
    )
    fair_odds: float = Field(
        ...,
        gt=0.0,
        description="Calculated fair odds (1.0 / predicted_probability)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional diagnostic metadata or feature importance records",
    )

    @field_validator("generated_at", "data_cutoff", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class SourceMapping(BaseDomainModel):
    """Mapping between external raw provider entity and canonical internal entity."""

    source: str = Field(
        ..., description="Source name (e.g. 'livescore_json', 'propline', 'api_football')"
    )
    source_entity_id: str = Field(..., description="External entity ID in raw source data")
    raw_name: str = Field(..., description="Raw team/player/league string as received from source")
    canonical_id: str = Field(..., description="Resolved internal canonical ID")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Matching confidence score (1.0 for exact, <1.0 for fuzzy)",
    )
    verified: bool = Field(
        default=False,
        description="Whether this mapping has been verified by human/canonical registry.",
    )
    entity_type: str = Field(
        default="team", description="Type of entity: team, league, player, fixture"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when mapping was established",
    )

    @field_validator("created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)
