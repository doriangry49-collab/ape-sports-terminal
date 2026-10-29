"""Unit tests for NBA Elo baseline rating model and walk-forward backtest."""

import pytest

from sports_engine.backtest.nba_backtest import NBAWalkForwardBacktest
from sports_engine.models.nba_elo import NBAEloModel


@pytest.fixture
def sample_nba_games():
    """Synthetic chronological NBA games."""
    teams = ["celtics", "lakers", "warriors", "heat"]
    games = []
    for i in range(30):
        h = teams[i % len(teams)]
        a = teams[(i + 1) % len(teams)]
        h_score = 110 + (i % 15)
        a_score = 105 + ((i * 3) % 15)
        games.append({
            "game_id": f"g_{i}",
            "event_date": f"2024-01-{(i % 28) + 1:02d}T19:00:00Z",
            "home_team": h,
            "away_team": a,
            "home_team_raw": h.title(),
            "away_team_raw": a.title(),
            "home_score": h_score,
            "away_score": a_score,
            "home_won": 1 if h_score > a_score else 0,
        })
    return games


def test_nba_elo_model_probabilities_and_odds(sample_nba_games):
    """Verify NBA Elo model produces valid complementary probabilities and fair odds."""
    model = NBAEloModel().fit(sample_nba_games)
    pred = model.predict_game("celtics", "lakers")

    assert pytest.approx(pred.home_probability + pred.away_probability, abs=1e-3) == 1.0
    assert pred.fair_home_odds > 1.0
    assert pred.fair_away_odds > 1.0
    assert pytest.approx(pred.fair_home_odds, abs=0.05) == round(1.0 / pred.home_probability, 2)
    assert pytest.approx(pred.fair_away_odds, abs=0.05) == round(1.0 / pred.away_probability, 2)


def test_nba_unfitted_raises():
    """Model must raise error if predict_game called before fit."""
    model = NBAEloModel()
    with pytest.raises(RuntimeError):
        model.predict_game("celtics", "lakers")


def test_nba_walk_forward_backtest(sample_nba_games):
    """Verify NBA walk-forward evaluation produces valid bounded metrics."""
    min_train = 10
    bt = NBAWalkForwardBacktest(min_train_size=min_train)
    summary, records = bt.run(sample_nba_games)

    expected_count = len(sample_nba_games) - min_train
    assert summary.total_test_games == expected_count
    assert len(records) == expected_count
    assert 0.0 <= summary.brier_score_binary <= 1.0
    assert summary.log_loss_mean >= 0.0
    assert 0.0 <= summary.accuracy_percent <= 100.0
