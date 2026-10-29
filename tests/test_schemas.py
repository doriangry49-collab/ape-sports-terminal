"""Test canonical domain schemas validation and constraints."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sports_engine.domain.schemas import (
    Bookmaker,
    Fixture,
    League,
    Market,
    MatchResult,
    ModelPrediction,
    OddsSnapshot,
    Player,
    Team,
    is_closing_line,
)


def test_league_schema():
    league = League(
        canonical_league_id="tr_super_lig",
        name="Trendyol Süper Lig",
        country="Turkey",
    )
    assert league.canonical_league_id == "tr_super_lig"
    assert league.created_at.tzinfo is not None


def test_team_schema():
    team = Team(
        canonical_team_id="galatasaray",
        canonical_league_id="tr_super_lig",
        name="Galatasaray SK",
        short_name="GS",
    )
    assert team.canonical_team_id == "galatasaray"
    assert team.country == "Turkey"


def test_player_schema():
    player = Player(
        canonical_player_id="mauro_icardi",
        canonical_team_id="galatasaray",
        name="Mauro Icardi",
        position="ST",
    )
    assert player.name == "Mauro Icardi"


def test_bookmaker_and_market_schema():
    bookmaker = Bookmaker(bookmaker_id="iddaa", name="İddaa", is_active=True)
    assert bookmaker.bookmaker_id == "iddaa"

    market = Market(market_id="1x2", market_type="MATCH_ODDS", description="Full time 1X2")
    assert market.market_id == "1x2"


def test_fixture_time_sensitive_schema():
    now = datetime.now(UTC)
    kickoff = now + timedelta(days=2)

    fixture = Fixture(
        canonical_fixture_id="tr_super_lig_2024_2025_20261028_galatasaray_vs_besiktas",
        canonical_league_id="tr_super_lig",
        season="2024-2025",
        round="10",
        home_team_id="galatasaray",
        away_team_id="besiktas",
        status="SCHEDULED",
        event_time=kickoff,
        source_time=now - timedelta(minutes=5),
        fetched_at=now,
        ingested_at=now + timedelta(seconds=1),
        available_at=now + timedelta(seconds=2),
    )
    assert fixture.event_time == kickoff
    assert fixture.ingested_at.tzinfo is not None


def test_odds_snapshot_and_closing_line_derivation():
    event_time = datetime(2026, 10, 28, 17, 0, 0, tzinfo=UTC)
    # Quote from 2 hours before match -> not closing line
    early_quote = event_time - timedelta(hours=2)
    # Quote from 3 minutes before match -> closing line (within default 300s window)
    closing_quote = event_time - timedelta(minutes=3)

    odds_early = OddsSnapshot(
        odds_id="odds_001",
        fixture_id="fixture_001",
        bookmaker_id="iddaa",
        market_type="1X2",
        selection="HOME",
        decimal_odds=1.95,
        source="iddaa_feed",
        event_time=event_time,
        source_time=early_quote,
        fetched_at=early_quote,
        ingested_at=early_quote + timedelta(seconds=1),
    )
    # is_closing_line must NOT be a model field
    assert "is_closing_line" not in odds_early.model_dump()
    assert is_closing_line(odds_early, threshold_seconds=300) is False

    odds_closing = OddsSnapshot(
        odds_id="odds_002",
        fixture_id="fixture_001",
        bookmaker_id="iddaa",
        market_type="1X2",
        selection="HOME",
        decimal_odds=1.85,
        source="iddaa_feed",
        event_time=event_time,
        source_time=closing_quote,
        fetched_at=closing_quote,
        ingested_at=closing_quote + timedelta(seconds=1),
    )
    assert is_closing_line(odds_closing, threshold_seconds=300) is True


def test_match_result_schema():
    event_time = datetime(2026, 10, 28, 17, 0, 0, tzinfo=UTC)
    res_time = event_time + timedelta(hours=2)

    result = MatchResult(
        result_id="res_001",
        fixture_id="fixture_001",
        home_score=2,
        away_score=1,
        halftime_home_score=1,
        halftime_away_score=0,
        status="FINISHED",
        event_time=event_time,
        source_time=res_time,
        fetched_at=res_time + timedelta(seconds=10),
        ingested_at=res_time + timedelta(seconds=11),
    )
    assert result.home_score == 2
    assert result.away_score == 1


def test_model_prediction_schema():
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=15)

    prediction = ModelPrediction(
        prediction_id="pred_20261028_001",
        fixture_id="tr_super_lig_2024_2025_20261028_galatasaray_vs_besiktas",
        generated_at=now,
        data_cutoff=cutoff,
        model_name="PoissonGoalsModel",
        model_version="0.1.0",
        market_type="1X2",
        selection="HOME",
        predicted_probability=0.55,
        fair_odds=1.818,
    )
    assert prediction.predicted_probability == 0.55
    assert prediction.fair_odds == 1.818
    assert prediction.data_cutoff < prediction.generated_at

    # Probability must be in [0.0, 1.0]
    with pytest.raises(ValidationError):
        ModelPrediction(
            prediction_id="pred_err",
            fixture_id="fix_err",
            generated_at=now,
            data_cutoff=cutoff,
            model_name="PoissonGoalsModel",
            model_version="0.1.0",
            market_type="1X2",
            selection="HOME",
            predicted_probability=1.5,  # Invalid!
            fair_odds=0.66,
        )
