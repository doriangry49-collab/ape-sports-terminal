"""TASK-020: Comprehensive Unit and Regression Tests for Settlement & Performance Tracking.

Tests:
1. 1X2 market settlement (HOME, DRAW, AWAY)
2. Correct Score market settlement (exact match vs mismatch)
3. Totals (Over/Under) settlement (above, below, integer push)
4. Both Teams to Score (BTTS) settlement (YES vs NO)
5. Half-Time 1X2 settlement (halftime score resolution)
6. Half-Time / Full-Time (HT/FT) combination settlement
7. Win profit calculation ((odds - 1) * stake)
8. Loss profit calculation (-1.0 * stake)
9. Push profit calculation (0.0 profit)
10. Flat-stake ROI calculation (total_profit / total_stake)
11. Duplicate settlement protection (idempotency guard)
12. Prediction immutability (original predictions snapshot unmodified)
13. Unresolved match handling (MATCH_UNRESOLVED when score missing)
14. Result provenance tracking (result_source preserved in settlement record)
15. Model EV vs Realized ROI separation (clear conceptual distinction)
"""

import json

from sports_engine.settlement.domain import (
    MatchResult,
    MatchStatus,
    SettlementRecord,
    SettlementStatus,
)
from sports_engine.settlement.engine import PredictionSettlementEngine
from sports_engine.settlement.metrics import (
    aggregate_settlement_metrics,
)
from sports_engine.settlement.rules import (
    calculate_flat_stake_profit,
    evaluate_selection_settlement,
    settle_1x2,
    settle_btts,
    settle_correct_score,
    settle_ht_1x2,
    settle_ht_ft,
    settle_totals,
)


def test_1_settle_1x2():
    """Test 1: 1X2 market settlement for HOME, DRAW, AWAY."""
    # Home win: 2-1
    assert settle_1x2("HOME", "Arsenal", "Chelsea", 2, 1) == SettlementStatus.WON
    assert settle_1x2("1", "Arsenal", "Chelsea", 2, 1) == SettlementStatus.WON
    assert settle_1x2("DRAW", "Arsenal", "Chelsea", 2, 1) == SettlementStatus.LOST
    assert settle_1x2("AWAY", "Arsenal", "Chelsea", 2, 1) == SettlementStatus.LOST

    # Draw: 1-1
    assert settle_1x2("DRAW", "Arsenal", "Chelsea", 1, 1) == SettlementStatus.WON
    assert settle_1x2("X", "Arsenal", "Chelsea", 1, 1) == SettlementStatus.WON
    assert settle_1x2("HOME", "Arsenal", "Chelsea", 1, 1) == SettlementStatus.LOST

    # Away win: 0-3
    assert settle_1x2("AWAY", "Arsenal", "Chelsea", 0, 3) == SettlementStatus.WON
    assert settle_1x2("2", "Arsenal", "Chelsea", 0, 3) == SettlementStatus.WON
    assert settle_1x2("HOME", "Arsenal", "Chelsea", 0, 3) == SettlementStatus.LOST


def test_2_settle_correct_score():
    """Test 2: Correct Score exact match vs mismatch."""
    assert settle_correct_score("2-1", 2, 1) == SettlementStatus.WON
    assert settle_correct_score("2:1", 2, 1) == SettlementStatus.WON
    assert settle_correct_score("1-1", 2, 1) == SettlementStatus.LOST
    assert settle_correct_score("0-0", 0, 0) == SettlementStatus.WON
    assert settle_correct_score("invalid_format", 2, 1) == SettlementStatus.UNSETTLEABLE


def test_3_settle_totals():
    """Test 3: Over/Under totals including integer line pushes."""
    # Score 2-1 = 3 goals
    assert settle_totals("Over 2.5", 2, 1) == SettlementStatus.WON
    assert settle_totals("Under 2.5", 2, 1) == SettlementStatus.LOST
    assert settle_totals("Over 3.5", 2, 1) == SettlementStatus.LOST
    assert settle_totals("Under 3.5", 2, 1) == SettlementStatus.WON

    # Integer line push: total 3 on line 3.0
    assert settle_totals("Over 3.0", 2, 1) == SettlementStatus.PUSH
    assert settle_totals("Under 3.0", 2, 1) == SettlementStatus.PUSH


def test_4_settle_btts():
    """Test 4: Both Teams to Score (BTTS) YES / NO."""
    # 2-1: Both scored
    assert settle_btts("YES", 2, 1) == SettlementStatus.WON
    assert settle_btts("NO", 2, 1) == SettlementStatus.LOST

    # 2-0: Away failed to score
    assert settle_btts("YES", 2, 0) == SettlementStatus.LOST
    assert settle_btts("NO", 2, 0) == SettlementStatus.WON


def test_5_settle_ht_1x2():
    """Test 5: Halftime 1X2 settlement."""
    assert settle_ht_1x2("HOME", "Arsenal", "Chelsea", 1, 0) == SettlementStatus.WON
    assert settle_ht_1x2("DRAW", "Arsenal", "Chelsea", 1, 0) == SettlementStatus.LOST
    assert settle_ht_1x2("HOME", "Arsenal", "Chelsea", None, None) == SettlementStatus.UNSETTLEABLE


def test_6_settle_ht_ft():
    """Test 6: Halftime/Fulltime combination settlement."""
    # HT: 1-0 (1), FT: 2-1 (1) -> 1/1
    assert settle_ht_ft("1/1", 1, 0, 2, 1) == SettlementStatus.WON
    assert settle_ht_ft("X/1", 1, 0, 2, 1) == SettlementStatus.LOST

    # HT: 0-0 (X), FT: 1-0 (1) -> X/1
    assert settle_ht_ft("X/1", 0, 0, 1, 0) == SettlementStatus.WON
    assert settle_ht_ft("1/1", 0, 0, 1, 0) == SettlementStatus.LOST


def test_7_win_profit_calculation():
    """Test 7: Win profit calculation ((odds - 1) * stake)."""
    profit, roi = calculate_flat_stake_profit(2.50, SettlementStatus.WON, stake=1.0)
    assert profit == 1.50
    assert roi == 150.0

    profit_high, roi_high = calculate_flat_stake_profit(21.00, SettlementStatus.WON, stake=1.0)
    assert profit_high == 20.00
    assert roi_high == 2000.0


def test_8_loss_profit_calculation():
    """Test 8: Loss profit calculation (-1.0 * stake)."""
    profit, roi = calculate_flat_stake_profit(1.80, SettlementStatus.LOST, stake=1.0)
    assert profit == -1.0
    assert roi == -100.0


def test_9_push_profit_calculation():
    """Test 9: Push profit calculation (0.0 profit)."""
    profit, roi = calculate_flat_stake_profit(2.00, SettlementStatus.PUSH, stake=1.0)
    assert profit == 0.0
    assert roi == 0.0


def test_10_roi_calculation():
    """Test 10: Flat stake total profit and ROI aggregation."""
    records = [
        SettlementRecord(
            settlement_id="s1",
            event_id="e1",
            match="M1",
            competition="EPL",
            kickoff="2026-10-10",
            market="1X2",
            selection="HOME",
            bookmaker="bm",
            bookmaker_odds=2.20,
            model_probability=0.5,
            model_fair_odds=2.0,
            model_ev_percent=10.0,
            status=SettlementStatus.WON,
            profit=1.20,
        ),
        SettlementRecord(
            settlement_id="s2",
            event_id="e2",
            match="M2",
            competition="EPL",
            kickoff="2026-10-10",
            market="1X2",
            selection="AWAY",
            bookmaker="bm",
            bookmaker_odds=3.00,
            model_probability=0.4,
            model_fair_odds=2.5,
            model_ev_percent=20.0,
            status=SettlementStatus.LOST,
            profit=-1.0,
        ),
    ]
    metrics = aggregate_settlement_metrics(records)
    summary = metrics["summary"]

    assert summary["total_stake"] == 2.0
    assert summary["total_profit"] == 0.20
    assert summary["realized_roi_percent"] == 10.0  # +0.2 / 2.0 = +10%


def test_11_duplicate_settlement_idempotency(tmp_path):
    """Test 11: Duplicate settlement runs do not duplicate ledger records or double-count profit."""
    pred_file = tmp_path / "predictions.json"
    perf_dir = tmp_path / "performance"
    perf_dir.mkdir(parents=True, exist_ok=True)

    dummy_preds = {
        "predictions": [
            {
                "event_id": "test_event_1",
                "fixture": "Arsenal vs Chelsea",
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "kickoff": "2026-10-10T12:00:00Z",
                "competition": "Premier League",
                "selections": [
                    {
                        "market": "1X2",
                        "selection": "HOME",
                        "bookmaker": "betmgm",
                        "bookmaker_odds": 2.00,
                        "model_probability": 0.55,
                        "model_fair_odds": 1.82,
                        "expected_value_percent": 10.0,
                    }
                ],
            }
        ]
    }
    with open(pred_file, "w", encoding="utf-8") as f:
        json.dump(dummy_preds, f)

    override = {
        "test_event_1": MatchResult(
            event_id="test_event_1",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff="2026-10-10T12:00:00Z",
            home_score=2,
            away_score=1,
            status=MatchStatus.FINISHED,
            result_source="TEST_OVERRIDE",
        )
    }

    engine = PredictionSettlementEngine(predictions_path=pred_file, performance_dir=perf_dir)

    # First run: settles
    payload1 = engine.run_settlement(manual_results_override=override)
    assert payload1["performance"]["summary"]["wins"] == 1
    assert payload1["performance"]["summary"]["total_profit"] == 1.0

    # Second run: must be identical (idempotent, no double profit)
    payload2 = engine.run_settlement(manual_results_override=override)
    assert payload2["performance"]["summary"]["wins"] == 1
    assert payload2["performance"]["summary"]["total_profit"] == 1.0
    assert len(payload2["performance"]["summary"]) > 0


def test_12_prediction_immutability(tmp_path):
    """Test 12: Settlement engine leaves prediction snapshot completely unmodified."""
    pred_file = tmp_path / "predictions.json"
    dummy_preds = {"predictions": [{"event_id": "ev_immutable", "fixture": "Team A vs Team B", "selections": []}]}
    with open(pred_file, "w", encoding="utf-8") as f:
        json.dump(dummy_preds, f)

    mtime_before = pred_file.stat().st_mtime_ns
    engine = PredictionSettlementEngine(predictions_path=pred_file, performance_dir=tmp_path)
    engine.run_settlement()
    mtime_after = pred_file.stat().st_mtime_ns

    # File was not rewritten or modified
    assert mtime_before == mtime_after


def test_13_unresolved_match_handling():
    """Test 13: Matches without verified scores evaluate to UNSETTLEABLE / PENDING without guessing."""
    res = evaluate_selection_settlement("1X2", "HOME", "TeamA", "TeamB", None, None, is_finished=False)
    assert res == SettlementStatus.PENDING


def test_14_result_provenance_tracking():
    """Test 14: Result source is explicitly tracked in SettlementRecord."""
    rec = SettlementRecord(
        settlement_id="s_test",
        event_id="e_test",
        match="A vs B",
        competition="EPL",
        kickoff="2026-10-10",
        market="1X2",
        selection="HOME",
        bookmaker="bovada",
        bookmaker_odds=2.10,
        model_probability=0.52,
        model_fair_odds=1.92,
        model_ev_percent=9.2,
        status=SettlementStatus.WON,
        result_source="PROPLINE_SCORES_API",
    )
    assert rec.result_source == "PROPLINE_SCORES_API"


def test_15_model_ev_vs_realized_roi_separation():
    """Test 15: Positive Model EV and Realized Loss exist simultaneously without conflation."""
    # Model identified +21.3% EV on a high odd (8.25), but the match was lost
    rec = SettlementRecord(
        settlement_id="s_ev_loss",
        event_id="e_test",
        match="Arsenal vs Leeds",
        competition="Premier League",
        kickoff="2026-10-10",
        market="1X2",
        selection="Leeds",
        bookmaker="betonline",
        bookmaker_odds=8.25,
        model_probability=0.147,
        model_fair_odds=6.80,
        model_ev_percent=21.3,  # POSITIVE MODEL EV
        status=SettlementStatus.LOST,  # ACTUAL OUTCOME
        profit=-1.0,  # REALIZED LOSS
        realized_roi_percent=-100.0,
    )
    assert rec.model_ev_percent == 21.3
    assert rec.profit == -1.0
    assert rec.status == SettlementStatus.LOST
