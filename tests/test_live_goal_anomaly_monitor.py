"""
Unit and Integration tests for In-Play Goal Anomaly Live Monitoring.
Validates:
1. InPlaySniperEngine.scan_in_play_goal_anomalies live match scanning
2. Halftime 88.8% HT Over 1.5 rule qualification filtering
3. SPEC-0015 minimum 50 TL stake enforcement
4. Alert deduplication via seen_alerts persistence
5. Telegram in-play goal anomaly formatter output
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from in_play_sniper_engine import InPlaySniperEngine
from live_inplay_ledger import LiveInPlayLedger
from sports_engine.models.goal_anomaly_engine import (
    GoalAnomalyEngine,
    format_in_play_goal_anomaly_alert,
)


@pytest.fixture
def sniper(monkeypatch, tmp_path):
    monkeypatch.setattr(InPlaySniperEngine, "_load_seen_alerts", lambda self: set())
    monkeypatch.setattr(InPlaySniperEngine, "_save_seen_alerts", lambda self: None)
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [],
        bridge_cache_path=tmp_path / "bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "live_ledger.csv"),
        active_alerts_path=tmp_path / "active_alerts.json",
    )
    engine.seen_alerts = set()
    return engine


def test_scan_in_play_goal_anomalies_qualified_match(sniper):
    """Verify that a match with HT goals >= 2, high tempo, and REAL live odds triggers an alert; missing odds fail closed."""
    mock_matches_no_odds = [
        {
            "event_id": "live_ev_no_odds",
            "name": "Bayern Munich vs Borussia Dortmund",
            "home": "Bayern Munich",
            "away": "Borussia Dortmund",
            "hg": 2,
            "ag": 1,
            "elapsed_min": 56,
            "clock_display": "56'",
            "period": 2,
            "league_code": "ger.1",
        }
    ]
    mock_matches = [
        {
            "event_id": "live_ev_101",
            "name": "Bayern Munich vs Borussia Dortmund",
            "home": "Bayern Munich",
            "away": "Borussia Dortmund",
            "hg": 2,
            "ag": 1,
            "elapsed_min": 56,
            "clock_display": "56'",
            "period": 2,
            "league_code": "ger.1",
            "open_o25": 1.48,
            "open_1": 1.75,
            "open_2": 4.10,
            "live_total_line": 4.5,
            "live_total_over_odds": 2.35,
            "has_real_live_odds": True,
            "odds_source": "espn_draftkings_live",
        }
    ]

    mock_stats = {
        "home_corners": 4,
        "away_corners": 3,
        "total_corners": 7,
        "home_shots": 14,
        "away_shots": 9,
        "total_shots": 23,
        "home_sot": 6,
        "away_sot": 4,
        "total_sot": 10,
        "home_possession": 56.0,
        "away_possession": 44.0,
        "has_corners": True,
        "has_ht_score": True,
        "ht_home": 2,
        "ht_away": 0,
        "ht_goals": 2,  # Passes 88.8% HT rule!
        "key_events": [
            {"type": {"text": "Goal"}, "clock": {"displayValue": "18'"}, "text": "Goal! Harry Kane (Bayern) right footed shot."},
            {"type": {"text": "Goal"}, "clock": {"displayValue": "34'"}, "text": "Goal! Leroy Sane (Bayern) left footed shot."},
            {"type": {"text": "Goal"}, "clock": {"displayValue": "52'"}, "text": "Goal! Julian Brandt (Dortmund) right footed shot."},
        ],
    }

    # Fail-closed check: without real live odds, MUST return 0 signals (no 1.85 fallback!)
    with patch.object(sniper, "fetch_live_in_play_matches", return_value=mock_matches_no_odds), \
         patch.object(sniper, "fetch_live_match_stats", return_value=mock_stats):
        assert sniper.scan_in_play_goal_anomalies(dispatch_telegram=False) == []

    with patch.object(sniper, "fetch_live_in_play_matches", return_value=mock_matches), \
         patch.object(sniper, "fetch_live_match_stats", return_value=mock_stats), \
         patch("in_play_sniper_engine.send_telegram_message") as mock_tg:

        opps = sniper.scan_in_play_goal_anomalies(dispatch_telegram=True)

        assert len(opps) == 1
        sig = opps[0]
        assert sig["event_id"] == "live_ev_101"
        assert sig["market"] == "CANLI GOL ANOMALİSİ"
        assert sig["selection"] == "4.5 ÜST"
        assert sig["is_synthetic_odds"] is False
        assert sig["book_odd"] == 2.35
        assert sig["stake"] >= 50.0           # SPEC-0015 compliant
        assert sig["ht_goals"] == 2
        assert sig["anomaly_result"].is_live_qualified is True
        mock_tg.assert_called_once()

        # Verify seen_alerts prevents duplicates on second pass
        opps_repeat = sniper.scan_in_play_goal_anomalies(dispatch_telegram=True)
        assert len(opps_repeat) == 0


def test_scan_in_play_goal_anomalies_vetoed_by_ht_rule(sniper):
    """Verify that a match at 60' with 0-0 at halftime is vetoed by the 88.8% HT Over 1.5 rule."""
    mock_matches = [
        {
            "event_id": "live_ev_102",
            "name": "Getafe vs Leganes",
            "home": "Getafe",
            "away": "Leganes",
            "hg": 0,
            "ag": 0,
            "elapsed_min": 62,
            "clock_display": "62'",
            "period": 2,
            "league_code": "esp.1",
        }
    ]

    mock_stats = {
        "home_corners": 1,
        "away_corners": 1,
        "total_corners": 2,
        "home_shots": 3,
        "away_shots": 2,
        "total_shots": 5,
        "has_corners": True,
        "has_ht_score": True,
        "ht_home": 0,
        "ht_away": 0,
        "ht_goals": 0,  # Fails 88.8% rule
        "key_events": [],
    }

    with patch.object(sniper, "fetch_live_in_play_matches", return_value=mock_matches), \
         patch.object(sniper, "fetch_live_match_stats", return_value=mock_stats):

        opps = sniper.scan_in_play_goal_anomalies(dispatch_telegram=False)
        assert len(opps) == 0


def test_scan_in_play_goal_anomalies_vetoed_by_momentum_filter(sniper):
    """Verify that even with HT 2+ goals, a match that stalls in the 2nd half is vetoed by LiveMomentumEngine."""
    mock_matches = [
        {
            "event_id": "live_ev_103",
            "name": "Lazio vs Roma",
            "home": "Lazio",
            "away": "Roma",
            "hg": 2,
            "ag": 1,
            "elapsed_min": 68,
            "clock_display": "68'",
            "period": 2,
            "league_code": "ita.1",
        }
    ]

    # Stalled stats: only 8 total shots in 68 mins (0.117 shot/min < 0.20 threshold)
    mock_stats = {
        "home_corners": 1,
        "away_corners": 1,
        "total_corners": 2,
        "home_shots": 5,
        "away_shots": 3,
        "total_shots": 8,
        "home_sot": 2,
        "away_sot": 1,
        "total_sot": 3,
        "home_possession": 51.0,
        "away_possession": 49.0,
        "has_corners": True,
        "has_ht_score": True,
        "ht_home": 2,
        "ht_away": 1,
        "ht_goals": 3,  # Passes HT rule! But fails momentum.
        "key_events": [],
    }

    with patch.object(sniper, "fetch_live_in_play_matches", return_value=mock_matches), \
         patch.object(sniper, "fetch_live_match_stats", return_value=mock_stats):

        opps = sniper.scan_in_play_goal_anomalies(dispatch_telegram=False)
        assert len(opps) == 0  # Fail-closed momentum filter must veto!


def test_telegram_in_play_goal_alert_formatter():
    """Verify format_in_play_goal_anomaly_alert produces compliant, rich Telegram markdown."""
    engine = GoalAnomalyEngine()
    fixture = {
        "event_id": "test_tg_fmt",
        "home_team": "Bayern Munich",
        "away_team": "Borussia Dortmund",
        "league": "Bundesliga",
        "open_o25": 1.35,
    }

    key_events = [
        {"type": {"text": "Goal"}, "clock": {"displayValue": "21'"}, "text": "Goal! Harry Kane (Bayern) header."},
        {"type": {"text": "Goal"}, "clock": {"displayValue": "26'"}, "text": "Goal! Harry Kane (Bayern) penalty."},
    ]

    res = engine.evaluate_live_fixture(
        fixture=fixture,
        minute=58,
        ht_goals=2,
        score_home=2,
        score_away=0,
        total_shots_rate=0.35,
        key_events=key_events,
    )

    msg = format_in_play_goal_anomaly_alert(
        result=res,
        minute=58,
        current_score="2-0",
        ht_score="2-0",
        recommended_line="3.5 ÜST",
        market_odds=1.85,
    )

    assert "APE CANLI GOL ANOMALİSİ" in msg
    assert "Bayern Munich vs Borussia Dortmund" in msg
    assert "Dk: `58'`" or "Dakika:* `58'`" in msg
    assert "Canlı Skor:* `2-0`" in msg
    assert "Zamanlama Dilimi" in msg
    assert "Brace Scorer: Harry Kane" in msg
    assert "Min. 50.0 TL (SPEC-0015)" in msg
