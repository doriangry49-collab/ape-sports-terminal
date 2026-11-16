"""Unit tests for InPlaySniperEngine (Proposal 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from in_play_sniper_engine import (
    InPlaySniperEngine,
    american_to_decimal,
    parse_display_clock,
    parse_espn_live_odds,
)
from live_inplay_ledger import LiveInPlayLedger


def test_parse_display_clock():
    """Verify robust parsing of various soccer clock string formats."""
    assert parse_display_clock("25'") == 25
    assert parse_display_clock("45'+2'") == 45
    assert parse_display_clock("78'") == 78
    assert parse_display_clock("90'+5'") == 90
    assert parse_display_clock(None) is None
    assert parse_display_clock("") is None
    assert parse_display_clock("Halftime") is None


def test_evaluate_in_play_hazard_decay_and_siege(tmp_path):
    """Verify Empirical Bayes hazard rate blending and game-state siege multipliers."""
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [],
        bridge_cache_path=tmp_path / "bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger.csv"),
        active_alerts_path=tmp_path / "active.json",
    )

    # Pre-match mu = 11.0, elapsed = 20 mins, 1 corner observed so far
    # Home team trailing 0-1 (siege effect active)
    res = engine.evaluate_in_play_hazard(
        home="Arsenal",
        away="Chelsea",
        elapsed_min=20,
        current_corners=1,
        current_goals_home=0,
        current_goals_away=1,
        total_shots=8,
        pre_match_mu=11.0,
    )

    assert res["home"] == "Arsenal"
    assert res["away"] == "Chelsea"
    assert res["elapsed_min"] == 20
    assert res["current_corners"] == 1
    assert res["pre_match_mu"] == 11.0
    # Trailing home team + high shot tempo should activate siege multiplier > 1.0
    assert res["siege_multiplier"] > 1.0
    # Projected remaining corners should be realistic
    assert res["projected_remaining"] > 4.0
    # Over 7.5 or 8.5 should be evaluated, with NO fake 1.85 placeholder odds
    lines = [le["line"] for le in res["lines"]]
    assert any(line in (7.5, 8.5) for line in lines)
    assert all(le["market_odds"] is None and le["edge_pct"] is None for le in res["lines"])


def test_panic_mispricing_detection(tmp_path):
    """Verify fail-closed behavior without live odds, and panic mispricing trigger with real live corner odds."""
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [],
        bridge_cache_path=tmp_path / "bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger.csv"),
        active_alerts_path=tmp_path / "active.json",
    )

    # 1. Without real live corner odds -> MUST fail closed (no 1.85 fallback!)
    res_no_odds = engine.evaluate_in_play_hazard(
        home="Borussia Dortmund",
        away="Bayern Munich",
        elapsed_min=25,
        current_corners=1,
        current_goals_home=0,
        current_goals_away=0,
        total_shots=9,
        pre_match_mu=11.5,
    )
    assert res_no_odds["is_panic_mispricing"] is False
    assert res_no_odds["best_opportunity"] is None

    # 2. Negative-EV live corner quote (8.5 @ 1.82 when fair odds ~3.27) -> MUST be vetoed!
    res_bad_ev = engine.evaluate_in_play_hazard(
        home="Borussia Dortmund",
        away="Bayern Munich",
        elapsed_min=25,
        current_corners=1,
        current_goals_home=0,
        current_goals_away=0,
        total_shots=9,
        pre_match_mu=11.5,
        live_corner_odds_by_line={"8.5": {"over": 1.82, "under": 1.88}},
    )
    assert res_bad_ev["is_panic_mispricing"] is False
    assert res_bad_ev["best_opportunity"] is None

    # 3. Genuine panic mispricing with real quoted live corner odds (4.5 @ 1.65 when fair odds ~1.29)
    res = engine.evaluate_in_play_hazard(
        home="Borussia Dortmund",
        away="Bayern Munich",
        elapsed_min=25,
        current_corners=1,
        current_goals_home=0,
        current_goals_away=0,
        total_shots=9,
        pre_match_mu=11.5,
        live_corner_odds_by_line={"4.5": {"over": 1.65, "under": 2.15}},
    )
    assert res["is_panic_mispricing"] is True
    assert res["best_opportunity"] is not None
    assert res["best_opportunity"]["is_synthetic_odds"] is False
    assert res["best_opportunity"]["market_odds"] == 1.65
    assert res["best_opportunity"]["edge_pct"] >= 5.0
    assert res["best_opportunity"]["p_over"] >= 0.58


@patch("in_play_sniper_engine.urllib.request.urlopen")
def test_scan_in_play_opportunities_mocked(mock_urlopen, tmp_path):
    """Test full pipeline with mocked ESPN scoreboard and summary responses."""
    # Mock Scoreboard response
    scoreboard_data = {
        "events": [
            {
                "id": "999001",
                "name": "Bayern Munich at Borussia Dortmund",
                "status": {
                    "type": {"state": "in"},
                    "displayClock": "28'",
                    "period": 1,
                },
                "links": [
                    {"href": "https://www.espn.com/soccer/report/_/gameId/999001/league/ger.1"}
                ],
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "score": "0", "team": {"name": "Borussia Dortmund"}},
                            {"homeAway": "away", "score": "1", "team": {"name": "Bayern Munich"}},
                        ]
                    }
                ],
            }
        ]
    }

    # Mock Summary boxscore response
    summary_data = {
        "boxscore": {
            "teams": [
                {
                    "statistics": [
                        {"name": "wonCorners", "displayValue": "2"},
                        {"name": "totalShots", "displayValue": "6"},
                        {"name": "shotsOnTarget", "displayValue": "3"},
                        {"name": "possessionPct", "displayValue": "48.0"},
                    ]
                },
                {
                    "statistics": [
                        {"name": "wonCorners", "displayValue": "1"},
                        {"name": "totalShots", "displayValue": "5"},
                        {"name": "shotsOnTarget", "displayValue": "2"},
                        {"name": "possessionPct", "displayValue": "52.0"},
                    ]
                },
            ]
        }
    }

    def _mock_url_read(req, timeout=5.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        mock_resp = MagicMock()
        if "scoreboard" in url:
            mock_resp.read.return_value = json.dumps(scoreboard_data).encode("utf-8")
        else:
            mock_resp.read.return_value = json.dumps(summary_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    mock_urlopen.side_effect = _mock_url_read

    # 1. Without real live corner odds -> fail-closed: ZERO opportunities, ZERO ledger bets
    engine_no_odds = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [],
        bridge_cache_path=tmp_path / "nesine_bridge_empty.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger_empty.csv"),
        active_alerts_path=tmp_path / "active_empty.json",
    )
    engine_no_odds.seen_alerts = set()
    with patch.object(engine_no_odds.corner_engine, "estimate_corner_mu", return_value=(11.5, {})):
        opps_empty = engine_no_odds.scan_in_play_opportunities(committee=None, dispatch_telegram=False)
    assert opps_empty == []
    assert engine_no_odds.ledger.get_summary()["total_bets"] == 0

    # 2. With real live corner odds from Nesine live feed -> triggers genuine signal
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [{
            "nesine_code": 3309901,
            "home": "Borussia Dortmund",
            "away": "Bayern Munich",
            "live_corners": {"8.5": {"over": 1.92, "under": 1.78}},
        }],
        bridge_cache_path=tmp_path / "nesine_bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger.csv"),
        active_alerts_path=tmp_path / "active.json",
    )
    engine.seen_alerts = set()  # Ensure empty

    # Force pre-match mu to 11.5 for this test
    with (
        patch.object(engine.corner_engine, "estimate_corner_mu", return_value=(11.5, {})),
        patch.object(engine, "_save_seen_alerts", return_value=None),
    ):
        opportunities = engine.scan_in_play_opportunities(committee=None, dispatch_telegram=False)

    assert len(opportunities) >= 1
    opp = opportunities[0]
    assert opp["event_id"] == "999001"
    assert opp["home"] == "Borussia Dortmund"
    assert opp["away"] == "Bayern Munich"
    assert opp["current_corners"] == 3
    assert opp["market"] == "CANLI KORNER"
    assert opp["is_synthetic_odds"] is False
    assert opp["book_odd"] == 1.92
    assert opp["stake"] >= 50.0  # SPEC-0015 compliance


def test_parse_espn_live_odds_and_american_conversion() -> None:
    assert american_to_decimal("+119") == 2.19
    assert american_to_decimal("-171") == 1.585
    assert american_to_decimal("OFF") is None

    comp = {
        "odds": [{
            "provider": {"name": "DraftKings"},
            "total": {
                "over": {"open": {"line": "o2.5", "odds": "-125"}, "current": {"line": "o1.5", "odds": "+119"}},
                "under": {"current": {"line": "u1.5", "odds": "-171"}},
            },
            "moneyline": {
                "home": {"open": {"odds": "+235"}, "current": {"odds": "+320"}},
                "draw": {"current": {"odds": "+145"}},
                "away": {"open": {"odds": "+100"}, "current": {"odds": "+135"}},
            },
        }]
    }
    parsed = parse_espn_live_odds(comp)
    assert parsed["odds_provider"] == "DraftKings"
    assert parsed["live_total_line"] == 1.5
    assert parsed["live_total_over_odds"] == 2.19
    assert parsed["live_total_under_odds"] == 1.585
    assert parsed["open_o25"] == 1.8
    assert parsed["live_1x2"] == (4.2, 2.45, 2.35)


def test_nesine_bridge_persists_across_kickoff_and_supports_live_feed(tmp_path: Path) -> None:
    cache_file = tmp_path / "nesine_bridge.json"

    # Pre-match snapshot before kickoff captures Nesine pre-match reference
    pre_engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [{
            "nesine_code": 3359411,
            "home": "NY Red Bulls",
            "away": "CF America",
            "nesine_1x2": (2.10, 3.20, 2.75),
            "nesine_ou25": (1.72, 1.88),
            "nesine_corners": {"9.5": {"over": 1.80, "under": 1.75}},
        }],
        bridge_cache_path=cache_file,
        ledger=LiveInPlayLedger(tmp_path / "bridge_ledger.csv"),
        active_alerts_path=tmp_path / "bridge_active.json",
    )
    stats = pre_engine.refresh_nesine_bridge(force=True)
    assert stats["pre_cached_count"] == 1
    assert cache_file.exists()

    # After kickoff: getprebultenfull returns empty, but persisted cache + injected live feed still link match
    live_engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        nesine_live_provider=lambda: [{
            "nesine_code": 3359411,
            "home": "New York Red Bulls",
            "away": "America",
            "live_total_line": 2.5,
            "live_total_over_odds": 2.15,
            "live_corners": {"8.5": {"over": 2.05, "under": 1.65}},
        }],
        bridge_cache_path=cache_file,
        ledger=LiveInPlayLedger(tmp_path / "bridge_ledger.csv"),
        active_alerts_path=tmp_path / "bridge_active.json",
    )
    live_engine.refresh_nesine_bridge(force=True)
    ctx = live_engine.match_nesine_context("New York Red Bulls", "Club America")
    assert ctx["nesine_code"] == 3359411
    assert ctx["nesine_pre_match"]["nesine_ou25"] == [1.72, 1.88] or ctx["nesine_pre_match"]["nesine_ou25"] == (1.72, 1.88)
    assert ctx["nesine_live"]["live_total_over_odds"] == 2.15
    assert ctx["nesine_live"]["live_corners"]["8.5"]["over"] == 2.05


def test_real_live_odds_dispatch_and_negative_ev_veto(tmp_path: Path) -> None:
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        bridge_cache_path=tmp_path / "bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger_real.csv"),
        active_alerts_path=tmp_path / "active_real.json",
    )
    engine.seen_alerts = set()

    # High-tempo match at 55' (2-1, HT 2-0), real live Over 3.5 @ 2.25 -> +EV, non-synthetic
    live_match_ev = [{
        "event_id": "live_real_1",
        "name": "Monterrey at Queretaro",
        "home": "Queretaro",
        "away": "Monterrey",
        "hg": 2,
        "ag": 1,
        "elapsed_min": 55,
        "clock_display": "55'",
        "period": 2,
        "league_code": "mex.1",
        "open_o25": 1.60,
        "open_1": 2.10,
        "open_2": 2.80,
        "live_total_line": 3.5,
        "live_total_over_odds": 2.65,
        "has_real_live_odds": True,
        "odds_source": "espn_draftkings_live",
        "nesine_code": 3399901,
    }]
    mock_stats = {
        "home_corners": 4,
        "away_corners": 3,
        "total_corners": 7,
        "home_shots": 14,
        "away_shots": 10,
        "total_shots": 24,
        "home_sot": 6,
        "away_sot": 4,
        "total_sot": 10,
        "home_possession": 54.0,
        "away_possession": 46.0,
        "has_corners": True,
        "has_ht_score": True,
        "ht_home": 2,
        "ht_away": 0,
        "ht_goals": 2,
        "key_events": [],
    }

    with (
        patch.object(engine, "fetch_live_in_play_matches", return_value=live_match_ev),
        patch.object(engine, "fetch_live_match_stats", return_value=mock_stats),
        patch.object(engine, "_save_seen_alerts", return_value=None),
        patch("in_play_sniper_engine.send_telegram_message") as mock_tg,
    ):
        opps = engine.scan_in_play_goal_anomalies(dispatch_telegram=True)
        assert len(opps) == 1
        assert opps[0]["is_synthetic_odds"] is False
        assert opps[0]["odds_source"] == "espn_draftkings_live"
        assert opps[0]["book_odd"] == 2.65
        assert opps[0]["edge_pct"] >= 4.0
        assert opps[0]["nesine_code"] == 3399901
        mock_tg.assert_called_once()

    # Now test low/negative-EV live odd (1.20) -> must be vetoed fail-closed!
    engine.seen_alerts = set()
    live_match_bad_odd = [{**live_match_ev[0], "event_id": "live_real_2", "live_total_over_odds": 1.20}]
    with (
        patch.object(engine, "fetch_live_in_play_matches", return_value=live_match_bad_odd),
        patch.object(engine, "fetch_live_match_stats", return_value=mock_stats),
        patch("in_play_sniper_engine.send_telegram_message") as mock_tg2,
    ):
        opps2 = engine.scan_in_play_goal_anomalies(dispatch_telegram=True)
        assert opps2 == []
        mock_tg2.assert_not_called()


def test_corner_sniper_with_real_nesine_live_odds_dispatches_telegram(tmp_path: Path) -> None:
    engine = InPlaySniperEngine(
        nesine_pre_provider=lambda: [],
        bridge_cache_path=tmp_path / "bridge.json",
        ledger=LiveInPlayLedger(tmp_path / "ledger_corner.csv"),
        active_alerts_path=tmp_path / "active_corner.json",
    )
    engine.seen_alerts = set()

    live_match = [{
        "event_id": "live_corner_1",
        "name": "Liverpool at Arsenal",
        "home": "Arsenal",
        "away": "Liverpool",
        "hg": 0,
        "ag": 1,
        "elapsed_min": 28,
        "clock_display": "28'",
        "period": 1,
        "league_code": "eng.1",
        "live_corners": {
            "8.5": {"over": 1.95, "under": 1.75},
            "9.5": {"over": 2.35, "under": 1.50},
        },
        "nesine_code": 3300112,
        "nesine_pre_match": {"nesine_corners": {"9.5": {"over": 1.80, "under": 1.85}}},
    }]
    mock_stats = {
        "home_corners": 2,
        "away_corners": 1,
        "total_corners": 3,
        "home_shots": 7,
        "away_shots": 5,
        "total_shots": 12,
        "home_sot": 3,
        "away_sot": 2,
        "total_sot": 5,
        "home_possession": 55.0,
        "away_possession": 45.0,
        "has_corners": True,
        "key_events": [],
    }

    with (
        patch.object(engine, "fetch_live_in_play_matches", return_value=live_match),
        patch.object(engine, "fetch_live_match_stats", return_value=mock_stats),
        patch.object(engine.corner_engine, "estimate_corner_mu", return_value=(11.5, {})),
        patch.object(engine, "_save_seen_alerts", return_value=None),
        patch("in_play_sniper_engine.send_telegram_message") as mock_tg,
    ):
        opps = engine.scan_in_play_opportunities(committee=None, dispatch_telegram=True)
        assert len(opps) == 1
        assert opps[0]["is_synthetic_odds"] is False
        assert opps[0]["odds_source"] == "nesine_live"
        assert opps[0]["nesine_code"] == 3300112
        assert opps[0]["book_odd"] >= 1.45
        mock_tg.assert_called_once()


