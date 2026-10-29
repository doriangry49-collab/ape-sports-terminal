"""Test timezone awareness enforcement across time-sensitive models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sports_engine.domain.schemas import Fixture, ModelPrediction, OddsSnapshot


def test_naive_datetime_rejected():
    naive_dt = datetime(2026, 10, 28, 19, 0, 0)  # No tzinfo!

    with pytest.raises(ValidationError) as exc:
        Fixture(
            canonical_fixture_id="fix_tz_fail",
            canonical_league_id="tr_super_lig",
            season="2024-2025",
            home_team_id="galatasaray",
            away_team_id="fenerbahce",
            event_time=naive_dt,
            fetched_at=datetime.now(UTC),
            ingested_at=datetime.now(UTC),
        )
    assert "timezone-aware" in str(exc.value)


def test_prediction_naive_datetime_rejected():
    naive_dt = datetime(2026, 10, 28, 12, 0, 0)
    aware_dt = datetime.now(UTC)

    with pytest.raises(ValidationError) as exc:
        ModelPrediction(
            prediction_id="pred_tz_fail",
            fixture_id="fix_001",
            generated_at=naive_dt,
            data_cutoff=aware_dt,
            model_name="TestModel",
            model_version="1.0",
            market_type="1X2",
            selection="DRAW",
            predicted_probability=0.3,
            fair_odds=3.33,
        )
    assert "timezone-aware" in str(exc.value)


def test_timezone_aware_accepted():
    aware_dt = datetime(2026, 10, 28, 19, 0, 0, tzinfo=UTC)
    now = datetime.now(UTC)

    odds = OddsSnapshot(
        odds_id="odds_tz_ok",
        fixture_id="fix_001",
        bookmaker_id="iddaa",
        market_type="1X2",
        selection="AWAY",
        decimal_odds=3.20,
        source="test_source",
        event_time=aware_dt,
        fetched_at=now,
        ingested_at=now,
    )
    assert odds.event_time.tzinfo is not None
    assert odds.fetched_at.tzinfo is not None
