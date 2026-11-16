"""Unit tests for Live Bulletin Golden Pattern Integration & Telegram Alerts."""
from __future__ import annotations

import pytest

from odds_pattern_miner import OddsPatternMiner, format_pattern_telegram_alert
from telegram_notifier import process_user_command


@pytest.fixture(scope="module")
def miner():
    return OddsPatternMiner()


def test_match_fixture_patterns_heavy_fav_high_totals(miner):
    # Mock fixture: Heavy home fav with 2.5 Over favored
    mock_fix = {
        "home": "Manchester City",
        "away": "Southampton",
        "time_str": "20:00",
        "mbs": 1,
        "nesine_1x2": (1.25, 6.0, 11.0),
        "nesine_ou25": (1.42, 2.50),
    }
    pats = miner.match_fixture_patterns(mock_fix)
    assert len(pats) >= 1
    p = pats[0]
    assert p["pattern_id"] == "HEAVY_HOME_FAV_HIGH_TOTALS"
    assert p["sample_size"] > 500
    assert p["pct_corners_12plus"] > 30.0
    assert p["pct_ht_o15"] > 40.0
    assert len(p["top_exact_scores"]) > 0


def test_match_fixture_patterns_low_totals_shield(miner):
    # Mock fixture: Defensive / low totals
    mock_fix = {
        "home": "Getafe",
        "away": "Cadiz",
        "time_str": "19:00",
        "mbs": 2,
        "nesine_1x2": (2.10, 2.90, 3.40),
        "nesine_ou25": (2.40, 1.45),
    }
    pats = miner.match_fixture_patterns(mock_fix)
    assert len(pats) >= 1
    p = pats[0]
    assert p["pattern_id"] == "LOW_TOTALS_CORNER_SHIELD"
    assert p["pct_corners_o95"] < 50.0  # Under 9.5 corners prevalent
    assert p["edge_corners_12plus"] < 0.0


def test_format_pattern_telegram_alert():
    mock_fix = {"home": "Arsenal", "away": "Wolves", "time_str": "21:00", "mbs": 1}
    mock_pattern = {
        "pattern_name": "Yüksek Gol & Korner Fırtınası",
        "description": "2.5 Üst Oranı (1.45) <= 1.55",
        "sample_size": 3358,
        "pct_corners_12plus": 35.8,
        "edge_corners_12plus": 6.4,
        "pct_ht_o15": 47.7,
        "edge_ht_o15": 13.6,
        "pct_ft_o25": 68.2,
        "edge_ft_o25": 17.1,
        "top_exact_scores": [("2-1", 8.55), ("1-1", 7.92)],
        "recommended_focus": "2.5 Üst (%68.2) & 12+ Korner (%35.8)",
    }
    text = format_pattern_telegram_alert(mock_fix, mock_pattern)
    assert "ALTIN ÖRÜNTÜ EŞLEŞMESİ" in text
    assert "Arsenal vs Wolves" in text
    assert "3358 Maç" in text
    assert "12+ Korner" in text
    assert "2-1 (%8.55)" in text


def test_telegram_oruntu_command():
    resp = process_user_command("/oruntu")
    assert isinstance(resp, str)
    assert len(resp) > 10
    # Response should either list matches or report no current matches in 12h
    assert ("ALTIN ÖRÜNTÜ" in resp) or ("bulunamadı" in resp)

