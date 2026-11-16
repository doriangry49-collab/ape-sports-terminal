"""Unit tests for Live Settlement & Accounting Engine."""

from __future__ import annotations

from unittest.mock import patch

from live_settlement_engine import (
    evaluate_pick_result,
    load_active_coupons,
    load_bankroll,
    run_settlement_cycle,
)


def test_evaluate_pick_result():
    # 1X2
    assert evaluate_pick_result("1X2", "MS 1", hg=2, ag=1) is True
    assert evaluate_pick_result("1X2", "MS 1", hg=1, ag=2) is False
    assert evaluate_pick_result("1X2", "MS X", hg=2, ag=2) is True
    assert evaluate_pick_result("1X2", "MS 2", hg=0, ag=3) is True

    # TG 6+
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=4, ag=2) is True
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=3, ag=2) is False

    # 2.5 Over/Under
    assert evaluate_pick_result("2.5 Gol", "2.5 ÜST", hg=2, ag=1) is True
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=1, ag=1) is True


def test_load_active_coupons_and_bankroll(tmp_path, monkeypatch):
    """Test loading active coupons and bankroll ledger in isolated sandbox."""
    import json
    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll_file)

    # 1. Missing file default fallback test
    coupons = load_active_coupons()
    assert coupons == []
    bankroll = load_bankroll()
    assert bankroll["initial_bankroll"] == 150.0
    assert bankroll["total_staked"] == 150.0
    assert bankroll["cash_balance"] == 0.0

    # 2. Existing file loading test
    mock_coupons = [
        {"id": "coupon_001_shield", "name": "Kasa Kalkanı", "status": "PENDING"},
        {"id": "coupon_002_tg6_sistem", "name": "TG 6+ Sistem", "status": "PENDING"},
        {"id": "coupon_003_htft_sistem", "name": "İY/MS Sistem", "status": "PENDING"},
    ]
    test_coupons_file.write_text(json.dumps(mock_coupons), encoding="utf-8")

    mock_bankroll = {
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(json.dumps(mock_bankroll), encoding="utf-8")

    coupons = load_active_coupons()
    assert len(coupons) == 3
    assert any(c["id"] == "coupon_001_shield" for c in coupons)

    bankroll = load_bankroll()
    assert bankroll["initial_bankroll"] == 150.0
    assert bankroll["total_staked"] == 150.0
    assert bankroll["status"] == "ALL_IN_PLAY"


def test_evaluate_pick_result_htft():
    """Verify evaluation of HT/FT outcomes with exact half-time scores."""
    # 2/2: Away leading at HT (0-1) and winning at FT (1-2)
    assert evaluate_pick_result("HT_FT", "2/2", hg=1, ag=2, ht_hg=0, ht_ag=1) is True
    # 2/2 failed because HT was draw (0-0)
    assert evaluate_pick_result("HT_FT", "2/2", hg=1, ag=2, ht_hg=0, ht_ag=0) is False
    # X/1: Draw at HT (1-1) and Home winning at FT (2-1)
    assert evaluate_pick_result("HT_FT", "X/1", hg=2, ag=1, ht_hg=1, ht_ag=1) is True
    # Missing HT score: fail-closed (False)
    assert evaluate_pick_result("HT_FT", "X/1", hg=2, ag=1, ht_hg=None, ht_ag=None) is False
    # Format with descriptive label e.g. "X/2 (İY 0 / MS 2)"
    assert evaluate_pick_result("HT_FT", "X/2 (İY 0 / MS 2)", hg=0, ag=1, ht_hg=0, ht_ag=0) is True


def test_fetch_espn_scores_inverted_competitors(monkeypatch):
    """Verify that when ESPN provides away competitor first, homeAway resolution corrects it."""
    import json

    from live_settlement_engine import fetch_espn_scores

    mock_response_data = {
        "events": [
            {
                "name": "Team A vs Team B",
                "status": {"type": {"description": "Full Time"}, "period": 2},
                "competitions": [
                    {
                        "competitors": [
                            {
                                "homeAway": "away",
                                "team": {"name": "Team B", "displayName": "Team B Away"},
                                "score": "3",
                                "linescores": [{"period": 1, "value": 1.0}],
                            },
                            {
                                "homeAway": "home",
                                "team": {"name": "Team A", "displayName": "Team A Home"},
                                "score": "1",
                                "linescores": [{"period": 1, "value": 0.0}],
                            },
                        ]
                    }
                ],
            }
        ]
    }

    class MockResp:
        def read(self):
            return json.dumps(mock_response_data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5.0: MockResp())

    scores = fetch_espn_scores("test.league")
    assert len(scores) == 1
    match = scores[0]
    # Home must be Team A with 1 goal, Away must be Team B with 3 goals
    assert match["home"] == "Team A"
    assert match["away"] == "Team B"
    assert match["hg"] == 1
    assert match["ag"] == 3
    assert match["ht_hg"] == 0
    assert match["ht_ag"] == 1
    assert match["is_completed"] is True


def test_run_settlement_cycle_system_2_3_htft(tmp_path, monkeypatch):
    """Verify System 2/3 parlay settlement with HT/FT picks and bankroll ledger updates."""
    import json

    from live_settlement_engine import load_active_coupons, load_bankroll, run_settlement_cycle

    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll_file)
    monkeypatch.setattr("live_settlement_engine.send_telegram_message", lambda *args, **kwargs: True)

    # 2 coupons: one settling, one pending
    coupons = [
        {
            "id": "coupon_sys",
            "name": "HT/FT Sistem",
            "type": "SYSTEM_2_3",
            "stake": 44.0,
            "misli": 11,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Match 1",
                    "home": "HomeA",
                    "away": "AwayA",
                    "league_key": "bra.1",
                    "market": "HT_FT",
                    "selection": "2/2",
                    "odds": 3.0,
                    "status": "PENDING",
                },
                {
                    "match": "Match 2",
                    "home": "HomeB",
                    "away": "AwayB",
                    "league_key": "fra.1",
                    "market": "HT_FT",
                    "selection": "X/1",
                    "odds": 4.0,
                    "status": "PENDING",
                },
                {
                    "match": "Match 3",
                    "home": "HomeC",
                    "away": "AwayC",
                    "league_key": "esp.1",
                    "market": "HT_FT",
                    "selection": "X/1",
                    "odds": 5.0,
                    "status": "PENDING",
                },
            ],
        },
        {
            "id": "coupon_other",
            "name": "Pending Coupon",
            "type": "ACCUMULATOR",
            "stake": 50.0,
            "potential_return": 150.0,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Match Tomorrow",
                    "home": "Arsenal",
                    "away": "Chelsea",
                    "league_key": "eng.1",
                    "market": "1X2",
                    "selection": "MS 1",
                    "odds": 1.5,
                    "status": "PENDING",
                }
            ],
        },
    ]
    test_coupons_file.write_text(json.dumps(coupons), encoding="utf-8")

    bankroll = {
        "currency": "TL",
        "initial_bankroll": 150.0,
        "total_staked": 94.0,
        "cash_balance": 56.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "active_tickets_count": 2,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(json.dumps(bankroll), encoding="utf-8")

    # Mock Match 1 (WON: 0-1 HT, 1-2 FT => 2/2)
    # Mock Match 2 (WON: 0-0 HT, 1-0 FT => X/1)
    # Mock Match 3 (LOST: 1-0 HT, 1-0 FT => 1/1 != X/1)
    mock_matches = [
        {"name": "Match 1", "league": "bra.1", "home": "HomeA", "away": "AwayA", "hg": 1, "ag": 2, "ht_hg": 0, "ht_ag": 1, "status": "Full Time", "is_completed": True, "is_in_progress": False},
        {"name": "Match 2", "league": "fra.1", "home": "HomeB", "away": "AwayB", "hg": 1, "ag": 0, "ht_hg": 0, "ht_ag": 0, "status": "Full Time", "is_completed": True, "is_in_progress": False},
        {"name": "Match 3", "league": "esp.1", "home": "HomeC", "away": "AwayC", "hg": 1, "ag": 0, "ht_hg": 1, "ht_ag": 0, "status": "Full Time", "is_completed": True, "is_in_progress": False},
    ]
    monkeypatch.setattr("live_settlement_engine.fetch_espn_scores", lambda l_key, *args: mock_matches)

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 1
    # System 2/3 payout for 2 won picks (odds 3.0 and 4.0) with misli 11:
    # (3.0 * 4.0) * 11 = 132.0 TL
    assert res["new_winnings"] == 132.0

    updated_coupons = load_active_coupons()
    c_sys = next(c for c in updated_coupons if c["id"] == "coupon_sys")
    assert c_sys["status"] == "WON"
    assert c_sys["payout"] == 132.0

    updated_bankroll = load_bankroll()
    # Cash: 56.0 + 132.0 = 188.0
    assert updated_bankroll["cash_balance"] == 188.0
    # Active tickets: 1 remaining (coupon_other)
    assert updated_bankroll["active_tickets_count"] == 1
    assert updated_bankroll["settled_tickets_count"] == 1
    # Active stakes in play: 50.0 (coupon_other)
    # Total portfolio value = cash (188.0) + active stakes (50.0) = 238.0
    assert updated_bankroll["total_portfolio_value"] == 238.0
    # Realized PnL: payout (132.0) - settled stake (44.0) = +88.0
    assert updated_bankroll["realized_pnl"] == 88.0
    assert updated_bankroll["status"] == "PARTIALLY_SETTLED"


@patch("live_settlement_engine.send_telegram_message")
@patch("live_settlement_engine.fetch_espn_scores")
def test_run_settlement_cycle_won_shield(mock_scores, mock_tg, tmp_path, monkeypatch):
    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll_file)

    initial_coupons = [
        {
            "id": "test_c1",
            "name": "Kasa Kalkanı Test",
            "type": "ACCUMULATOR",
            "stake": 50.0,
            "potential_return": 147.0,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Marseille vs Toulouse",
                    "home": "Marseille",
                    "away": "Toulouse",
                    "league_key": "fra.1",
                    "market": "1X2",
                    "selection": "MS 1",
                    "odds": 1.67,
                    "status": "PENDING",
                },
                {
                    "match": "Athletic Club vs Real Sociedad",
                    "home": "Athletic Club",
                    "away": "Real Sociedad",
                    "league_key": "esp.1",
                    "market": "1X2",
                    "selection": "MS 1",
                    "odds": 1.76,
                    "status": "PENDING",
                },
            ],
        }
    ]
    test_coupons_file.write_text(
        __import__("json").dumps(initial_coupons), encoding="utf-8"
    )

    initial_bankroll = {
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "settled_tickets_count": 0,
    }
    test_bankroll_file.write_text(
        __import__("json").dumps(initial_bankroll), encoding="utf-8"
    )

    # Mock completed matches
    mock_scores.side_effect = lambda l_key, *args: [
        {
            "name": "Marseille vs Toulouse",
            "home": "Marseille",
            "away": "Toulouse",
            "hg": 3,
            "ag": 1,
            "status": "Full Time",
            "is_completed": True,
            "is_in_progress": False,
        }
    ] if l_key == "fra.1" else [
        {
            "name": "Athletic Club vs Real Sociedad",
            "home": "Athletic Club",
            "away": "Real Sociedad",
            "hg": 2,
            "ag": 0,
            "status": "Full Time",
            "is_completed": True,
            "is_in_progress": False,
        }
    ]

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 1
    assert res["new_winnings"] == 147.0
    assert mock_tg.call_count == 1

    settled_bankroll = load_bankroll()
    assert settled_bankroll["cash_balance"] == 147.0
    assert settled_bankroll["settled_tickets_count"] == 1


def test_evaluate_pick_result_corners_and_cards():
    """Verify corner and card market outcome evaluations."""
    # Corners ALT
    assert evaluate_pick_result("CORNERS", "Korner 8.5 ALT", hg=0, ag=2, corners=6) is True
    assert evaluate_pick_result("CORNERS", "Korner 8.5 ALT", hg=0, ag=2, corners=9) is False
    # Corners ÜST
    assert evaluate_pick_result("CORNERS", "Korner 9.5 ÜST", hg=1, ag=1, corners=11) is True
    assert evaluate_pick_result("CORNERS", "Korner 9.5 ÜST", hg=1, ag=1, corners=8) is False
    # Cards ALT / ÜST
    assert evaluate_pick_result("CARDS", "Kart 4.5 ALT", hg=1, ag=0, cards=3) is True
    assert evaluate_pick_result("CARDS", "Kart 4.5 ÜST", hg=1, ag=0, cards=5) is True


@patch("live_settlement_engine.send_telegram_message")
@patch("live_settlement_engine.fetch_espn_scores")
def test_run_settlement_cycle_single_corner_coupon(mock_scores, mock_tg, tmp_path, monkeypatch):
    """Verify single corner ticket settlement and bankroll accounting."""
    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll_file)

    single_coupon = [
        {
            "id": "coupon_test_corner",
            "name": "Test Corner Single",
            "type": "SINGLE",
            "stake": 50.0,
            "total_odds": 2.03,
            "potential_return": 101.5,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Slavia Prag vs Arsenal",
                    "home": "Slavia Prag",
                    "away": "Arsenal",
                    "league_key": "ucl",
                    "market": "CORNERS",
                    "selection": "Korner 8.5 ALT",
                    "odds": 2.03,
                    "status": "PENDING",
                    "score": None,
                }
            ],
        }
    ]
    test_coupons_file.write_text(__import__("json").dumps(single_coupon), encoding="utf-8")

    initial_bankroll = {
        "initial_bankroll": 150.0,
        "total_staked": 50.0,
        "cash_balance": 50.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 100.0,
        "active_tickets_count": 1,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(__import__("json").dumps(initial_bankroll), encoding="utf-8")

    mock_scores.return_value = [
        {
            "name": "Arsenal at Slavia Prague",
            "home": "Slavia Prague",
            "away": "Arsenal",
            "league": "uefa.champions",
            "hg": 0,
            "ag": 2,
            "corners": 6,
            "status": "Full Time",
            "is_completed": True,
            "is_in_progress": False,
        }
    ]

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 1
    assert res["new_winnings"] == 101.5
    assert mock_tg.call_count == 1

    settled_bankroll = load_bankroll()
    assert settled_bankroll["cash_balance"] == 151.5
    assert settled_bankroll["total_portfolio_value"] == 151.5
    assert settled_bankroll["realized_pnl"] == 51.5
    assert settled_bankroll["settled_tickets_count"] == 1
    assert settled_bankroll["active_tickets_count"] == 0
    assert settled_bankroll["status"] == "ALL_SETTLED"


