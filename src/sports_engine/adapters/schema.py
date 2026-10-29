"""TASK-014 — Normalized Odds Schema

Canonical internal model for dual-provider bookmaker odds.
All odds from PropLine and Xiddaa are mapped to NormalizedOddsRecord.

Design rules:
  - odds_decimal is the canonical comparison format (>1.0, always decimal)
  - odds_raw + odds_format preserve the original provider value unmodified
  - provider ≠ bookmaker (PropLine can contain Bovada, Pinnacle, etc.)
  - model probabilities, fair odds, edge: NOT stored here (future task)
  - source provenance fields are always populated
  - invalid/sentinel/unplayable records are rejected with a reason
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Optional


class OddsFormat(str, Enum):
    """Raw odds format as received from provider."""
    DECIMAL = "DECIMAL"
    AMERICAN = "AMERICAN"
    UNKNOWN = "UNKNOWN"


class MarketPeriod(str, Enum):
    """Period of the match this market covers."""
    FULL_MATCH = "FULL_MATCH"
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"
    UNKNOWN = "UNKNOWN"


class CanonicalMarket(str, Enum):
    """Canonical market identifiers.

    Only markets with VERIFIED_REAL_ODDS evidence from TASK-013 / TASK-013B are listed.
    Do not add a market here unless it has been proven by experiment.
    """
    # PropLine VERIFIED (TASK-013)
    H1X2 = "1X2"
    TOTALS = "TOTALS"
    SPREAD = "SPREAD"
    CORRECT_SCORE = "CORRECT_SCORE"

    # Xiddaa VERIFIED pre-match (TASK-013B)
    BTTS = "BTTS"
    HT_FT = "HT_FT"
    H1_1X2 = "H1_1X2"
    H1_TOTALS = "H1_TOTALS"
    H1_BTTS = "H1_BTTS"
    H1_CORRECT_SCORE = "H1_CORRECT_SCORE"
    HT_FT_SCORE = "HT_FT_SCORE"   # Xiddaa "1. Yarı/Maç Sonucu Skorları"
    HANDICAP = "HANDICAP"

    UNKNOWN = "UNKNOWN"


class MatchPhase(str, Enum):
    PREMATCH = "PREMATCH"
    LIVE = "LIVE"


class RecordStatus(str, Enum):
    VERIFIED_REAL_ODDS = "VERIFIED_REAL_ODDS"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class NormalizedOddsRecord:
    """Canonical odds record from any provider.

    Immutable after creation. All comparison uses odds_decimal.
    odds_raw + odds_format always preserve the original value.
    """

    # ── Identity ──────────────────────────────────────────────
    event_id: str                      # Canonical fixture identifier (generated)
    provider: str                      # "propline" | "xiddaa"
    bookmaker: str                     # Actual bookmaker: "bovada", "fanduel", "xiddaa", etc.

    # ── Match context ─────────────────────────────────────────
    sport: str                         # e.g. "soccer"
    country: str                       # e.g. "Turkey", "World"
    competition: str                   # e.g. "Trendyol Süper Lig"
    home_team: str
    away_team: str
    kickoff: Optional[str]             # ISO 8601 string from provider

    # ── Market ───────────────────────────────────────────────
    market: str                        # CanonicalMarket value or raw if unmapped
    market_period: str                 # MarketPeriod value
    match_phase: str                   # "PREMATCH" | "LIVE"

    # ── Selection & price ─────────────────────────────────────
    selection: str                     # e.g. "HOME", "DRAW", "1-0", "1/1"
    odds_decimal: float                # Canonical format (>1.0)
    odds_raw: str                      # Original raw value as string
    odds_format: str                   # OddsFormat value

    # ── Provenance ───────────────────────────────────────────
    captured_at: datetime              # When snapshot was taken (UTC)
    source_event_id: str               # Provider's own event/fixture ID
    source_market_id: str              # Provider's market key/name
    source_selection_id: str           # Provider's selection name/id
    source_status: str                 # Provider's raw status string

    # ── Quality ───────────────────────────────────────────────
    status: str = RecordStatus.VERIFIED_REAL_ODDS


@dataclass
class RejectedOddsRecord:
    """Record rejected during normalization with a diagnostic reason."""
    provider: str
    source_event_id: str
    source_market_id: str
    source_selection_id: str
    raw_value: str
    reason: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class NormalizationResult:
    """Output of a normalization run: accepted records + rejected diagnostics."""
    accepted: list[NormalizedOddsRecord] = field(default_factory=list)
    rejected: list[RejectedOddsRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)

    @property
    def acceptance_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return len(self.accepted) / self.total
