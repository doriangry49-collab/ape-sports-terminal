"""Domain schemas for Global Competition and Fixture Registries."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    """Validate that datetime has timezone information."""
    if dt is not None:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(f"Datetime '{dt}' must be timezone-aware.")
    return dt


class BaseRegistryModel(BaseModel):
    """Base model for registry entities."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
    )


class ProviderPresence(BaseRegistryModel):
    """Flags indicating presence in distinct data providers."""

    api_football: bool = Field(default=False, description="Available in API-Football")
    bzzoiro: bool = Field(default=False, description="Available in Bzzoiro")
    prop_line: bool = Field(default=False, description="Available in PropLine")
    xiddaa: bool = Field(default=False, description="Available in xiddaa (İddaa)")
    provider_keys: dict[str, Any] = Field(
        default_factory=dict, description="Raw provider IDs or keys"
    )


class BettingUniverseMetadata(BaseRegistryModel):
    """Betting market availability and Turkish legal market verification."""

    active_odds_available: bool = Field(
        default=False, description="Active odds/lines are offered by bookmakers"
    )
    bookmaker_count: int = Field(default=0, description="Number of bookmakers offering odds")
    market_count: int = Field(default=0, description="Number of unique markets offered")
    turkey_legal_status: str = Field(
        default="UNKNOWN",
        description="Verification in official Turkish legal betting: 'VERIFIED', 'UNKNOWN', 'NOT_OFFERED'",
    )
    last_scanned_at: datetime | None = Field(default=None)

    @field_validator("last_scanned_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class MarketCoverageMetadata(BaseRegistryModel):
    """Taxonomy and coverage metrics for competition markets."""

    offered_markets: list[str] = Field(
        default_factory=list, description="Markets actually offered by bookmakers"
    )
    modelled_markets: list[str] = Field(
        default_factory=list, description="Markets derived by our prediction models"
    )
    market_status: dict[str, str] = Field(
        default_factory=dict,
        description="Per-market taxonomy: 'MODEL_ONLY', 'OFFERED', 'OFFERED_AND_MODELLED', 'OFFERED_BUT_UNMODELLED'",
    )
    coverage_ratio: float = Field(
        default=0.0, description="Ratio of offered markets that are modelled"
    )


class ModelUniverseMetadata(BaseRegistryModel):
    """Model data readiness and statistical availability."""

    data_available: bool = Field(
        default=False, description="Historical match/statistics data is available"
    )
    historical_matches_available: int = Field(
        default=0, description="Approximate count of historical matches"
    )
    xg_available: bool = Field(default=False, description="xG / shot-level data available")
    model_readiness: str = Field(
        default="NO_MARKET_DATA",
        description="'MODEL_READY', 'INSUFFICIENT_HISTORY', 'NO_MARKET_DATA'",
    )


class CompetitionRegistryEntry(BaseRegistryModel):
    """Canonical representation of a global competition in the registry."""

    competition_id: str = Field(..., description="Canonical competition ID, e.g. 'england_premier_league'")
    canonical_name: str = Field(..., description="Canonical competition name, e.g. 'Premier League'")
    country: str = Field(..., description="Country or territory, e.g. 'England'")
    region: str = Field(..., description="Global region, e.g. 'Europe', 'South America', 'International'")
    competition_type: str = Field(
        default="League",
        description="'League', 'Cup', 'Youth', 'Women', 'International', 'Friendly'",
    )
    gender: str = Field(default="Men", description="'Men', 'Women'")
    providers: ProviderPresence = Field(default_factory=ProviderPresence)
    betting: BettingUniverseMetadata = Field(default_factory=BettingUniverseMetadata)
    markets: MarketCoverageMetadata = Field(default_factory=MarketCoverageMetadata)
    model: ModelUniverseMetadata = Field(default_factory=ModelUniverseMetadata)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class FixtureRegistryEntry(BaseRegistryModel):
    """Canonical representation of a global fixture in the registry."""

    fixture_id: str = Field(..., description="Canonical fixture identifier")
    competition_id: str = Field(..., description="Canonical competition identifier")
    competition_name: str = Field(..., description="Human readable competition name")
    country: str = Field(..., description="Country of competition")
    home_team: str = Field(..., description="Canonical home team name")
    away_team: str = Field(..., description="Canonical away team name")
    commence_time: datetime = Field(..., description="Scheduled kickoff time (timezone-aware)")
    providers_present: list[str] = Field(
        default_factory=list, description="List of providers providing this fixture"
    )
    data_available: bool = Field(default=False)
    betting_market_available: bool = Field(default=False)
    turkey_legal_status: str = Field(
        default="UNKNOWN",
        description="'VERIFIED', 'UNKNOWN', 'NOT_OFFERED'",
    )
    offered_markets: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("commence_time", "created_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)
