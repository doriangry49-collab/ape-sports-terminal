"""Unit tests for multi-sport discovery and model eligibility classification."""

from sports_engine.collectors.discovery import categorize_sport, discover_all_sports


def test_categorize_sport_mapping():
    """Verify standard mapping of sport keys into broader athletic families."""
    assert categorize_sport("soccer_turkey_super_lig") == "Football"
    assert categorize_sport("soccer_epl") == "Football"
    assert categorize_sport("basketball_nba") == "Basketball"
    assert categorize_sport("baseball_mlb") == "Baseball"
    assert categorize_sport("tennis") == "Tennis"
    assert categorize_sport("hockey_nhl") == "Hockey"
    assert categorize_sport("football_nfl") == "American Football"
    assert categorize_sport("mma_ufc") == "Combat Sports"


def test_discover_all_sports_model_status():
    """Ensure Süper Lig has MODEL_AVAILABLE while unsupported sports have NO_MODEL_YET."""
    sports = discover_all_sports(force_refresh=False)
    assert len(sports) >= 50

    super_lig = next((s for s in sports if s["sport_key"] == "soccer_turkey_super_lig"), None)
    assert super_lig is not None
    assert super_lig["model_status"] == "MODEL_AVAILABLE"
    assert super_lig["model_name"] == "poisson_bivariate_baseline v0.1.0"

    mlb = next((s for s in sports if s["sport_key"] == "baseball_mlb"), None)
    assert mlb is not None
    assert mlb["model_status"] == "NO_MODEL_YET"
    assert mlb["model_name"] is None
