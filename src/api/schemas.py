"""Pydantic v2 schemas for APE Sports-Engine B2B REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DevigRequest(BaseModel):
    odds: list[float] = Field(
        ...,
        description="List of offered bookmaker odds, e.g. [2.10, 3.40, 3.80]",
        min_length=2,
    )
    method: str = Field(
        default="shin",
        description="Devigging algorithm: 'shin', 'power', 'multiplicative', 'additive', or 'logarithmic'",
    )


class DevigResponse(BaseModel):
    method: str
    odds: list[float]
    probabilities: list[float]
    fair_odds: list[float]
    margin: float
    margin_pct: float
    z_parameter: float | None = None


class ValueSignalSchema(BaseModel):
    fixture_id: str
    league: str
    home_team: str
    away_team: str
    kickoff_trt: str
    market: str
    selection: str
    bookmaker: str
    offered_odds: float
    fair_odds_shin: float
    fair_prob_shin: float
    model_prob: float
    edge_pct: float
    ev_roi: float
    half_kelly: float
    shin_margin: float


class ActiveSignalsResponse(BaseModel):
    count: int
    signals: list[ValueSignalSchema]
    timestamp_utc: str


class LedgerSummaryResponse(BaseModel):
    total_bets: int
    pending_bets: int
    settled_bets: int
    won_bets: int
    win_rate_pct: float
    net_units: float
    roi_pct: float
    avg_clv_ratio: float
    beat_clv_pct: float


class HealthResponse(BaseModel):
    status: str
    engine_name: str
    engine_version: str
    timestamp_utc: str
    daemon_status: dict[str, Any]
