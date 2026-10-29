"""Data contract and strict canonical schemas for odds, timestamps, and phase guards."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    """Validate that datetime has timezone information."""
    if dt is not None:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(f"Datetime '{dt}' must be timezone-aware.")
    return dt


class TimestampLayers(BaseModel):
    """Four strictly separated timestamp layers. Never promote event timestamp to outcome level."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    event_last_update: str = Field(default="UNKNOWN", description="Timestamp from event container")
    market_last_update: str = Field(default="UNKNOWN", description="Timestamp from market container")
    outcome_last_update: str = Field(
        default="UNKNOWN", description="Timestamp directly on outcome quote. UNKNOWN if missing."
    )
    snapshot_collected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Pipeline ingestion timestamp when record was collected",
    )

    @field_validator("snapshot_collected_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class CanonicalOddsRecord(BaseModel):
    """Canonical odds record required for Phase 2 No-Vig and Edge calculations."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    fixture_id: str = Field(..., description="Canonical fixture identifier")
    provider: str = Field(..., description="Provider source, e.g. 'prop_line', 'bzzoiro'")
    bookmaker: str = Field(..., description="Bookmaker name, e.g. 'Pinnacle', 'Bovada'")
    market: str = Field(..., description="Standardized market name, e.g. '1X2', 'Totals'")
    selection: str = Field(..., description="Selection name, e.g. 'HOME', 'DRAW', 'OVER 2.5'")
    price: float = Field(..., description="Decimal odds price")
    event_last_update: str = Field(default="UNKNOWN")
    market_last_update: str = Field(default="UNKNOWN")
    outcome_last_update: str = Field(default="UNKNOWN")
    snapshot_collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    match_phase: str = Field(..., description="'PREMATCH' or 'LIVE'")
    source: str = Field(..., description="'PROP_LINE', 'API_FOOTBALL', 'XIDDAA', etc.")

    @field_validator("snapshot_collected_at", mode="after")
    @classmethod
    def check_tz(cls, v: datetime | None) -> datetime | None:
        return ensure_timezone_aware(v)


class CrossProviderFixtureMatchEvidence(BaseModel):
    """Evidence record for reconciliation between two providers."""

    provider_A: str
    provider_B: str
    fixture_A: str
    fixture_B: str
    canonical_fixture_id: str
    match_method: str
    team_match: str
    date_match: str
    competition_match: str
    confidence: float


def validate_phase_compatibility(model_phase: str, odds_phase: str) -> bool:
    """Strict guard preventing cross-contamination between PREMATCH and LIVE markets.

    Allowed:
      PREMATCH model <-> PREMATCH odds
      LIVE model <-> LIVE odds

    Forbidden:
      PREMATCH model <-> LIVE odds
      LIVE model <-> PREMATCH odds
    """
    m_p = model_phase.upper().strip()
    o_p = odds_phase.upper().strip()

    if m_p != o_p:
        raise ValueError(
            f"Phase mismatch violation: Cannot compare {m_p} model with {o_p} odds. "
            f"Cross-phase operations are strictly forbidden."
        )
    return True
