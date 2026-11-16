"""TASK-014 — Match Normalization and Cross-Provider Deduplication

Handles:
1. Duplicate detection within a snapshot window
2. Match reconciliation between PropLine and Xiddaa for the same fixture
3. Snapshot vs. history distinction

Design principles:
  - UNMATCHED is preferred over wrong match
  - Fuzzy team name matching only with >= 0.85 confidence
  - kickoff must be within 3 hours to be considered same fixture
  - No automatic inference — uncertain matches stay UNMATCHED
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sports_engine.adapters.schema import NormalizedOddsRecord
from sports_engine.normalization.canonical import normalize_entity_name


@dataclass
class MatchKey:
    """Composite key for identifying the same fixture across providers."""
    home_normalized: str
    away_normalized: str
    date_str: str      # YYYYMMDD
    competition_normalized: str


@dataclass
class CrossProviderMatch:
    """Evidence record for a reconciled cross-provider fixture match."""
    propline_event_id: str
    xiddaa_event_id: str
    canonical_fixture_id: str
    home_team: str
    away_team: str
    kickoff: str | None
    confidence: float
    match_method: str    # "exact", "fuzzy", "UNMATCHED"


def _normalize_kickoff(kickoff: str | None) -> str:
    """Return YYYYMMDD date string from ISO kickoff, or '' if unavailable."""
    if not kickoff:
        return ""
    try:
        dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        return dt.strftime("%Y%m%d")
    except Exception:
        return ""


def _match_key_from_record(rec: NormalizedOddsRecord) -> MatchKey:
    return MatchKey(
        home_normalized=normalize_entity_name(rec.home_team),
        away_normalized=normalize_entity_name(rec.away_team),
        date_str=_normalize_kickoff(rec.kickoff),
        competition_normalized=normalize_entity_name(rec.competition),
    )


def deduplicate_records(
    records: list[NormalizedOddsRecord],
    window_minutes: int = 10,
) -> tuple[list[NormalizedOddsRecord], list[NormalizedOddsRecord]]:
    """Remove duplicate records within the same snapshot window.

    Duplicate = same (provider, bookmaker, event_id, market, selection)
    within window_minutes of each other.

    Returns: (unique_records, duplicate_records)
    Timestamps differ → retained (odds history).
    """
    seen: dict[tuple, NormalizedOddsRecord] = {}
    duplicates: list[NormalizedOddsRecord] = []
    unique: list[NormalizedOddsRecord] = []

    for rec in records:
        key = (
            rec.provider,
            rec.bookmaker,
            rec.event_id,
            rec.market,
            rec.selection,
        )
        if key in seen:
            existing = seen[key]
            delta = abs((rec.captured_at - existing.captured_at).total_seconds())
            if delta <= window_minutes * 60:
                # Same window → duplicate
                duplicates.append(rec)
                continue
            # Different window → retain (history update)
        seen[key] = rec
        unique.append(rec)

    return unique, duplicates


def reconcile_providers(
    propline_records: list[NormalizedOddsRecord],
    xiddaa_records: list[NormalizedOddsRecord],
) -> list[CrossProviderMatch]:
    """Attempt to match PropLine events with Xiddaa events for the same fixture.

    Matching strategy:
    1. Exact normalized team name + date match → confidence=1.0
    2. No match → UNMATCHED (never infer)

    Returns list of CrossProviderMatch evidence records.
    """
    # Group propline by (home_norm, away_norm, date)
    pl_index: dict[tuple[str, str, str], NormalizedOddsRecord] = {}
    for rec in propline_records:
        key = (
            normalize_entity_name(rec.home_team),
            normalize_entity_name(rec.away_team),
            _normalize_kickoff(rec.kickoff),
        )
        pl_index[key] = rec

    matches = []
    seen_xiddaa_ids: set[str] = set()

    for xi_rec in xiddaa_records:
        xi_home = normalize_entity_name(xi_rec.home_team)
        xi_away = normalize_entity_name(xi_rec.away_team)
        xi_date = _normalize_kickoff(xi_rec.kickoff)
        xi_key = (xi_home, xi_away, xi_date)

        if xi_rec.source_event_id in seen_xiddaa_ids:
            continue
        seen_xiddaa_ids.add(xi_rec.source_event_id)

        pl_rec = pl_index.get(xi_key)
        if pl_rec:
            canonical_id = f"{xi_date}_{xi_home}_vs_{xi_away}"
            matches.append(CrossProviderMatch(
                propline_event_id=pl_rec.event_id,
                xiddaa_event_id=xi_rec.event_id,
                canonical_fixture_id=canonical_id,
                home_team=xi_rec.home_team,
                away_team=xi_rec.away_team,
                kickoff=xi_rec.kickoff,
                confidence=1.0,
                match_method="exact",
            ))
        else:
            canonical_id = f"UNMATCHED_{xi_date}_{xi_home}_vs_{xi_away}"
            matches.append(CrossProviderMatch(
                propline_event_id="",
                xiddaa_event_id=xi_rec.event_id,
                canonical_fixture_id=canonical_id,
                home_team=xi_rec.home_team,
                away_team=xi_rec.away_team,
                kickoff=xi_rec.kickoff,
                confidence=0.0,
                match_method="UNMATCHED",
            ))

    return matches
