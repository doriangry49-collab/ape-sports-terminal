"""TASK-014 — Xiddaa Odds Adapter

Normalizes Xiddaa API response into NormalizedOddsRecord objects.

Xiddaa API format (TASK-013B verified):
  - Event endpoint: GET /api/v1/events/{event_id}
  - Response: { data: { id, name, participants, startTime, competition, classification,
                         markets: [ { name, status: {code}, type: {code}, live,
                                      outcomes: [ { name, odd, playable, isSentinelOdd } ] } ] } }
  - odds are DECIMAL format (e.g. 1.29, 5.46, 3.82)
  - Bookmaker = "xiddaa" (Xiddaa is both provider AND bookmaker; no sub-bookmakers)

Pre-match discovery (TASK-013B verified):
  - classification=prematch&from=...&to=... returns today's pre-match events
  - Events with playableMarketCount=0 are valid but have no odds yet
  - Future Süper Lig events may have playableMarketCount=0 until odds open

Validation rules (TASK-013B confirmed field names):
  - playable == True
  - isSentinelOdd == False
  - odd is not None
  - odd > 1.0
  - market status.code != "CLOSED" (optional — playable flag is primary filter)

Provider role: TURKEY / LOCAL MARKET ODDS
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sports_engine.adapters.conversion import (
    OddsFormat,
    normalize_correct_score_selection,
    normalize_htft_selection,
)
from sports_engine.adapters.market_map import normalize_xiddaa_market
from sports_engine.adapters.schema import (
    CanonicalMarket,
    MatchPhase,
    NormalizationResult,
    NormalizedOddsRecord,
    RecordStatus,
    RejectedOddsRecord,
)
from sports_engine.normalization.canonical import normalize_entity_name

logger = logging.getLogger(__name__)

PROVIDER_NAME = "xiddaa"
BOOKMAKER_NAME = "xiddaa"  # Xiddaa is the single bookmaker for this provider


def _make_event_id(
    source_event_id: str,
    home: str,
    away: str,
    kickoff: str | None,
) -> str:
    """Generate deterministic event ID for Xiddaa events."""
    home_n = normalize_entity_name(home)
    away_n = normalize_entity_name(away)
    date_part = ""
    if kickoff:
        try:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            date_part = dt.strftime("%Y%m%d")
        except Exception:
            date_part = "unknown"
    return f"xiddaa_{date_part}_{home_n}_vs_{away_n}"


def _normalize_selection(canonical_market: str, raw_name: str) -> str:
    """Normalize selection label for canonical representation."""
    if canonical_market == CanonicalMarket.CORRECT_SCORE:
        return normalize_correct_score_selection(raw_name)
    if canonical_market == CanonicalMarket.H1_CORRECT_SCORE:
        return normalize_correct_score_selection(raw_name)
    if canonical_market == CanonicalMarket.HT_FT:
        return normalize_htft_selection(raw_name)
    if canonical_market == CanonicalMarket.HT_FT_SCORE:
        # e.g. "0-0 2-1" → keep as-is but strip whitespace
        return raw_name.strip()
    return raw_name.strip()


def normalize_xiddaa_event(
    event_data: dict[str, Any],
    captured_at: datetime | None = None,
) -> NormalizationResult:
    """Normalize a single Xiddaa event detail response into NormalizedOddsRecord list.

    Args:
        event_data: Raw dict from Xiddaa /api/v1/events/{id} response (the 'data' key).
        captured_at: Snapshot timestamp (defaults to now UTC).

    Returns:
        NormalizationResult with accepted records and rejected diagnostics.
    """
    if captured_at is None:
        captured_at = datetime.now(UTC)

    result = NormalizationResult()

    source_event_id = str(event_data.get("id", ""))
    classification = event_data.get("classification", "")  # "prematch" | "finished" etc.

    participants = event_data.get("participants", {})
    home_raw = participants.get("home", "")
    away_raw = participants.get("away", "")
    kickoff = event_data.get("startTime")

    comp = event_data.get("competition", {})
    competition = comp.get("name", "Unknown")
    country_code = comp.get("countryCode", "")
    country = _country_code_to_name(country_code) if country_code else "Unknown"

    if not home_raw or not away_raw:
        result.rejected.append(RejectedOddsRecord(
            provider=PROVIDER_NAME,
            source_event_id=source_event_id,
            source_market_id="",
            source_selection_id="",
            raw_value="",
            reason="Missing home or away participant",
            captured_at=captured_at,
        ))
        return result

    event_id = _make_event_id(source_event_id, home_raw, away_raw, kickoff)

    markets = event_data.get("markets", [])
    if not markets:
        # No markets yet (e.g. playableMarketCount=0 for future events) — not an error
        return result

    for market_data in markets:
        market_name = market_data.get("name", "")
        market_status_code = market_data.get("status", {}).get("code", "")
        source_market_id = market_name  # Xiddaa has no numeric market ID in responses

        canonical_market, market_period = normalize_xiddaa_market(market_name)

        for outcome in market_data.get("outcomes", []):
            o_name = outcome.get("name", "")
            odd = outcome.get("odd")
            playable = outcome.get("playable", False)
            is_sentinel = outcome.get("isSentinelOdd", True)  # default True = safer

            # Validation 1: playable must be True
            if not playable:
                result.rejected.append(RejectedOddsRecord(
                    provider=PROVIDER_NAME,
                    source_event_id=source_event_id,
                    source_market_id=source_market_id,
                    source_selection_id=o_name,
                    raw_value=str(odd),
                    reason="playable is False",
                    captured_at=captured_at,
                ))
                continue

            # Validation 2: must NOT be sentinel
            if is_sentinel:
                result.rejected.append(RejectedOddsRecord(
                    provider=PROVIDER_NAME,
                    source_event_id=source_event_id,
                    source_market_id=source_market_id,
                    source_selection_id=o_name,
                    raw_value=str(odd),
                    reason="isSentinelOdd is True",
                    captured_at=captured_at,
                ))
                continue

            # Validation 3: odd must exist
            if odd is None:
                result.rejected.append(RejectedOddsRecord(
                    provider=PROVIDER_NAME,
                    source_event_id=source_event_id,
                    source_market_id=source_market_id,
                    source_selection_id=o_name,
                    raw_value="null",
                    reason="odd is None",
                    captured_at=captured_at,
                ))
                continue

            # Validation 4: odd > 1.0
            try:
                odd_f = float(odd)
            except (TypeError, ValueError) as exc:
                result.rejected.append(RejectedOddsRecord(
                    provider=PROVIDER_NAME,
                    source_event_id=source_event_id,
                    source_market_id=source_market_id,
                    source_selection_id=o_name,
                    raw_value=str(odd),
                    reason=f"odd not numeric: {exc}",
                    captured_at=captured_at,
                ))
                continue

            if odd_f <= 1.0:
                result.rejected.append(RejectedOddsRecord(
                    provider=PROVIDER_NAME,
                    source_event_id=source_event_id,
                    source_market_id=source_market_id,
                    source_selection_id=o_name,
                    raw_value=str(odd),
                    reason=f"odd {odd_f} <= 1.0",
                    captured_at=captured_at,
                ))
                continue

            normalized_selection = _normalize_selection(canonical_market, o_name)

            record = NormalizedOddsRecord(
                event_id=event_id,
                provider=PROVIDER_NAME,
                bookmaker=BOOKMAKER_NAME,
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
                odds_decimal=round(odd_f, 6),
                odds_raw=str(odd),
                odds_format=OddsFormat.DECIMAL,
                captured_at=captured_at,
                source_event_id=source_event_id,
                source_market_id=source_market_id,
                source_selection_id=o_name,
                source_status=market_status_code,
                status=RecordStatus.VERIFIED_REAL_ODDS,
            )
            result.accepted.append(record)

    return result


def _country_code_to_name(code: str) -> str:
    """Simple country code → name mapping."""
    _MAP = {
        "TR": "Turkey",
        "EN": "England",
        "DE": "Germany",
        "ES": "Spain",
        "FR": "France",
        "IT": "Italy",
        "PT": "Portugal",
        "NL": "Netherlands",
        "BE": "Belgium",
        "AT": "Austria",
        "CH": "Switzerland",
        "RU": "Russia",
    }
    return _MAP.get(code.upper(), code)
