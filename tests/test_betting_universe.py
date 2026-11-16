"""Unit and integration tests for TASK-008 Phase 1B: Betting Universe & Market Coverage."""

from sports_engine.collectors.betting_universe import (
    STANDARD_MARKETS,
    BettingUniverseEngine,
)
from sports_engine.domain.betting_universe import MarketStatus


def test_betting_universe_funnel():
    """Verify that 561 catalog competitions narrow down cleanly through the funnel to active fixtures."""
    engine = BettingUniverseEngine()
    active_fixtures, funnel = engine.build_active_fixture_registry()

    assert funnel["catalog_competitions"] == 561
    assert funnel["total_active_fixtures"] > 0
    assert funnel["competitions_with_active_fixtures"] <= funnel["catalog_competitions"]
    assert funnel["fixtures_with_active_odds"] > 0
    assert len(active_fixtures) == funnel["total_active_fixtures"]


def test_xiddaa_legal_status_recheck():
    """Verify that catalog presence alone does NOT grant VERIFIED legal status.

    Only fixtures with actual event records in xiddaa event feeds get VERIFIED.
    Other active fixtures must remain UNKNOWN.
    """
    engine = BettingUniverseEngine()
    active_fixtures, funnel = engine.build_active_fixture_registry()

    # There should be fixtures marked as UNKNOWN because they don't have concrete fixture-level evidence
    unknown_fixtures = [f for f in active_fixtures if f.turkey_legal_status == "UNKNOWN"]
    assert len(unknown_fixtures) > 0, "Expected at least some fixtures with UNKNOWN legal status"
    assert funnel["fixtures_unknown_legal_status"] == len(unknown_fixtures)

    # For any fixture with UNKNOWN legal status, fixture_evidence_present must be False
    for f in unknown_fixtures:
        assert f.fixture_evidence_present is False


def test_market_taxonomy_status():
    """Verify that all 18 standard markets receive an exact MarketStatus enum value."""
    engine = BettingUniverseEngine()
    active_fixtures, funnel = engine.build_active_fixture_registry()

    assert len(STANDARD_MARKETS) == 18

    valid_statuses = {
        MarketStatus.OFFERED_AND_MODELLED,
        MarketStatus.MODEL_ONLY,
        MarketStatus.OFFERED_BUT_UNMODELLED,
        MarketStatus.OFFERED,
        MarketStatus.UNKNOWN,
    }

    for f in active_fixtures:
        assert len(f.market_presence) == 18
        for _m_name, ev in f.market_presence.items():
            assert ev.status in valid_statuses
            # If market is modelled and offered, status must be OFFERED_AND_MODELLED
            if ev.market_exists and ev.model_exists:
                assert ev.status == MarketStatus.OFFERED_AND_MODELLED
            # If market is modelled but not offered, status must be MODEL_ONLY
            elif not ev.market_exists and ev.model_exists:
                assert ev.status == MarketStatus.MODEL_ONLY
            # If market is offered but not modelled, status must be OFFERED_BUT_UNMODELLED
            elif ev.market_exists and not ev.model_exists:
                assert ev.status == MarketStatus.OFFERED_BUT_UNMODELLED


def test_odds_separation_rule():
    """Verify that market_exists, odds_exists, and model_exists are strictly separated."""
    engine = BettingUniverseEngine()
    active_fixtures, _ = engine.build_active_fixture_registry()

    for f in active_fixtures:
        for ev in f.market_presence.values():
            assert isinstance(ev.market_exists, bool)
            assert isinstance(ev.odds_exists, bool)
            assert isinstance(ev.model_exists, bool)


def test_coverage_score_bounds():
    """Verify market_coverage_score is between 0.0 and 1.0."""
    engine = BettingUniverseEngine()
    active_fixtures, _ = engine.build_active_fixture_registry()

    for f in active_fixtures:
        assert 0.0 <= f.market_coverage_score <= 1.0
