"""Test canonical ID generation, exact normalization, and RapidFuzz fallback resolution."""

from datetime import UTC, datetime

from sports_engine.normalization.canonical import (
    build_canonical_fixture_id,
    build_canonical_league_id,
    build_canonical_player_id,
    build_canonical_team_id,
    normalize_entity_name,
)
from sports_engine.normalization.resolution import EntityResolver


def test_canonical_id_builders():
    # League
    league_id = build_canonical_league_id("Turkey", "Süper Lig")
    assert league_id == "turkey_super_lig"

    # Team
    team_id = build_canonical_team_id("Galatasaray Spor Kulübü")
    assert team_id == "galatasaray"

    # Player
    player_id = build_canonical_player_id("Mauro Emanuel Icardi", canonical_team_id="galatasaray")
    assert player_id == "galatasaray_mauro_emanuel_icardi"

    # Fixture
    kickoff = datetime(2026, 10, 28, 17, 0, 0, tzinfo=UTC)
    fixture_id = build_canonical_fixture_id(
        canonical_league_id="tr_super_lig",
        season="2024-2025",
        home_team_id="galatasaray",
        away_team_id="besiktas",
        event_time=kickoff,
    )
    assert fixture_id == "tr_super_lig_2024_2025_20261028_galatasaray_vs_besiktas"


def test_exact_normalization_turkish_characters():
    assert normalize_entity_name("Fenerbahçe SK") == "fenerbahce"
    assert normalize_entity_name("Beşiktaş Jimnastik Kulübü") == "besiktas"
    assert normalize_entity_name("İstanbul Başakşehir FK") == "istanbul_basaksehir"
    assert normalize_entity_name("Göztepe A.Ş.") == "goztepe"
    assert normalize_entity_name("Çaykur Rizespor") == "caykur_rizespor"


def test_entity_resolver_exact_match():
    resolver = EntityResolver()
    resolver.register_canonical_entity(
        canonical_id="galatasaray",
        display_name="Galatasaray SK",
        aliases=["Galatasaray", "Cimbom"],
    )

    mapping = resolver.resolve(
        raw_name="Galatasaray SK",
        source="livescore_json",
        source_entity_id="src_team_101",
    )
    assert mapping.canonical_id == "galatasaray"
    assert mapping.confidence == 1.0
    assert mapping.verified is True


def test_entity_resolver_rapidfuzz_fallback_not_auto_verified():
    resolver = EntityResolver(fuzzy_threshold=70.0)
    resolver.register_canonical_entity(
        canonical_id="fenerbahce",
        display_name="Fenerbahce",
    )

    # Slight misspelling or alternate casing
    mapping = resolver.resolve(
        raw_name="Fenerbahche Spor",
        source="propline",
        source_entity_id="prop_404",
    )
    assert mapping.canonical_id == "fenerbahce"
    assert 0.70 <= mapping.confidence < 1.0
    # HARD CONSTRAINT: Do not automatically mark fuzzy matches as verified!
    assert mapping.verified is False


def test_entity_resolver_unresolved_fallback():
    resolver = EntityResolver(fuzzy_threshold=80.0)
    resolver.register_canonical_entity("trabzonspor", "Trabzonspor")

    mapping = resolver.resolve(
        raw_name="Real Madrid CF",
        source="random_feed",
        source_entity_id="ext_999",
    )
    assert mapping.confidence < 0.80
    assert mapping.verified is False
