"""TASK-014 — PropLine Odds Adapter

Normalizes PropLine API response into NormalizedOddsRecord objects.

PropLine API format (TASK-013 verified):
  - Sport endpoint: /sports/{sport_key}/events/{event_id}/odds
  - Response: { bookmakers: [ { key, markets: [ { key, outcomes: [ { name, price, point? } ] } ] } ] }
  - price field uses American odds format for most bookmakers
  - No isSentinelOdd / playable flags (PropLine uses price=null for unavailable)

Validation rules:
  - price must not be None
  - odds_decimal > 1.0 after conversion
  - bookmaker key must be present
  - market key must be present
  - selection name must be present

Provider role: GLOBAL BOOKMAKER ODDS
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sports_engine.adapters.conversion import (
    OddsFormat,
    detect_odds_format,
    normalize_correct_score_selection,
    normalize_htft_selection,
    to_decimal,
)
from sports_engine.adapters.market_map import normalize_propline_market
from sports_engine.adapters.schema import (
    MatchPhase,
    NormalizationResult,
    NormalizedOddsRecord,
    RecordStatus,
    RejectedOddsRecord,
)
from sports_engine.normalization.canonical import normalize_entity_name

logger = logging.getLogger(__name__)

PROVIDER_NAME = "propline"


def _make_event_id(home: str, away: str, kickoff: str | None, sport_key: str) -> str:
    """Generate a deterministic event ID for cross-provider matching."""
    home_n = normalize_entity_name(home)
    away_n = normalize_entity_name(away)
    date_part = ""
    if kickoff:
        try:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            date_part = dt.strftime("%Y%m%d")
        except Exception:
            date_part = "unknown"
    sport_n = sport_key.lower().replace(" ", "_")
    return f"propline_{sport_n}_{date_part}_{home_n}_vs_{away_n}"


def _normalize_selection(market_key: str, raw_name: str) -> str:
    """Normalize selection name for canonical representation."""
    if market_key == "correct_score":
        return normalize_correct_score_selection(raw_name)
    if market_key == "halftime_fulltime":
        return normalize_htft_selection(raw_name)
    return raw_name.strip()


def normalize_propline_event(
    event_data: dict[str, Any],
    sport_key: str,
    competition: str,
    country: str,
    captured_at: datetime | None = None,
) -> NormalizationResult:
    """Normalize a single PropLine event response dict into NormalizedOddsRecord list.

    Args:
        event_data: Raw dict from PropLine events endpoint.
            Expected keys: id, home_team, away_team, commence_time, bookmakers
        sport_key: PropLine sport key, e.g. 'soccer_turkey_super_lig'
        competition: Human-readable competition name
        country: Country of competition
        captured_at: Snapshot timestamp (defaults to now UTC)

    Returns:
        NormalizationResult with accepted records and rejected diagnostics.
    """
    if captured_at is None:
        captured_at = datetime.now(UTC)

    result = NormalizationResult()

    home_raw = event_data.get("home_team", "")
    away_raw = event_data.get("away_team", "")
    kickoff = event_data.get("commence_time")
    source_event_id = str(event_data.get("id", ""))

    if not home_raw or not away_raw:
        result.rejected.append(RejectedOddsRecord(
            provider=PROVIDER_NAME,
            source_event_id=source_event_id,
            source_market_id="",
            source_selection_id="",
            raw_value="",
            reason="Missing home_team or away_team in event",
            captured_at=captured_at,
        ))
        return result

    event_id = _make_event_id(home_raw, away_raw, kickoff, sport_key)

    bookmakers = event_data.get("bookmakers", [])
    if not bookmakers:
        # Event exists but has no bookmakers — not an error, just empty
        return result

    for bk_data in bookmakers:
        bookmaker_key = bk_data.get("key", "")
        if not bookmaker_key:
            result.rejected.append(RejectedOddsRecord(
                provider=PROVIDER_NAME,
                source_event_id=source_event_id,
                source_market_id="",
                source_selection_id="",
                raw_value="",
                reason="Bookmaker has no key",
                captured_at=captured_at,
            ))
            continue

        for market_data in bk_data.get("markets", []):
            market_key = market_data.get("key", "")
            if not market_key:
                continue

            canonical_market, market_period = normalize_propline_market(market_key)

            for outcome in market_data.get("outcomes", []):
                selection_raw = outcome.get("name", "")
                price_raw = outcome.get("price")
                point = outcome.get("point")  # for spreads/totals line

                # Build full selection label including line if available
                selection_label = selection_raw
                if point is not None:
                    selection_label = f"{selection_raw} {point}"

                # Validation: price must exist
                if price_raw is None:
                    result.rejected.append(RejectedOddsRecord(
                        provider=PROVIDER_NAME,
                        source_event_id=source_event_id,
                        source_market_id=market_key,
                        source_selection_id=selection_raw,
                        raw_value="null",
                        reason="price is None",
                        captured_at=captured_at,
                    ))
                    continue

                # Detect format and convert
                try:
                    price_float = float(price_raw)
                    fmt = detect_odds_format(price_float)
                    if fmt == OddsFormat.UNKNOWN:
                        result.rejected.append(RejectedOddsRecord(
                            provider=PROVIDER_NAME,
                            source_event_id=source_event_id,
                            source_market_id=market_key,
                            source_selection_id=selection_raw,
                            raw_value=str(price_raw),
                            reason=f"Unknown odds format for value {price_raw}",
                            captured_at=captured_at,
                        ))
                        continue

                    odds_decimal = to_decimal(price_float, fmt)
                except (ValueError, TypeError) as exc:
                    result.rejected.append(RejectedOddsRecord(
                        provider=PROVIDER_NAME,
                        source_event_id=source_event_id,
                        source_market_id=market_key,
                        source_selection_id=selection_raw,
                        raw_value=str(price_raw),
                        reason=f"Conversion error: {exc}",
                        captured_at=captured_at,
                    ))
                    continue

                # Validate decimal > 1.0
                if odds_decimal <= 1.0:
                    result.rejected.append(RejectedOddsRecord(
                        provider=PROVIDER_NAME,
                        source_event_id=source_event_id,
                        source_market_id=market_key,
                        source_selection_id=selection_raw,
                        raw_value=str(price_raw),
                        reason=f"odds_decimal {odds_decimal} <= 1.0",
                        captured_at=captured_at,
                    ))
                    continue

                # Normalize selection
                normalized_selection = _normalize_selection(market_key, selection_label)

                record = NormalizedOddsRecord(
                    event_id=event_id,
                    provider=PROVIDER_NAME,
                    bookmaker=bookmaker_key,
                    sport="soccer",
                    country=country,
                    competition=competition,
                    home_team=home_raw,
                    away_team=away_raw,
                    kickoff=kickoff,
                    market=canonical_market,
                    market_period=market_period,
                    match_phase=MatchPhase.PREMATCH,
                    selection=normalized_selection,
                    odds_decimal=odds_decimal,
                    odds_raw=str(price_raw),
                    odds_format=fmt,
                    captured_at=captured_at,
                    source_event_id=source_event_id,
                    source_market_id=market_key,
                    source_selection_id=selection_raw,
                    source_status="bookmaker_offer",
                    status=RecordStatus.VERIFIED_REAL_ODDS,
                )
                result.accepted.append(record)

    return result


def normalize_propline_response(
    response_data: list[dict[str, Any]],
    sport_key: str,
    competition: str,
    country: str,
    captured_at: datetime | None = None,
) -> NormalizationResult:
    """Normalize a full PropLine sport response (list of events) into records."""
    if captured_at is None:
        captured_at = datetime.now(UTC)

    combined = NormalizationResult()
    for ev in response_data:
        event_result = normalize_propline_event(ev, sport_key, competition, country, captured_at)
        combined.accepted.extend(event_result.accepted)
        combined.rejected.extend(event_result.rejected)
    return combined
