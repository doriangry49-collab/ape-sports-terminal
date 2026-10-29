"""Unit tests for baseline Poisson football model and MVP prediction pipeline."""

from datetime import UTC, datetime

import pytest

from sports_engine.features.dataset import fetch_or_load_historical_matches
from sports_engine.models.poisson import PoissonGoalModel
from sports_engine.normalization.canonical import normalize_entity_name


@pytest.fixture
def sample_matches():
    """Synthetic match history for testing model mathematics."""
    return [
        {"home_team": "team_a", "away_team": "team_b", "home_score": 2, "away_score": 1, "event_date": "2026-09-01T15:00:00Z"},
        {"home_team": "team_b", "away_team": "team_c", "home_score": 0, "away_score": 0, "event_date": "2026-09-08T15:00:00Z"},
        {"home_team": "team_c", "away_team": "team_a", "home_score": 1, "away_score": 3, "event_date": "2026-09-15T15:00:00Z"},
        {"home_team": "team_a", "away_team": "team_c", "home_score": 4, "away_score": 0, "event_date": "2026-09-22T15:00:00Z"},
        {"home_team": "team_b", "away_team": "team_a", "home_score": 1, "away_score": 2, "event_date": "2026-09-29T15:00:00Z"},
    ]


def test_poisson_unfitted_raises():
    """Predicting before fitting must raise RuntimeError."""
    model = PoissonGoalModel()
    with pytest.raises(RuntimeError):
        model.predict_match("team_a", "team_b")


def test_poisson_probability_sum_and_fair_odds(sample_matches):
    """Model probabilities must sum to 1.0 and fair odds must equal 1/p."""
    model = PoissonGoalModel().fit(sample_matches)
    pred = model.predict_match("team_a", "team_b")

    total_prob = pred.home_probability + pred.draw_probability + pred.away_probability
    assert pytest.approx(total_prob, abs=1e-3) == 1.0

    # Stronger away team (team_a won 3-1 away and 2-1 away)
    pred_reverse = model.predict_match("team_b", "team_a")
    assert pred_reverse.away_probability > pred_reverse.home_probability

    # Fair odds verification
    assert pytest.approx(pred.fair_home_odds, abs=0.05) == round(1.0 / pred.home_probability, 2)
    assert pytest.approx(pred.fair_draw_odds, abs=0.05) == round(1.0 / pred.draw_probability, 2)
    assert pytest.approx(pred.fair_away_odds, abs=0.05) == round(1.0 / pred.away_probability, 2)


def test_data_cutoff_anti_leakage(sample_matches, tmp_path):
    """Matches strictly after data_cutoff must be excluded."""
    import json

    cache_file = tmp_path / "test_events.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(sample_matches, f)

    # Cutoff set to Sept 10: only matches on Sept 01 and Sept 08 should remain
    cutoff = datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)
    filtered = fetch_or_load_historical_matches(
        limit=50,
        data_cutoff=cutoff,
        cache_path=cache_file,
    )

    assert len(filtered) == 2
    for m in filtered:
        event_dt = datetime.fromisoformat(m["event_date"])
        assert event_dt <= cutoff


def test_turkish_entity_normalization_consistency():
    """Verify consistent canonical team names for Süper Lig matchup."""
    home_norm = normalize_entity_name("Çaykur Rizespor")
    away_norm = normalize_entity_name("Fenerbahçe")
    assert home_norm == "caykur_rizespor"
    assert away_norm == "fenerbahce"

    # Variations
    assert normalize_entity_name("Caykur Rizespor") == "caykur_rizespor"
    assert normalize_entity_name("Fenerbahce") == "fenerbahce"
    assert normalize_entity_name("Fenerbahce SK") == "fenerbahce"
