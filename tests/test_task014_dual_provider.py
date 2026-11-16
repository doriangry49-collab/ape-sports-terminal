"""TASK-014 — Unit Tests: Dual Odds Provider Integration MVP

Tests:
  Test 1:  PropLine 1X2 → normalized decimal
  Test 2:  PropLine American odds → correct decimal conversion
  Test 3:  PropLine Correct Score → normalized selection
  Test 4:  Xiddaa Correct Score → normalized odds
  Test 5:  Xiddaa HT/FT → normalized selection
  Test 6:  price=None / odd=None → rejected
  Test 7:  isSentinelOdd=True → rejected
  Test 8:  playable=False → rejected
  Test 9:  duplicate snapshot → handled
  Test 10: different timestamp → retained
  Test 11: same teams uncertain match → NOT auto-matched (UNMATCHED)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sports_engine.adapters.conversion import (
    american_to_decimal,
    detect_odds_format,
    normalize_correct_score_selection,
    normalize_htft_selection,
)
from sports_engine.adapters.match_normalizer import deduplicate_records, reconcile_providers
from sports_engine.adapters.propline_adapter import normalize_propline_event
from sports_engine.adapters.schema import (
    CanonicalMarket,
    MatchPhase,
    NormalizedOddsRecord,
    OddsFormat,
    RecordStatus,
)
from sports_engine.adapters.xiddaa_adapter import normalize_xiddaa_event

# ────────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────────────────────

CAPTURED_AT = datetime(2026, 10, 2, 15, 0, 0, tzinfo=UTC)


def _propline_event_1x2(home="Arsenal", away="Leeds", h2h_odds=None):
    """Minimal PropLine event dict with h2h (1X2) market in American format."""
    if h2h_odds is None:
        h2h_odds = [
            {"name": "Arsenal", "price": -175},  # favourite → ~1.571 decimal
            {"name": "Draw", "price": 310},       # → 4.10 decimal
            {"name": "Leeds United", "price": 490},  # → 5.90 decimal
        ]
    return {
        "id": "ev_001",
        "home_team": home,
        "away_team": away,
        "commence_time": "2026-10-10T14:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "last_update": "2026-10-02T12:00:00Z",
                "markets": [
                    {"key": "h2h", "outcomes": h2h_odds}
                ],
            }
        ],
    }


def _propline_event_correct_score():
    return {
        "id": "ev_002",
        "home_team": "Arsenal",
        "away_team": "Leeds",
        "commence_time": "2026-10-10T14:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "correct_score",
                        "outcomes": [
                            {"name": "0 - 1", "price": 1200},
                            {"name": "2 - 0", "price": 450},
                        ],
                    }
                ],
            }
        ],
    }


def _xiddaa_event_correct_score():
    return {
        "id": 3202999,
        "name": "Erciyes 38 - Yeni Mersin",
        "participants": {"home": "Erciyes 38", "away": "Yeni Mersin"},
        "startTime": "2026-10-02T12:30:00.000Z",
        "classification": "prematch",
        "competition": {"id": 80730, "name": "TFF 3. Lig", "countryCode": "TR"},
        "markets": [
            {
                "name": "Maç Skoru",
                "status": {"code": "OPEN"},
                "type": {"code": "PREMATCH"},
                "live": False,
                "outcomes": [
                    {"name": "1-0", "odd": 4.50, "playable": True, "isSentinelOdd": False},
                    {"name": "2-1", "odd": 12.5, "playable": True, "isSentinelOdd": False},
                    {"name": "0-0", "odd": 6.20, "playable": True, "isSentinelOdd": False},
                ],
            }
        ],
    }


def _xiddaa_event_htft():
    return {
        "id": 3172837,
        "name": "Avusturya U21 - Danimarka U21",
        "participants": {"home": "Avusturya U21", "away": "Danimarka U21"},
        "startTime": "2026-10-02T16:00:00.000Z",
        "classification": "prematch",
        "competition": {"id": 100, "name": "UEFA U21 Eleme", "countryCode": ""},
        "markets": [
            {
                "name": "1. Yarı / Maç Sonucu",
                "status": {"code": "OPEN"},
                "type": {"code": "PREMATCH"},
                "live": False,
                "outcomes": [
                    {"name": "1/1", "odd": 8.08, "playable": True, "isSentinelOdd": False},
                    {"name": "1/0", "odd": 16.95, "playable": True, "isSentinelOdd": False},
                    {"name": "2/1", "odd": 36.5, "playable": True, "isSentinelOdd": False},
                ],
            }
        ],
    }


def _make_normalized_record(
    provider="propline",
    bookmaker="bovada",
    event_id="ev_001",
    market=CanonicalMarket.H1X2,
    selection="HOME",
    odds_decimal=1.8,
    captured_at=None,
    home_team="Arsenal",
    away_team="Leeds",
    kickoff="2026-10-10T14:00:00Z",
) -> NormalizedOddsRecord:
    return NormalizedOddsRecord(
        event_id=event_id,
        provider=provider,
        bookmaker=bookmaker,
        sport="soccer",
        country="England",
        competition="EPL",
        home_team=home_team,
        away_team=away_team,
        kickoff=kickoff,
        market=market,
        market_period="FULL_MATCH",
        match_phase=MatchPhase.PREMATCH,
        selection=selection,
        odds_decimal=odds_decimal,
        odds_raw=str(odds_decimal),
        odds_format=OddsFormat.DECIMAL,
        captured_at=captured_at or CAPTURED_AT,
        source_event_id="src_001",
        source_market_id="h2h",
        source_selection_id=selection,
        source_status="open",
        status=RecordStatus.VERIFIED_REAL_ODDS,
    )


# ────────────────────────────────────────────────────────────────────────────────
# TEST 1: PropLine 1X2 → normalized decimal
# ────────────────────────────────────────────────────────────────────────────────

def test_propline_1x2_normalized():
    """PropLine h2h outcomes are normalized to decimal odds > 1.0."""
    ev = _propline_event_1x2()
    result = normalize_propline_event(
        ev, "soccer_epl", "Premier League", "England", CAPTURED_AT
    )

    assert len(result.accepted) == 3, f"Expected 3 outcomes, got {len(result.accepted)}"

    selections = {r.selection: r.odds_decimal for r in result.accepted}

    # All decimal odds must be > 1.0
    for sel, dec in selections.items():
        assert dec > 1.0, f"{sel}: odds_decimal {dec} is not > 1.0"

    # Market must be canonical 1X2
    for r in result.accepted:
        assert r.market == CanonicalMarket.H1X2
        assert r.provider == "propline"
        assert r.bookmaker == "bovada"
        assert r.match_phase == MatchPhase.PREMATCH


# ────────────────────────────────────────────────────────────────────────────────
# TEST 2: PropLine American odds → correct decimal conversion
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("american, expected_decimal", [
    (250,   3.50),
    (-150,  1.666667),
    (100,   2.00),
    (-100,  2.00),
    (5500,  56.00),
    (490,   5.90),
    (-175,  1.571429),
    (310,   4.10),
])
def test_american_to_decimal_conversion(american, expected_decimal):
    """American odds must convert to correct decimal within tolerance."""
    result = american_to_decimal(float(american))
    assert abs(result - expected_decimal) < 0.001, (
        f"american={american}: expected ~{expected_decimal}, got {result}"
    )


def test_detect_odds_format_american():
    assert detect_odds_format(250) == OddsFormat.AMERICAN
    assert detect_odds_format(-150) == OddsFormat.AMERICAN
    assert detect_odds_format(5500) == OddsFormat.AMERICAN


def test_detect_odds_format_decimal():
    assert detect_odds_format(3.50) == OddsFormat.DECIMAL
    assert detect_odds_format(1.05) == OddsFormat.DECIMAL
    assert detect_odds_format(45.5) == OddsFormat.DECIMAL


# ────────────────────────────────────────────────────────────────────────────────
# TEST 3: PropLine Correct Score → normalized selection
# ────────────────────────────────────────────────────────────────────────────────

def test_propline_correct_score_selection_normalized():
    """Correct Score selection strings must be normalized to canonical H-A format."""
    ev = _propline_event_correct_score()
    result = normalize_propline_event(
        ev, "soccer_epl", "Premier League", "England", CAPTURED_AT
    )

    assert len(result.accepted) == 2
    selections = {r.selection for r in result.accepted}
    assert "0-1" in selections
    assert "2-0" in selections
    for r in result.accepted:
        assert r.market == CanonicalMarket.CORRECT_SCORE


@pytest.mark.parametrize("raw, expected", [
    ("0 - 1",  "0-1"),
    ("2-0",    "2-0"),
    ("1 : 2",  "1-2"),
    ("0:0",    "0-0"),
    ("3 - 2",  "3-2"),
])
def test_correct_score_normalization(raw, expected):
    assert normalize_correct_score_selection(raw) == expected


# ────────────────────────────────────────────────────────────────────────────────
# TEST 4: Xiddaa Correct Score → normalized odds
# ────────────────────────────────────────────────────────────────────────────────

def test_xiddaa_correct_score_normalized():
    """Xiddaa Correct Score outcomes are normalized with decimal odds > 1.0."""
    ev = _xiddaa_event_correct_score()
    result = normalize_xiddaa_event(ev, CAPTURED_AT)

    assert len(result.accepted) == 3

    for r in result.accepted:
        assert r.provider == "xiddaa"
        assert r.bookmaker == "xiddaa"
        assert r.odds_decimal > 1.0
        assert r.odds_format == OddsFormat.DECIMAL
        assert r.market == CanonicalMarket.CORRECT_SCORE
        assert r.status == RecordStatus.VERIFIED_REAL_ODDS

    odds_by_sel = {r.selection: r.odds_decimal for r in result.accepted}
    assert abs(odds_by_sel.get("1-0", 0) - 4.50) < 0.001
    assert abs(odds_by_sel.get("2-1", 0) - 12.5) < 0.001


# ────────────────────────────────────────────────────────────────────────────────
# TEST 5: Xiddaa HT/FT → normalized selection
# ────────────────────────────────────────────────────────────────────────────────

def test_xiddaa_htft_normalized():
    """Xiddaa HT/FT market is normalized with correct canonical market and selections."""
    ev = _xiddaa_event_htft()
    result = normalize_xiddaa_event(ev, CAPTURED_AT)

    assert len(result.accepted) == 3

    for r in result.accepted:
        assert r.market == CanonicalMarket.HT_FT
        assert r.odds_decimal > 1.0
        assert r.provider == "xiddaa"

    # Verify specific HT/FT selections and odds
    by_sel = {r.selection: r.odds_decimal for r in result.accepted}
    assert "1/1" in by_sel
    assert "1/0" in by_sel
    assert "2/1" in by_sel
    assert abs(by_sel["1/1"] - 8.08) < 0.001
    assert abs(by_sel["2/1"] - 36.5) < 0.001


@pytest.mark.parametrize("raw, expected", [
    ("1/1",   "1/1"),
    ("X/2",   "X/2"),
    ("2 / 1", "2/1"),
    ("1 / X", "1/X"),
])
def test_htft_selection_normalization(raw, expected):
    assert normalize_htft_selection(raw) == expected


# ────────────────────────────────────────────────────────────────────────────────
# TEST 6: price=None / odd=None → rejected
# ────────────────────────────────────────────────────────────────────────────────

def test_propline_null_price_rejected():
    """PropLine outcome with price=None must be rejected."""
    ev = {
        "id": "ev_null",
        "home_team": "TeamA",
        "away_team": "TeamB",
        "commence_time": "2026-10-10T14:00:00Z",
        "bookmakers": [
            {
                "key": "bovada",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "TeamA", "price": None},
                            {"name": "Draw",  "price": 300},
                        ],
                    }
                ],
            }
        ],
    }
    result = normalize_propline_event(ev, "soccer_epl", "EPL", "England", CAPTURED_AT)
    assert len(result.accepted) == 1   # Only Draw accepted
    assert len(result.rejected) == 1
    assert "None" in result.rejected[0].reason or "price" in result.rejected[0].reason.lower()


def test_xiddaa_null_odd_rejected():
    """Xiddaa outcome with odd=None must be rejected."""
    ev = {
        "id": 999,
        "name": "A - B",
        "participants": {"home": "TeamA", "away": "TeamB"},
        "startTime": "2026-10-02T14:00:00.000Z",
        "classification": "prematch",
        "competition": {"id": 1, "name": "Test League", "countryCode": "TR"},
        "markets": [
            {
                "name": "Maç Sonucu",
                "status": {"code": "OPEN"},
                "outcomes": [
                    {"name": "1", "odd": None,  "playable": True,  "isSentinelOdd": False},
                    {"name": "0", "odd": 3.50,  "playable": True,  "isSentinelOdd": False},
                ],
            }
        ],
    }
    result = normalize_xiddaa_event(ev, CAPTURED_AT)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "odd is None"


# ────────────────────────────────────────────────────────────────────────────────
# TEST 7: isSentinelOdd=True → rejected
# ────────────────────────────────────────────────────────────────────────────────

def test_xiddaa_sentinel_rejected():
    """Xiddaa outcome with isSentinelOdd=True must be rejected."""
    ev = {
        "id": 1001,
        "name": "X - Y",
        "participants": {"home": "X", "away": "Y"},
        "startTime": "2026-10-02T14:00:00.000Z",
        "classification": "prematch",
        "competition": {"id": 1, "name": "Test", "countryCode": "TR"},
        "markets": [
            {
                "name": "Maç Sonucu",
                "status": {"code": "OPEN"},
                "outcomes": [
                    {"name": "1", "odd": 1.0,  "playable": True,  "isSentinelOdd": True},
                    {"name": "0", "odd": 5.0,  "playable": True,  "isSentinelOdd": False},
                ],
            }
        ],
    }
    result = normalize_xiddaa_event(ev, CAPTURED_AT)
    # Sentinel must be rejected; odd=1.0 is also invalid but sentinel check comes first
    sentinel_rej = [r for r in result.rejected if "Sentinel" in r.reason or "sentinel" in r.reason.lower()]
    assert len(sentinel_rej) >= 1
    assert len(result.accepted) == 1  # Only the non-sentinel @5.0


# ────────────────────────────────────────────────────────────────────────────────
# TEST 8: playable=False → rejected
# ────────────────────────────────────────────────────────────────────────────────

def test_xiddaa_not_playable_rejected():
    """Xiddaa outcome with playable=False must be rejected."""
    ev = {
        "id": 1002,
        "name": "A - B",
        "participants": {"home": "A", "away": "B"},
        "startTime": "2026-10-02T14:00:00.000Z",
        "classification": "prematch",
        "competition": {"id": 1, "name": "Test", "countryCode": "TR"},
        "markets": [
            {
                "name": "Maç Sonucu",
                "status": {"code": "OPEN"},
                "outcomes": [
                    {"name": "1", "odd": 2.5, "playable": False, "isSentinelOdd": False},
                    {"name": "2", "odd": 3.0, "playable": True,  "isSentinelOdd": False},
                ],
            }
        ],
    }
    result = normalize_xiddaa_event(ev, CAPTURED_AT)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert "playable" in result.rejected[0].reason.lower()


# ────────────────────────────────────────────────────────────────────────────────
# TEST 9: Duplicate snapshot → handled (not duplicated in accepted)
# ────────────────────────────────────────────────────────────────────────────────

def test_duplicate_snapshot_handled():
    """Same record captured twice in the same snapshot window → only one retained."""
    rec = _make_normalized_record()
    records = [rec, rec]  # exact duplicate (same object)

    unique, duplicates = deduplicate_records(records, window_minutes=10)
    assert len(unique) == 1
    assert len(duplicates) == 1


def test_duplicate_detection_same_selection():
    """Two records with same (provider, bookmaker, event, market, selection) in window → deduplicated."""
    rec1 = _make_normalized_record(odds_decimal=1.80, captured_at=CAPTURED_AT)
    rec2 = _make_normalized_record(odds_decimal=1.81,
                                   captured_at=CAPTURED_AT.replace(minute=5))  # 5 min apart

    unique, duplicates = deduplicate_records([rec1, rec2], window_minutes=10)
    assert len(unique) == 1    # First wins
    assert len(duplicates) == 1


# ────────────────────────────────────────────────────────────────────────────────
# TEST 10: Different timestamp → retained (history)
# ────────────────────────────────────────────────────────────────────────────────

def test_different_timestamp_retained():
    """Same (provider, bookmaker, event, market, selection) but >window apart → both retained."""

    rec1 = _make_normalized_record(odds_decimal=1.80, captured_at=CAPTURED_AT)
    rec2 = _make_normalized_record(
        odds_decimal=1.75,
        captured_at=CAPTURED_AT + timedelta(hours=3)
    )

    unique, duplicates = deduplicate_records([rec1, rec2], window_minutes=10)
    assert len(unique) == 2    # Both retained as history
    assert len(duplicates) == 0


# ────────────────────────────────────────────────────────────────────────────────
# TEST 11: Same teams, uncertain match → UNMATCHED (no auto-inference)
# ────────────────────────────────────────────────────────────────────────────────

def test_uncertain_match_not_auto_matched():
    """Teams with different kickoff dates must NOT be matched (UNMATCHED)."""
    # PropLine: Arsenal vs Leeds on Oct 10
    pl_rec = _make_normalized_record(
        provider="propline",
        home_team="Arsenal",
        away_team="Leeds United",
        kickoff="2026-10-10T14:00:00Z",
    )

    # Xiddaa: Arsenal vs Leeds on a DIFFERENT date (Oct 17)
    xi_rec = _make_normalized_record(
        provider="xiddaa",
        bookmaker="xiddaa",
        event_id="xi_ev_999",
        home_team="Arsenal",
        away_team="Leeds",
        kickoff="2026-10-17T14:00:00Z",
    )

    matches = reconcile_providers([pl_rec], [xi_rec])
    assert len(matches) == 1
    assert matches[0].match_method == "UNMATCHED"
    assert matches[0].confidence == 0.0


def test_exact_match_reconciled():
    """Exact same team names and date → matched with confidence=1.0."""
    pl_rec = _make_normalized_record(
        provider="propline",
        home_team="Galatasaray",
        away_team="Kasımpaşa",
        kickoff="2026-10-09T17:00:00Z",
    )
    xi_rec = _make_normalized_record(
        provider="xiddaa",
        bookmaker="xiddaa",
        event_id="xi_ev_100",
        home_team="Galatasaray",
        away_team="Kasımpaşa",
        kickoff="2026-10-09T17:00:00Z",
    )

    matches = reconcile_providers([pl_rec], [xi_rec])
    assert len(matches) == 1
    assert matches[0].match_method == "exact"
    assert matches[0].confidence == 1.0
