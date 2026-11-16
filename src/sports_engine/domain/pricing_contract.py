"""Domain contract and data models for Phase 2A Pricing Intelligence.

Covers:
- No-Vig computation models (Multiplicative, Shin, Power)
- Market probability, overround, and fair odds representation
- Selection edge (raw edge and uncertainty-adjusted edge)
- Strict phase guard enforcement
- Exclusion of MODEL_DERIVED and longshot markets from Phase 2A
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NoVigMethod(str, Enum):
    """Supported No-Vig methods."""

    MULTIPLICATIVE = "MULTIPLICATIVE"
    SHIN = "SHIN"
    POWER = "POWER"


class Phase2ASupportedMarket(str, Enum):
    """Strictly allowed markets in Phase 2A. High-odds/longshots are deferred to Phase 2C."""

    ONE_X_TWO = "1X2"
    TOTALS = "TOTALS"
    BTTS = "BTTS"


class MarketPricingResult(BaseModel):
    """Container for bookmaker market pricing and no-vig normalization results."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    market_name: str = Field(..., description="Market name, e.g. '1X2', 'TOTALS', 'BTTS'")
    method: NoVigMethod = Field(..., description="No-vig algorithm used")
    overround: float = Field(..., description="Total market overround (sum of raw implied probabilities, e.g. 1.05)")
    raw_implied_probabilities: dict[str, float] = Field(
        ..., description="Raw implied probabilities before margin removal (1 / price)"
    )
    no_vig_probabilities: dict[str, float] = Field(
        ..., description="True fair market probabilities after margin removal (sum = 1.0)"
    )
    fair_odds: dict[str, float] = Field(
        ..., description="Fair market odds without bookmaker margin (1 / no_vig_probability)"
    )


class SelectionEdge(BaseModel):
    """Calculated edge for a specific selection comparing model probability with market fair price."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    fixture_id: str = Field(..., description="Canonical fixture identifier")
    market: str = Field(..., description="Market identifier (must be 1X2, TOTALS, or BTTS in Phase 2A)")
    selection: str = Field(..., description="Selection outcome, e.g. 'HOME', 'DRAW', 'OVER 2.5'")
    entry_odds: float = Field(..., description="Bookmaker offering price (> 1.0)")
    model_probability: float = Field(..., description="Model derived probability [0.0, 1.0]")
    model_fair_odds: float = Field(..., description="Model fair odds (1.0 / model_probability)")
    market_no_vig_probability: float = Field(..., description="Market fair probability after margin removal")
    raw_edge: float = Field(
        ...,
        description=(
            "Raw Edge defined as: model_probability - market_no_vig_probability. "
            "Positive (> 0.0) indicates model sees positive expected value over market consensus. "
            "Negative (< 0.0) indicates market consensus prices outcome higher than model."
        ),
    )
    adjusted_edge: float | None = Field(
        default=None,
        description=(
            "Uncertainty-adjusted edge. Set to None (representing UNKNOWN) if no verified "
            "model uncertainty metric exists. Never invent fake certainty heuristics."
        ),
    )
    source_classification: str = Field(
        default="BOOKMAKER_OFFERED",
        description="Must be 'BOOKMAKER_OFFERED'. MODEL_DERIVED markets are strictly forbidden in Phase 2A.",
    )
    match_phase: str = Field(default="PREMATCH", description="'PREMATCH' or 'LIVE'")
    notes: str = Field(default="", description="Diagnostic or audit commentary")

    @field_validator("entry_odds")
    @classmethod
    def check_entry_odds(cls, v: float) -> float:
        if v <= 1.0:
            raise ValueError(f"Entry odds must be > 1.0, got {v}")
        return v

    @field_validator("model_probability", "market_no_vig_probability")
    @classmethod
    def check_probability_bounds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Probability must be within [0.0, 1.0], got {v}")
        return v
