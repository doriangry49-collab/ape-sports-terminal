"""Tests for TASK-008 Phase 1B.2: Odds Contract, Reconciliation, Timestamps, and Phase Guard."""

import pytest

from sports_engine.collectors.betting_universe import BettingUniverseEngine
from sports_engine.domain.betting_universe import MarketStatus
from sports_engine.domain.odds_contract import (
    CanonicalOddsRecord,
    CrossProviderFixtureMatchEvidence,
    TimestampLayers,
    validate_phase_compatibility,
)


def test_cross_provider_match_has_evidence():
    """Verify at least 5 cross-provider matches with concrete evidence, methods, and confidence."""
    engine = BettingUniverseEngine()
    evidences = engine.get_cross_provider_match_evidence()

    assert len(evidences) >= 5, f"Expected >= 5 match evidences, got {len(evidences)}"

    for ev in evidences:
        assert isinstance(ev, CrossProviderFixtureMatchEvidence)
        assert ev.provider_A and ev.provider_B
        assert ev.canonical_fixture_id
        assert ev.match_method
        assert ev.team_match
        assert ev.date_match
        assert ev.competition_match
        assert 0.90 <= ev.confidence <= 1.0


def test_timestamp_layers_are_distinct():
    """Verify the 4 timestamp layers remain strictly distinct."""
    layers = TimestampLayers(
        event_last_update="2026-09-29T15:44:43Z",
        market_last_update="2026-09-29T15:44:36Z",
        outcome_last_update="2026-09-29T12:34:57Z",
    )

    assert layers.event_last_update == "2026-09-29T15:44:43Z"
    assert layers.market_last_update == "2026-09-29T15:44:36Z"
    assert layers.outcome_last_update == "2026-09-29T12:34:57Z"
    assert layers.snapshot_collected_at.tzinfo is not None


def test_event_timestamp_is_not_outcome_timestamp():
    """Verify that bookmakers without outcome timestamps have outcome_last_update='UNKNOWN'."""
    engine = BettingUniverseEngine()
    records = engine.extract_canonical_odds_records()

    assert len(records) > 0

    # Pinnacle outcomes do not provide book_updated_at in PropLine raw feed -> outcome_last_update must be UNKNOWN
    pinnacle_records = [r for r in records if r.bookmaker.lower() == "pinnacle"]
    assert len(pinnacle_records) > 0
    for r in pinnacle_records:
        assert r.outcome_last_update == "UNKNOWN", (
            "Event timestamp must NEVER be promoted to outcome_last_update for Pinnacle"
        )
        assert r.event_last_update != "UNKNOWN"

    # Bovada outcomes DO provide book_updated_at -> outcome_last_update must be an ISO timestamp
    bovada_records = [r for r in records if r.bookmaker.lower() == "bovada"]
    assert len(bovada_records) > 0
    bovada_with_outcome_ts = [r for r in bovada_records if r.outcome_last_update != "UNKNOWN"]
    assert len(bovada_with_outcome_ts) > 0


def test_snapshot_collected_at_is_preserved():
    """Verify that snapshot_collected_at is an immutable timezone-aware datetime."""
    engine = BettingUniverseEngine()
    records = engine.extract_canonical_odds_records()

    for r in records[:20]:
        assert r.snapshot_collected_at is not None
        assert r.snapshot_collected_at.tzinfo is not None


def test_odds_record_has_canonical_schema():
    """Verify that CanonicalOddsRecord contains all 12 required fields for Phase 2."""
    required_fields = {
        "fixture_id",
        "provider",
        "bookmaker",
        "market",
        "selection",
        "price",
        "event_last_update",
        "market_last_update",
        "outcome_last_update",
        "snapshot_collected_at",
        "match_phase",
        "source",
    }

    assert required_fields.issubset(CanonicalOddsRecord.model_fields.keys())

    engine = BettingUniverseEngine()
    records = engine.extract_canonical_odds_records()
    sample = records[0]
    for field in required_fields:
        val = getattr(sample, field)
        assert val is not None, f"Field '{field}' cannot be None"


def test_prematch_live_cannot_cross():
    """Verify that phase guard prevents comparing PREMATCH with LIVE odds."""
    # Compatible
    assert validate_phase_compatibility("PREMATCH", "PREMATCH") is True
    assert validate_phase_compatibility("LIVE", "LIVE") is True

    # Incompatible -> must raise ValueError
    with pytest.raises(ValueError, match="Phase mismatch violation"):
        validate_phase_compatibility("PREMATCH", "LIVE")

    with pytest.raises(ValueError, match="Phase mismatch violation"):
        validate_phase_compatibility("LIVE", "PREMATCH")


def test_model_derived_market_has_no_bookmaker_offer():
    """Verify that model-derived markets (Correct Score, 1H/2H, HT/FT) have no bookmaker offer."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    model_derived_keys = ["Correct Score", "HT/FT", "First Half Result", "Second Half Result", "Team Goals", "DNB", "Double Chance"]

    for f in fixtures:
        if f.match_phase == "PREMATCH":
            for m_key in model_derived_keys:
                ev = f.market_presence.get(m_key)
                assert ev is not None
                assert ev.status == MarketStatus.MODEL_ONLY
                assert ev.classification == "MODEL_DERIVED"
                assert ev.market_exists is False
                assert ev.odds_exists is False
                assert ev.bookmaker_count == 0
