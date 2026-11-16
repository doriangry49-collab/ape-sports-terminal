"""End-to-End Test Suite for All Supported Bet Types and Settlement Accounting.

Author: worker_m3 (Milestone 3 E2E Verification & Test Worker)
Scope:
1. 1X2 Market Settlement (Home win, Draw, Away win across various token formats).
2. Over/Under (Total Goals) Market Settlement (2.5 Üst/Alt, Over/Under, >, <).
3. TG 6+ (Total Goals 6+) Market Settlement (Under 6 goals Lost, 6+ goals Won).
4. HT/FT (Half-Time / Full-Time) 9-Grid Scenarios with Period 1 Linescores:
   - 1/1, 1/X, 1/2, X/1, X/X, X/2, 2/1, 2/X, 2/2.
   - Descriptive token handling (e.g. "X/2 (İY 0 / MS 2)").
   - Fail-closed evaluation when half-time score linescores are missing.
5. Combinatoric System Parlay Bets:
   - System 1,2,3 with varying won legs.
   - System 2,3 with varying won legs.
   - Exact combinatorial payout verification.
6. Full Multi-Stage End-to-End Settlement Cycle with Bankroll Invariant Proof:
   - Conservation of total portfolio value: total_portfolio_value == cash_balance + active_stakes.
   - Mathematical accuracy of realized PnL: realized_pnl == total_settled_payouts - total_settled_stakes.
   - Ticket count synchronization: active_tickets_count + settled_tickets_count == total_coupons.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from live_settlement_engine import (
    calculate_system_payout,
    evaluate_pick_result,
    load_bankroll,
    run_settlement_cycle,
)

# =====================================================================
# 1. 1X2 MARKET SETTLEMENT E2E
# =====================================================================

def test_1x2_market_settlement_all_outcomes():
    """Verify 1X2 market correctly resolves for home win, draw, and away win."""
    # Home Win Scenarios (hg > ag)
    assert evaluate_pick_result("1X2", "MS 1", hg=2, ag=0) is True
    assert evaluate_pick_result("1X2", "MS1", hg=3, ag=2) is True
    assert evaluate_pick_result("1X2", "1", hg=1, ag=0) is True
    assert evaluate_pick_result("1X2", "HOME", hg=4, ag=1) is True
    assert evaluate_pick_result("1X2", "MS X", hg=2, ag=0) is False
    assert evaluate_pick_result("1X2", "MS 2", hg=2, ag=0) is False

    # Draw Scenarios (hg == ag)
    assert evaluate_pick_result("1X2", "MS X", hg=1, ag=1) is True
    assert evaluate_pick_result("1X2", "MSX", hg=0, ag=0) is True
    assert evaluate_pick_result("1X2", "X", hg=3, ag=3) is True
    assert evaluate_pick_result("1X2", "DRAW", hg=2, ag=2) is True
    assert evaluate_pick_result("1X2", "MS 1", hg=1, ag=1) is False
    assert evaluate_pick_result("1X2", "MS 2", hg=1, ag=1) is False

    # Away Win Scenarios (ag > hg)
    assert evaluate_pick_result("1X2", "MS 2", hg=0, ag=2) is True
    assert evaluate_pick_result("1X2", "MS2", hg=1, ag=3) is True
    assert evaluate_pick_result("1X2", "2", hg=0, ag=1) is True
    assert evaluate_pick_result("1X2", "AWAY", hg=2, ag=5) is True
    assert evaluate_pick_result("1X2", "MS 1", hg=0, ag=2) is False
    assert evaluate_pick_result("1X2", "MS X", hg=0, ag=2) is False


# =====================================================================
# 2. OVER / UNDER (TOTAL GOALS) MARKET SETTLEMENT E2E
# =====================================================================

def test_over_under_market_settlement_all_variations():
    """Verify Over/Under 2.5 goals market evaluates correctly across Turkish and English tokens."""
    # Over 2.5 goals (hg + ag >= 3)
    assert evaluate_pick_result("2.5 Gol", "2.5 ÜST", hg=2, ag=1) is True
    assert evaluate_pick_result("2.5 Gol", "2.5 UST", hg=3, ag=0) is True
    assert evaluate_pick_result("Total Goals 2.5", "OVER 2.5", hg=2, ag=2) is True
    assert evaluate_pick_result("2.5 Gol", "> 2.5", hg=1, ag=3) is True

    # Under 2.5 goals on high-scoring matches must evaluate to False
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=2, ag=1) is False
    assert evaluate_pick_result("2.5 Gol", "2.5 UNDER", hg=4, ag=0) is False

    # Under 2.5 goals (hg + ag <= 2)
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=1, ag=1) is True
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=0, ag=0) is True
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=1, ag=0) is True
    assert evaluate_pick_result("2.5 Gol", "2.5 ALT", hg=0, ag=2) is True
    assert evaluate_pick_result("Total Goals 2.5", "UNDER 2.5", hg=0, ag=1) is True
    assert evaluate_pick_result("2.5 Gol", "< 2.5", hg=1, ag=0) is True

    # Over 2.5 goals on low-scoring matches must evaluate to False
    assert evaluate_pick_result("2.5 Gol", "2.5 ÜST", hg=1, ag=1) is False
    assert evaluate_pick_result("2.5 Gol", "2.5 ÜST", hg=0, ag=0) is False


# =====================================================================
# 3. TOTAL GOALS 6+ (TG 6+) MARKET SETTLEMENT E2E
# =====================================================================

def test_total_goals_6_plus_market_settlement():
    """Verify TG 6+ market resolves True only when total match goals >= 6."""
    # Winning cases (sum >= 6)
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=4, ag=2) is True  # 6 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=3, ag=3) is True  # 6 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=5, ag=2) is True  # 7 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=0, ag=6) is True  # 6 goals
    assert evaluate_pick_result("Total Goals", "6+", hg=6, ag=1) is True  # 7 goals

    # Losing cases (sum < 6)
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=3, ag=2) is False  # 5 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=2, ag=2) is False  # 4 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=0, ag=0) is False  # 0 goals
    assert evaluate_pick_result("TG_6+", "TG 6+", hg=1, ag=4) is False  # 5 goals


# =====================================================================
# 4. HT/FT (HALF-TIME / FULL-TIME) 9-GRID & LINESCORES E2E
# =====================================================================

def test_htft_nine_grid_exhaustive_settlement():
    """Verify all 9 possible combinations of HT/FT outcomes with exact linescores."""
    nine_grid = [
        # (name, ht_hg, ht_ag, ft_hg, ft_ag, expected_token)
        ("1/1", 1, 0, 2, 0, "1/1"),
        ("1/X", 1, 0, 1, 1, "1/X"),
        ("1/2", 1, 0, 1, 2, "1/2"),
        ("X/1", 0, 0, 2, 1, "X/1"),
        ("X/X", 1, 1, 1, 1, "X/X"),
        ("X/2", 0, 0, 0, 1, "X/2"),
        ("2/1", 0, 1, 3, 1, "2/1"),
        ("2/X", 0, 2, 2, 2, "2/X"),
        ("2/2", 0, 1, 1, 2, "2/2"),
    ]

    for target_token, ht_h, ht_a, ft_h, ft_a, _expected in nine_grid:
        # Expected token must evaluate to True
        assert evaluate_pick_result(
            market="HT_FT",
            selection=target_token,
            hg=ft_h,
            ag=ft_a,
            ht_hg=ht_h,
            ht_ag=ht_a,
        ) is True, f"Failed positive evaluation for {target_token}"

        # All other 8 tokens must evaluate to False
        for other_token, _, _, _, _, _ in nine_grid:
            if other_token != target_token:
                assert evaluate_pick_result(
                    market="HT_FT",
                    selection=other_token,
                    hg=ft_h,
                    ag=ft_a,
                    ht_hg=ht_h,
                    ht_ag=ht_a,
                ) is False, f"False positive for {other_token} on {target_token} outcome"


def test_htft_descriptive_token_labels():
    """Verify HT/FT regex correctly parses descriptive token labels."""
    # Label format e.g. "X/2 (İY 0 / MS 2)"
    assert evaluate_pick_result(
        "HT_FT",
        "X/2 (İY 0 / MS 2)",
        hg=0,
        ag=1,
        ht_hg=0,
        ht_ag=0,
    ) is True

    assert evaluate_pick_result(
        "HT_FT",
        "1/1 (İY 1 / MS 1)",
        hg=3,
        ag=0,
        ht_hg=1,
        ht_ag=0,
    ) is True

    assert evaluate_pick_result(
        "HT_FT",
        "2/1 (İY 0-1 / MS 2-1)",
        hg=2,
        ag=1,
        ht_hg=0,
        ht_ag=1,
    ) is True


def test_htft_fail_closed_on_missing_linescores():
    """Verify that if half-time linescores are missing (None), HT/FT fails closed to False."""
    assert evaluate_pick_result("HT_FT", "1/1", hg=2, ag=0, ht_hg=None, ht_ag=None) is False
    assert evaluate_pick_result("HT_FT", "X/1", hg=2, ag=1, ht_hg=None, ht_ag=0) is False
    assert evaluate_pick_result("HT_FT", "2/2", hg=0, ag=2, ht_hg=0, ht_ag=None) is False


# =====================================================================
# 5. MULTI-LEG SYSTEM PARLAY BETS (SYSTEM 1,2,3 & SYSTEM 2,3)
# =====================================================================

def test_combinatoric_system_1_2_3_payouts():
    """Verify combinatoric payout calculation for System 1,2,3 across won legs count."""
    picks = [
        {"odds": 2.0, "status": "WON"},
        {"odds": 3.0, "status": "WON"},
        {"odds": 4.0, "status": "WON"},
    ]
    misli = 8.0

    # 0 won picks: 0.0 TL
    assert calculate_system_payout([], (1, 2, 3), misli=misli) == 0.0

    # 1 won pick (odds 2.0):
    # Combos length 1: (2.0) * 8.0 = 16.0 TL
    assert calculate_system_payout([picks[0]], (1, 2, 3), misli=misli) == 16.0

    # 2 won picks (odds 2.0 and 3.0):
    # Length 1: (2.0 + 3.0) * 8.0 = 40.0 TL
    # Length 2: (2.0 * 3.0) * 8.0 = 48.0 TL
    # Total: 40.0 + 48.0 = 88.0 TL
    assert calculate_system_payout([picks[0], picks[1]], (1, 2, 3), misli=misli) == 88.0

    # 3 won picks (odds 2.0, 3.0, 4.0):
    # Length 1: (2 + 3 + 4) * 8 = 72.0
    # Length 2: (2*3 + 2*4 + 3*4) * 8 = (6 + 8 + 12) * 8 = 208.0
    # Length 3: (2 * 3 * 4) * 8 = 24 * 8 = 192.0
    # Total: 72.0 + 208.0 + 192.0 = 472.0 TL
    assert calculate_system_payout(picks, (1, 2, 3), misli=misli) == 472.0


def test_combinatoric_system_2_3_payouts():
    """Verify combinatoric payout calculation for System 2,3 across won legs count."""
    picks = [
        {"odds": 3.0, "status": "WON"},
        {"odds": 4.0, "status": "WON"},
        {"odds": 5.0, "status": "WON"},
    ]
    misli = 11.0

    # 0 or 1 won pick: System 2,3 requires at least 2 legs to win -> 0.0 TL
    assert calculate_system_payout([], (2, 3), misli=misli) == 0.0
    assert calculate_system_payout([picks[0]], (2, 3), misli=misli) == 0.0

    # 2 won picks (odds 3.0 and 4.0):
    # Combos length 2: (3.0 * 4.0) * 11 = 132.0 TL
    assert calculate_system_payout([picks[0], picks[1]], (2, 3), misli=misli) == 132.0

    # 3 won picks (odds 3.0, 4.0, 5.0):
    # Combos length 2: (3*4 + 3*5 + 4*5) * 11 = (12 + 15 + 20) * 11 = 517.0 TL
    # Combos length 3: (3 * 4 * 5) * 11 = 60 * 11 = 660.0 TL
    # Total: 517.0 + 660.0 = 1177.0 TL
    assert calculate_system_payout(picks, (2, 3), misli=misli) == 1177.0


# =====================================================================
# 6. FULL MULTI-STAGE SETTLEMENT CYCLE & BANKROLL CONSERVATION PROOF
# =====================================================================

def test_full_e2e_settlement_cycle_and_bankroll_invariants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Execute complete end-to-end multi-coupon settlement simulation in an isolated sandbox.

    Proves:
    1. Simultaneous evaluation of Accumulator, System 1,2,3 (TG 6+), and System 2,3 (HT/FT).
    2. Bankroll balance conservation: total_portfolio_value == cash_balance + active_stakes.
    3. Mathematical correctness of realized PnL: realized_pnl == total_won_payouts - total_settled_stakes.
    4. Exact ticket status transitions: ALL_IN_PLAY -> PARTIALLY_SETTLED -> ALL_SETTLED.
    """
    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"

    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll_file)
    monkeypatch.setattr("live_settlement_engine.send_telegram_message", lambda *args, **kwargs: True)

    # 3 Active Coupons mirroring production architecture
    initial_coupons = [
        # Coupon 1: ACCUMULATOR (Tier 1 Kasa Kalkanı - 2 1X2 legs)
        {
            "id": "c1_shield",
            "name": "Kasa Kalkanı",
            "type": "ACCUMULATOR",
            "stake": 50.0,
            "potential_return": 147.0,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Team A vs Team B",
                    "home": "Team A",
                    "away": "Team B",
                    "league_key": "fra.1",
                    "market": "1X2",
                    "selection": "MS 1",
                    "odds": 1.67,
                    "status": "PENDING",
                },
                {
                    "match": "Team C vs Team D",
                    "home": "Team C",
                    "away": "Team D",
                    "league_key": "esp.1",
                    "market": "1X2",
                    "selection": "MS 1",
                    "odds": 1.76,
                    "status": "PENDING",
                },
            ],
        },
        # Coupon 2: SYSTEM_1_2_3 (TG 6+ Sistem - 3 legs)
        {
            "id": "c2_tg6",
            "name": "TG 6+ Sistem",
            "type": "SYSTEM_1_2_3",
            "stake": 56.0,
            "misli": 8,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Team A vs Team B",
                    "home": "Team A",
                    "away": "Team B",
                    "league_key": "fra.1",
                    "market": "TG_6+",
                    "selection": "TG 6+",
                    "odds": 6.72,
                    "status": "PENDING",
                },
                {
                    "match": "Team C vs Team D",
                    "home": "Team C",
                    "away": "Team D",
                    "league_key": "esp.1",
                    "market": "TG_6+",
                    "selection": "TG 6+",
                    "odds": 11.6,
                    "status": "PENDING",
                },
                {
                    "match": "Team E vs Team F",
                    "home": "Team E",
                    "away": "Team F",
                    "league_key": "por.1",
                    "market": "TG_6+",
                    "selection": "TG 6+",
                    "odds": 15.8,
                    "status": "PENDING",
                },
            ],
        },
        # Coupon 3: SYSTEM_2_3 (İY/MS Sistem - 3 legs)
        {
            "id": "c3_htft",
            "name": "İY/MS Sistem",
            "type": "SYSTEM_2_3",
            "stake": 44.0,
            "misli": 11,
            "status": "PENDING",
            "payout": 0.0,
            "picks": [
                {
                    "match": "Team G vs Team H",
                    "home": "Team G",
                    "away": "Team H",
                    "league_key": "bra.1",
                    "market": "HT_FT",
                    "selection": "2/2",
                    "odds": 8.81,
                    "status": "PENDING",
                },
                {
                    "match": "Team A vs Team B",
                    "home": "Team A",
                    "away": "Team B",
                    "league_key": "fra.1",
                    "market": "HT_FT",
                    "selection": "X/1",
                    "odds": 4.96,
                    "status": "PENDING",
                },
                {
                    "match": "Team C vs Team D",
                    "home": "Team C",
                    "away": "Team D",
                    "league_key": "esp.1",
                    "market": "HT_FT",
                    "selection": "X/1",
                    "odds": 4.77,
                    "status": "PENDING",
                },
            ],
        },
    ]
    test_coupons_file.write_text(json.dumps(initial_coupons), encoding="utf-8")

    # Initial Bankroll Ledger (150.0 TL all staked across 3 coupons)
    initial_bankroll = {
        "currency": "TL",
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "active_tickets_count": 3,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(json.dumps(initial_bankroll), encoding="utf-8")

    # --- STAGE 1: Matches for Coupon 1 conclude (Team A & Team C win) ---
    # Team A vs Team B: FT 2-0, HT 0-0 (Outcome: 1X2 WON, TG6 LOST, HT/FT X/1 WON)
    # Team C vs Team D: FT 2-1, HT 0-1 (Outcome: 1X2 WON, TG6 LOST, HT/FT 2/1 != X/1 LOST)
    # Team E vs Team F: Still In Progress
    # Team G vs Team H: Still In Progress

    def mock_espn_stage_1(league_key, *args):
        if league_key == "fra.1":
            return [{
                "name": "Team A vs Team B",
                "league": "fra.1",
                "home": "Team A",
                "away": "Team B",
                "hg": 2,
                "ag": 0,
                "ht_hg": 0,
                "ht_ag": 0,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        elif league_key == "esp.1":
            return [{
                "name": "Team C vs Team D",
                "league": "esp.1",
                "home": "Team C",
                "away": "Team D",
                "hg": 2,
                "ag": 1,
                "ht_hg": 0,
                "ht_ag": 1,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        elif league_key == "por.1":
            return [{
                "name": "Team E vs Team F",
                "league": "por.1",
                "home": "Team E",
                "away": "Team F",
                "hg": 1,
                "ag": 0,
                "status": "1st Half",
                "is_completed": False,
                "is_in_progress": True,
            }]
        elif league_key == "bra.1":
            return [{
                "name": "Team G vs Team H",
                "league": "bra.1",
                "home": "Team G",
                "away": "Team H",
                "hg": 0,
                "ag": 0,
                "status": "Scheduled",
                "is_completed": False,
                "is_in_progress": False,
            }]
        return []

    monkeypatch.setattr("live_settlement_engine.fetch_espn_scores", mock_espn_stage_1)

    res_1 = run_settlement_cycle()

    # Coupon 1 settled: Both 1X2 picks WON -> Payout = 147.0 TL
    assert res_1["settled_coupons"] == 1
    assert res_1["new_winnings"] == 147.0

    b1 = load_bankroll()
    # Invariant checks after Stage 1
    assert b1["cash_balance"] == 147.0
    assert b1["active_tickets_count"] == 2  # c2_tg6 and c3_htft still active
    assert b1["settled_tickets_count"] == 1  # c1_shield settled
    # Active stakes: c2 (56.0) + c3 (44.0) = 100.0 TL
    # Total portfolio value = cash (147.0) + active stakes (100.0) = 247.0 TL
    assert b1["total_portfolio_value"] == 247.0
    # Realized PnL: won (147.0) - stake of settled coupon (50.0) = +97.0 TL
    assert b1["realized_pnl"] == 97.0
    assert b1["status"] == "PARTIALLY_SETTLED"

    # --- STAGE 2: Remaining matches conclude ---
    # Team E vs Team F: FT 4-3 (TG 6+ WON!)
    # Team G vs Team H: FT 0-2, HT 0-1 (HT/FT 2/2 WON!)

    def mock_espn_stage_2(league_key, *args):
        if league_key == "fra.1":
            return [{
                "name": "Team A vs Team B",
                "league": "fra.1",
                "home": "Team A",
                "away": "Team B",
                "hg": 2,
                "ag": 0,
                "ht_hg": 0,
                "ht_ag": 0,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        elif league_key == "esp.1":
            return [{
                "name": "Team C vs Team D",
                "league": "esp.1",
                "home": "Team C",
                "away": "Team D",
                "hg": 2,
                "ag": 1,
                "ht_hg": 0,
                "ht_ag": 1,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        elif league_key == "por.1":
            return [{
                "name": "Team E vs Team F",
                "league": "por.1",
                "home": "Team E",
                "away": "Team F",
                "hg": 4,
                "ag": 3,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        elif league_key == "bra.1":
            return [{
                "name": "Team G vs Team H",
                "league": "bra.1",
                "home": "Team G",
                "away": "Team H",
                "hg": 0,
                "ag": 2,
                "ht_hg": 0,
                "ht_ag": 1,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }]
        return []

    monkeypatch.setattr("live_settlement_engine.fetch_espn_scores", mock_espn_stage_2)

    res_2 = run_settlement_cycle()

    # In Coupon 2 (System 1,2,3):
    # Leg 1 (Team A): 2-0 -> LOST
    # Leg 2 (Team C): 2-1 -> LOST
    # Leg 3 (Team E): 4-3 (7 goals) -> WON (odds 15.8)
    # Won picks = 1 leg. In System 1,2,3 with misli 8:
    # Length 1 combos payout = 15.8 * 8 = 126.40 TL

    # In Coupon 3 (System 2,3):
    # Leg 1 (Team G): HT 0-1, FT 0-2 -> 2/2 WON (odds 8.81)
    # Leg 2 (Team A): HT 0-0, FT 2-0 -> X/1 WON (odds 4.96)
    # Leg 3 (Team C): HT 0-1, FT 2-1 -> 2/1 != X/1 LOST
    # Won picks = 2 legs. In System 2,3 with misli 11:
    # Length 2 combo payout = (8.81 * 4.96) * 11 = 43.6976 * 11 = 480.67 TL

    expected_c2_payout = round(15.8 * 8.0, 2)  # 126.40
    expected_c3_payout = round((8.81 * 4.96) * 11.0, 2)  # 480.67
    expected_stage_2_winnings = expected_c2_payout + expected_c3_payout  # 607.07

    assert res_2["settled_coupons"] == 2
    assert pytest.approx(res_2["new_winnings"], abs=0.05) == expected_stage_2_winnings

    b2 = load_bankroll()
    # Invariant checks after Stage 2 (ALL coupons concluded)
    assert b2["active_tickets_count"] == 0
    assert b2["settled_tickets_count"] == 3
    assert b2["status"] == "ALL_SETTLED"

    # Total Cash = 147.0 + 126.40 + 480.67 = 754.07
    total_expected_cash = round(147.0 + expected_stage_2_winnings, 2)
    assert pytest.approx(b2["cash_balance"], abs=0.05) == total_expected_cash

    # Zero active stakes -> total_portfolio_value == cash_balance
    assert pytest.approx(b2["total_portfolio_value"], abs=0.05) == b2["cash_balance"]

    # Realized PnL = total payouts won (754.07) - total stakes (150.0) = +604.07 TL
    expected_pnl = round(total_expected_cash - 150.0, 2)
    assert pytest.approx(b2["realized_pnl"], abs=0.05) == expected_pnl

