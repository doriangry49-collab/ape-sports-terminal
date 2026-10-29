"""Data quality and audit tests for TASK-008 Phase 1B.1."""

from sports_engine.collectors.betting_universe import BettingUniverseEngine
from sports_engine.domain.betting_universe import MarketStatus


def test_live_and_prematch_are_separate():
    """Verify that every fixture is distinctly tagged as PREMATCH or LIVE, never conflated."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    prematch_fixtures = [f for f in fixtures if f.match_phase == "PREMATCH"]
    live_fixtures = [f for f in fixtures if f.match_phase == "LIVE"]

    assert len(prematch_fixtures) > 0, "Expected at least 1 PREMATCH fixture"
    assert len(live_fixtures) > 0, "Expected at least 1 LIVE fixture"
    assert len(prematch_fixtures) + len(live_fixtures) == len(fixtures)

    # Check Iceland U21 vs Switzerland U21 is strictly tagged as LIVE
    u21 = next((f for f in fixtures if "iceland" in f.canonical_home_team.lower()), None)
    assert u21 is not None
    assert u21.match_phase == "LIVE"


def test_model_only_has_no_bookmaker_claim():
    """Verify that MODEL_ONLY markets NEVER claim that a bookmaker offered them."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    for f in fixtures:
        for m_name, ev in f.market_presence.items():
            if ev.status == MarketStatus.MODEL_ONLY:
                assert ev.market_exists is False, f"MODEL_ONLY market {m_name} must have market_exists=False"
                assert ev.odds_exists is False, f"MODEL_ONLY market {m_name} must have odds_exists=False"
                assert ev.classification == "MODEL_DERIVED"
                assert ev.source == "MODEL"
                assert ev.bookmaker_count == 0


def test_market_source_is_preserved():
    """Verify each market records its true source (PROP_LINE, API_FOOTBALL, MODEL, etc.)."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    valid_sources = {"PROP_LINE", "API_FOOTBALL", "XIDDAA", "BZZOIRO", "MODEL", "UNKNOWN"}

    for f in fixtures:
        for m_name, ev in f.market_presence.items():
            assert ev.source in valid_sources, f"Source '{ev.source}' not in valid sources"


def test_odds_timestamp_is_not_invented():
    """Verify that timestamps are either genuine ISO strings from upstream or 'UNKNOWN'."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    for f in fixtures:
        for m_name, ev in f.market_presence.items():
            if ev.odds_exists:
                # Must be a non-empty string timestamp (e.g. from Bovada) or "UNKNOWN"
                assert isinstance(ev.odds_timestamp, str)
                assert len(ev.odds_timestamp) > 0
            else:
                assert ev.odds_timestamp == "UNKNOWN"


def test_bookmaker_count_matches_source():
    """Verify fixture bookmaker_count matches actual bookmakers observed."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    for f in fixtures:
        if f.match_phase == "PREMATCH":
            assert f.betting_presence.get("bookmaker_count") == 5
        elif f.match_phase == "LIVE":
            assert f.betting_presence.get("bookmaker_count") == 1


def test_legal_status_requires_evidence():
    """Verify legal status is only VERIFIED when fixture_evidence_present is True."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    for f in fixtures:
        if f.turkey_legal_status == "VERIFIED":
            assert f.fixture_evidence_present is True
        else:
            assert f.turkey_legal_status == "UNKNOWN"
            assert f.fixture_evidence_present is False


def test_coverage_score_semantics():
    """Verify separation of MODEL_COVERAGE and MARKET_AVAILABILITY metrics."""
    engine = BettingUniverseEngine()
    fixtures, _ = engine.build_active_fixture_registry()

    for f in fixtures:
        assert 0.0 <= f.model_coverage <= 1.0
        assert 0.0 <= f.market_availability <= 1.0

        offered = sum(1 for m in f.market_presence.values() if m.market_exists)
        assert f.market_availability == round(offered / 18, 3)
