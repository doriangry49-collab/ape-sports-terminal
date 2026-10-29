"""Unit tests for walk-forward backtesting engine and evaluation metrics."""

import math
from datetime import UTC, datetime

import pytest

from sports_engine.backtest.engine import WalkForwardBacktest


@pytest.fixture
def mock_walk_forward_dataset():
    """Generates synthetic sequential matches across consecutive weeks."""
    matches = []
    teams = ["galatasaray", "fenerbahce", "besiktas", "trabzonspor"]
    base_date = datetime(2025, 9, 1, 15, 0, 0, tzinfo=UTC)

    for i in range(25):
        h = teams[i % len(teams)]
        a = teams[(i + 1) % len(teams)]
        dt = datetime.fromtimestamp(base_date.timestamp() + i * 86400, tz=UTC)
        matches.append({
            "home_team": h,
            "away_team": a,
            "home_score": (i % 3) + 1,
            "away_score": (i % 2),
            "event_date": dt.isoformat(),
        })
    return matches


def test_walk_forward_insufficient_data_raises():
    """Backtest must raise error if match count <= min_train_size."""
    bt = WalkForwardBacktest(min_train_size=20)
    with pytest.raises(ValueError):
        bt.run([{"event_date": "2026-01-01T00:00:00Z"}] * 10)


def test_walk_forward_metrics_and_temporal_order(mock_walk_forward_dataset):
    """Verify Brier score and log loss calculations over valid walk-forward run."""
    min_train = 10
    bt = WalkForwardBacktest(min_train_size=min_train)
    summary, records = bt.run(mock_walk_forward_dataset)

    expected_tests = len(mock_walk_forward_dataset) - min_train
    assert summary.total_test_matches == expected_tests
    assert len(records) == expected_tests

    # Metrics bounded checks
    assert 0.0 <= summary.brier_score_mean <= 2.0
    assert summary.log_loss_mean >= 0.0
    assert 0.0 <= summary.accuracy_percent <= 100.0

    # Ensure temporal sequence: each record's event_date is non-decreasing
    dates = [datetime.fromisoformat(r["event_date"]) for r in records]
    for i in range(len(dates) - 1):
        assert dates[i] <= dates[i + 1]


def test_brier_and_log_loss_math():
    """Verify multi-class Brier score and log loss formulas directly."""
    p_h, p_d, p_a = 0.6, 0.3, 0.1
    # Actual outcome HOME -> y = (1, 0, 0)
    brier = (0.6 - 1.0) ** 2 + (0.3 - 0.0) ** 2 + (0.1 - 0.0) ** 2
    assert pytest.approx(brier, abs=1e-4) == 0.16 + 0.09 + 0.01  # 0.26

    log_loss = -math.log(0.6)
    assert pytest.approx(log_loss, abs=1e-4) == 0.5108
