"""Unit and integration tests for TASK-008 Phase 1A: Global Football Discovery & Registry."""

from sports_engine.collectors.global_discovery import (
    GlobalDiscoveryEngine,
    build_canonical_competition_id,
    detect_competition_type,
    map_country_code_to_name,
)
from sports_engine.models.football_markets import FootballMarketEngine


def test_global_competition_discovery():
    """Verify that GlobalDiscoveryEngine runs and discovers hundreds of competitions across providers."""
    engine = GlobalDiscoveryEngine()
    competitions, fixtures, metrics = engine.build_registry()

    assert len(competitions) > 50, f"Expected > 50 competitions, got {len(competitions)}"
    assert metrics["global_competitions_discovered"] == len(competitions)
    assert metrics["canonical_competitions"] == len(competitions)
    assert metrics["data_available"] > 0
    assert metrics["betting_market_available"] > 0


def test_multiple_countries():
    """Verify that multiple countries across continents are represented in the registry."""
    engine = GlobalDiscoveryEngine()
    competitions, _, metrics = engine.build_registry()

    countries = {c.country for c in competitions}
    assert metrics["countries_count"] >= 10, f"Expected >= 10 countries, got {len(countries)}"

    # Must contain major football nations
    required_countries = ["England", "Spain", "Germany", "Italy", "France", "Netherlands", "Turkey"]
    for country in required_countries:
        assert country in countries, f"Expected {country} in discovered countries"


def test_competition_normalization():
    """Verify canonical naming and normalization rules."""
    assert build_canonical_competition_id("England", "Premier League") == "england_premier_league"
    assert build_canonical_competition_id("GB", "İngiltere Premier Lig") == "england_premier_league"
    assert build_canonical_competition_id("Spain", "La Liga") == "spain_la_liga"
    assert build_canonical_competition_id("ES", "İspanya La Liga") == "spain_la_liga"
    assert build_canonical_competition_id("Germany", "Bundesliga") == "germany_bundesliga"
    assert build_canonical_competition_id("Italy", "Serie A") == "italy_serie_a"
    assert build_canonical_competition_id("Turkey", "Süper Lig") == "turkey_super_lig"

    # Type detection
    c_type, gender = detect_competition_type("Ziraat Türkiye Kupası")
    assert c_type == "Cup"
    assert gender == "Men"

    c_type_u21, _ = detect_competition_type("UEFA U21 Championship")
    assert c_type_u21 == "Youth"

    c_type_w, gender_w = detect_competition_type("Kadın Futbol Süper Ligi")
    assert gender_w == "Women"


def test_provider_reconciliation():
    """Verify cross-provider matching on major leagues."""
    engine = GlobalDiscoveryEngine()
    competitions, _, metrics = engine.build_registry()

    comp_dict = {c.competition_id: c for c in competitions}

    # England Premier League should be matched across multiple providers
    epl = comp_dict.get("england_premier_league")
    assert epl is not None
    provider_count = sum([epl.providers.api_football, epl.providers.bzzoiro, epl.providers.prop_line, epl.providers.xiddaa])
    assert provider_count >= 2, f"Expected EPL in at least 2 providers, found {provider_count}"

    assert metrics["cross_provider_matches"] > 0


def test_fixture_deduplication():
    """Verify fixture registry creation and canonical deduplication."""
    engine = GlobalDiscoveryEngine()
    _, fixtures, metrics = engine.build_registry()

    assert metrics["canonical_fixtures"] == len(fixtures)
    fixture_ids = [f.fixture_id for f in fixtures]
    assert len(fixture_ids) == len(set(fixture_ids)), "Fixture IDs must be unique (no duplicates)"


def test_turkey_is_not_only_universe():
    """Critical test: Verify Turkey is NOT the only country and represents a fraction of global competitions."""
    engine = GlobalDiscoveryEngine()
    competitions, _, _ = engine.build_registry()

    turkey_comps = [c for c in competitions if c.country == "Turkey"]
    non_turkey_comps = [c for c in competitions if c.country != "Turkey"]

    assert len(non_turkey_comps) > len(turkey_comps), (
        f"Non-Turkey competitions ({len(non_turkey_comps)}) must exceed Turkey competitions ({len(turkey_comps)})"
    )
    # Check that legal market distinction is maintained
    # If not verified in official iddaa feed, it must remain UNKNOWN
    for c in competitions:
        if not c.providers.xiddaa:
            assert c.betting.turkey_legal_status == "UNKNOWN"


def test_existing_task007_compatibility():
    """Ensure TASK-007 football_markets.py continues to work seamlessly."""
    market_engine = FootballMarketEngine(lambda_home=1.5, lambda_away=1.2)
    derived = market_engine.get_full_market_suite()

    assert "1x2" in derived
    assert "totals" in derived
    assert "btts" in derived
    assert "top_correct_scores" in derived
    assert "ht_ft" in derived
    assert abs(derived["1x2"]["HOME"] + derived["1x2"]["DRAW"] + derived["1x2"]["AWAY"] - 1.0) < 1e-3
