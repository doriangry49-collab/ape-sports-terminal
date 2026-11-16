"""Unit tests for OddsPatternMiner & Empirical Conditional Analytics Engine."""
from __future__ import annotations

from pathlib import Path

import pytest

from odds_pattern_miner import OddsPatternMiner, PatternInsight

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "gold" / "odds_pattern_dataset_42k.parquet"


@pytest.fixture(scope="module")
def miner():
    return OddsPatternMiner(DATASET_PATH)


def test_miner_initialization(miner):
    assert miner is not None
    assert miner.baseline["n"] > 25000
    assert miner.baseline["avg_corners"] > 8.0
    assert miner.baseline["pct_ft_o25"] > 40.0


def test_query_conditional_high_totals(miner):
    # Matches where 2.5 Over is heavily favored
    insight = miner.query_conditional("open_o25 <= 1.55", min_sample=50)
    assert isinstance(insight, PatternInsight)
    assert insight.sample_size > 1000
    # Gollü beklenen maçlarda 2.5 Üst oranı ve ortalama korner baseline'ın üstünde olmalı
    assert insight.pct_ft_o25 > miner.baseline["pct_ft_o25"]
    assert insight.edge_ft_o25 > 5.0
    assert insight.avg_corners > miner.baseline["avg_corners"]
    assert len(insight.top_exact_scores) > 0
    assert len(insight.top_ht_scores) > 0


def test_query_conditional_defensive_low_totals(miner):
    # Matches where Under 2.5 is heavily favored
    insight = miner.query_conditional("open_u25 <= 1.60", min_sample=50)
    assert insight.sample_size > 500
    # Kısır beklenen maçlarda 2.5 Üst ve 12+ korner negatif sapma vermeli
    assert insight.edge_ft_o25 < -5.0
    assert insight.edge_corners_12plus < -3.0


def test_query_conditional_rejects_tiny_sample(miner):
    with pytest.raises(ValueError, match="Sample size too small"):
        miner.query_conditional("open_1 > 99.0 AND open_2 > 99.0", min_sample=50)


def test_query_conditional_rejects_invalid_sql(miner):
    with pytest.raises(ValueError, match="Invalid condition SQL syntax"):
        miner.query_conditional("non_existent_column_xyz == 123")


def test_inverse_profile(miner):
    prof = miner.inverse_profile("corners_12plus = 1")
    assert prof["sample_size"] > 5000
    assert prof["avg_open_over25_odd"] > 1.0
    assert "avg_steam_over25_pct" in prof


def test_discover_golden_patterns(miner):
    patterns = miner.discover_golden_patterns(min_sample=100, min_edge=5.0)
    assert len(patterns) >= 3
    for p in patterns:
        assert "name" in p
        assert "condition" in p
        assert p["sample_size"] >= 100

