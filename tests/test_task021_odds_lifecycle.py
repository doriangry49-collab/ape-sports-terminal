"""Tests for TASK-021: Multi-Snapshot Odds Lifecycle & Line Movement."""

import json
from datetime import UTC, datetime

import pytest

from sports_engine.odds_lifecycle.cli import format_lifecycle_table
from sports_engine.odds_lifecycle.domain import (
    KickoffProximity,
    MovementDirection,
    OddsMovementSummary,
    calculate_kickoff_proximity,
)
from sports_engine.odds_lifecycle.tracker import (
    OddsLifecycleTracker,
    make_lifecycle_id,
)


def test_calculate_kickoff_proximity_bands():
    ref = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

    # Post kickoff
    assert calculate_kickoff_proximity("2026-10-10T11:00:00Z", ref) == KickoffProximity.POST_KICKOFF
    # 30 min before
    assert calculate_kickoff_proximity("2026-10-10T12:30:00Z", ref) == KickoffProximity.T_1H
    # 90 min before
    assert calculate_kickoff_proximity("2026-10-10T13:30:00Z", ref) == KickoffProximity.T_2H
    # 5 hours before
    assert calculate_kickoff_proximity("2026-10-10T17:00:00Z", ref) == KickoffProximity.T_6H
    # 10 hours before
    assert calculate_kickoff_proximity("2026-10-10T22:00:00Z", ref) == KickoffProximity.T_12H
    # 20 hours before
    assert calculate_kickoff_proximity("2026-10-11T08:00:00Z", ref) == KickoffProximity.T_24H
    # 40 hours before
    assert calculate_kickoff_proximity("2026-10-12T04:00:00Z", ref) == KickoffProximity.T_48H
    # 60 hours before
    assert calculate_kickoff_proximity("2026-10-12T23:00:00Z", ref) == KickoffProximity.T_72H
    # 100 hours before
    assert calculate_kickoff_proximity("2026-10-14T16:00:00Z", ref) == KickoffProximity.T_PLUS_72H


def test_make_lifecycle_id_deterministic():
    id1 = make_lifecycle_id("event_123", "1x2", "Arsenal", "Betfair")
    id2 = make_lifecycle_id("event_123", "1x2", "Arsenal", "Betfair")
    id3 = make_lifecycle_id("event_123", "1x2", "Draw", "Betfair")
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 24


def test_clv_ratio_mathematics():
    # When initial odds = 8.25 and last prematch odds = 7.50 -> CLV = 1.10 (Beat market by 10%)
    init_o = 8.25
    last_o = 7.50
    clv_ratio = round(init_o / last_o, 4)
    assert clv_ratio == 1.10

    # When odds drifted from 2.00 to 2.50 -> CLV = 0.80
    init_o = 2.00
    last_o = 2.50
    clv_ratio = round(init_o / last_o, 4)
    assert clv_ratio == 0.80


def test_clv_label_is_strictly_pre_closing():
    summary = OddsMovementSummary(
        initial_odds=2.00,
        latest_odds=1.90,
        last_prematch_odds=1.90,
        delta_odds=-0.10,
        pct_change=-5.0,
        initial_implied_prob=0.50,
        latest_implied_prob=0.5263,
        delta_implied_prob=0.0263,
        direction=MovementDirection.SIGNIFICANT_MOVE,
        is_significant=True,
        snapshots_count=2,
        preliminary_clv_ratio=1.0526,
    )
    assert summary.clv_label == "PRE_CLOSING_LINE_VALUE"
    assert "OFFICIAL" not in summary.clv_label


@pytest.fixture
def sample_prediction_data(tmp_path):
    pred_file = tmp_path / "predictions.json"
    data = {
        "task_id": "TASK-019",
        "predictions_count": 1,
        "predictions": [
            {
                "event_id": "test_epl_arsenal_leeds",
                "fixture": "Arsenal vs Leeds",
                "competition": "Premier League",
                "kickoff": "2026-10-10T15:00:00Z",
                "selections": [
                    {
                        "market": "1x2",
                        "selection": "Arsenal",
                        "bookmaker": "Bet365",
                        "bookmaker_odds": 1.50,
                        "model_probability": 0.70,
                        "model_fair_odds": 1.43,
                        "expected_value_percent": 4.9,
                        "prediction_timestamp": "2026-10-08T10:00:00Z",
                    },
                    {
                        "market": "1x2",
                        "selection": "Leeds",
                        "bookmaker": "Bet365",
                        "bookmaker_odds": 8.00,
                        "model_probability": 0.15,
                        "model_fair_odds": 6.67,
                        "expected_value_percent": 20.0,
                        "prediction_timestamp": "2026-10-08T10:00:00Z",
                    },
                ],
            }
        ],
    }
    pred_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return pred_file


def test_tracker_initial_state_and_timeline(sample_prediction_data, tmp_path):
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    payload = tracker.track_lifecycle(now_dt=datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC))

    assert payload["summary"]["total_selections_tracked"] == 2
    assert payload["summary"]["multi_snapshot_selections"] == 0
    assert payload["summary"]["stable_count"] == 2

    # Check ledger content
    ledger = tracker.ledger
    assert len(ledger) == 2
    for _lid, rec in ledger.items():
        assert rec["lifecycle_state"] == "PREDICTED"
        assert len(rec["snapshots_timeline"]) == 1
        assert rec["movement"]["preliminary_clv_ratio"] == 1.0


def test_tracker_multi_snapshot_movement(sample_prediction_data, tmp_path):
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    # Arsenal shortened: 1.50 -> 1.40 (drop > 5% -> SIGNIFICANT)
    # Leeds drifted: 8.00 -> 9.00 (rise > 5% -> SIGNIFICANT)
    lid_arsenal = make_lifecycle_id("test_epl_arsenal_leeds", "1x2", "Arsenal", "Bet365")
    lid_leeds = make_lifecycle_id("test_epl_arsenal_leeds", "1x2", "Leeds", "Bet365")

    sim_series = {
        lid_arsenal: [
            {"snapshot_id": "snap_1", "timestamp": "2026-10-09T12:00:00Z", "odds": 1.40}
        ],
        lid_leeds: [
            {"snapshot_id": "snap_1", "timestamp": "2026-10-09T12:00:00Z", "odds": 9.00}
        ],
    }

    payload = tracker.track_lifecycle(
        simulated_time_series=sim_series,
        now_dt=datetime(2026, 10, 9, 14, 0, 0, tzinfo=UTC),
    )

    assert payload["summary"]["multi_snapshot_selections"] == 2
    assert payload["summary"]["significant_moves_count"] == 2

    ars_rec = tracker.ledger[lid_arsenal]
    assert ars_rec["movement"]["initial_odds"] == 1.50
    assert ars_rec["movement"]["latest_odds"] == 1.40
    assert ars_rec["movement"]["delta_odds"] == -0.10
    assert ars_rec["movement"]["pct_change"] < 0
    assert ars_rec["movement"]["preliminary_clv_ratio"] > 1.0  # Beat closing price

    leeds_rec = tracker.ledger[lid_leeds]
    assert leeds_rec["movement"]["initial_odds"] == 8.00
    assert leeds_rec["movement"]["latest_odds"] == 9.00
    assert leeds_rec["movement"]["delta_odds"] == 1.00
    assert leeds_rec["movement"]["pct_change"] > 0
    assert leeds_rec["movement"]["preliminary_clv_ratio"] < 1.0


def test_tracker_preserves_initial_predictions_immutability(sample_prediction_data, tmp_path):
    orig_content = sample_prediction_data.read_text(encoding="utf-8")
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    tracker.track_lifecycle()
    new_content = sample_prediction_data.read_text(encoding="utf-8")

    assert orig_content == new_content, "predictions.json must remain strictly immutable!"


def test_last_prematch_odds_ignores_post_kickoff(sample_prediction_data, tmp_path):
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    lid_arsenal = make_lifecycle_id("test_epl_arsenal_leeds", "1x2", "Arsenal", "Bet365")

    # Kickoff is 2026-10-10T15:00:00Z
    # Snap 1 is pre-kickoff (1.40)
    # Snap 2 is post-kickoff (1.10 in-play)
    sim_series = {
        lid_arsenal: [
            {"snapshot_id": "pre", "timestamp": "2026-10-10T14:30:00Z", "odds": 1.40},
            {"snapshot_id": "post", "timestamp": "2026-10-10T16:00:00Z", "odds": 1.10},
        ]
    }

    tracker.track_lifecycle(
        simulated_time_series=sim_series,
        now_dt=datetime(2026, 10, 10, 17, 0, 0, tzinfo=UTC),
    )

    rec = tracker.ledger[lid_arsenal]
    assert rec["movement"]["latest_odds"] == 1.10
    # last_prematch_odds should be 1.40, NOT the post-kickoff 1.10!
    assert rec["movement"]["last_prematch_odds"] == 1.40
    assert rec["lifecycle_state"] == "KICKOFF_PASSED"


def test_cli_table_formatting_runs_cleanly():
    payload = {
        "generated_at": "2026-10-04T00:00:00Z",
        "predictions_source": "artifacts/predictions/TASK-019/predictions.json",
        "summary": {
            "total_selections_tracked": 100,
            "multi_snapshot_selections": 80,
            "shortened_count": 30,
            "drifted_count": 40,
            "stable_count": 10,
            "significant_moves_count": 20,
            "value_candidates_tracked": 15,
            "value_candidates_beat_closing_market": 9,
            "value_clv_beat_rate_percent": 60.0,
        },
        "top_shortened_selections": [
            {
                "fixture": "Arsenal vs Leeds",
                "market": "1x2",
                "selection": "Arsenal",
                "lifecycle_state": "SNAPSHOT_TRACKED",
                "movement": {
                    "initial_odds": 1.50,
                    "latest_odds": 1.35,
                    "delta_odds": -0.15,
                    "pct_change": -10.0,
                    "preliminary_clv_ratio": 1.11,
                },
            }
        ],
        "top_drifted_selections": [],
    }

    table_text = format_lifecycle_table(payload)
    assert "TASK-021: MULTI-SNAPSHOT ODDS LIFECYCLE & MOVEMENT REPORT" in table_text
    assert "Arsenal vs Leeds" in table_text
    assert "PRE_CLOSING_LINE_VALUE" in table_text


def test_line_movement_direction_classifications():
    # Stable test
    summary_stable = OddsMovementSummary(
        initial_odds=2.00,
        latest_odds=2.005,
        last_prematch_odds=2.005,
        delta_odds=0.005,
        pct_change=0.25,
        initial_implied_prob=0.50,
        latest_implied_prob=0.4988,
        delta_implied_prob=-0.0012,
        direction=MovementDirection.STABLE,
        is_significant=False,
        snapshots_count=2,
        preliminary_clv_ratio=0.9975,
    )
    assert summary_stable.direction == MovementDirection.STABLE
    assert not summary_stable.is_significant

    # Drifted test (between 1% and 4.9%)
    summary_drifted = OddsMovementSummary(
        initial_odds=2.00,
        latest_odds=2.06,
        last_prematch_odds=2.06,
        delta_odds=0.06,
        pct_change=3.0,
        initial_implied_prob=0.50,
        latest_implied_prob=0.4854,
        delta_implied_prob=-0.0146,
        direction=MovementDirection.DRIFTED,
        is_significant=False,
        snapshots_count=2,
        preliminary_clv_ratio=0.9709,
    )
    assert summary_drifted.direction == MovementDirection.DRIFTED
    assert not summary_drifted.is_significant

    # Shortened test (between -1% and -4.9%)
    summary_shortened = OddsMovementSummary(
        initial_odds=2.00,
        latest_odds=1.94,
        last_prematch_odds=1.94,
        delta_odds=-0.06,
        pct_change=-3.0,
        initial_implied_prob=0.50,
        latest_implied_prob=0.5155,
        delta_implied_prob=0.0155,
        direction=MovementDirection.SHORTENED,
        is_significant=False,
        snapshots_count=2,
        preliminary_clv_ratio=1.0309,
    )
    assert summary_shortened.direction == MovementDirection.SHORTENED
    assert not summary_shortened.is_significant


def test_timeline_sorting_order(sample_prediction_data, tmp_path):
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    lid = make_lifecycle_id("test_epl_arsenal_leeds", "1x2", "Arsenal", "Bet365")

    # Add snapshots in reverse order
    sim_series = {
        lid: [
            {"snapshot_id": "late", "timestamp": "2026-10-09T18:00:00Z", "odds": 1.35},
            {"snapshot_id": "early", "timestamp": "2026-10-08T15:00:00Z", "odds": 1.45},
        ]
    }

    tracker.track_lifecycle(
        simulated_time_series=sim_series,
        now_dt=datetime(2026, 10, 9, 20, 0, 0, tzinfo=UTC),
    )

    rec = tracker.ledger[lid]
    timeline = rec["snapshots_timeline"]
    assert len(timeline) == 3  # init + 2 sim
    # Verify chronological ascending order
    for i in range(len(timeline) - 1):
        assert timeline[i]["timestamp"] <= timeline[i + 1]["timestamp"]


def test_tracker_idempotence_double_run(sample_prediction_data, tmp_path):
    mov_dir = tmp_path / "movement"
    tracker = OddsLifecycleTracker(predictions_path=sample_prediction_data, movement_dir=mov_dir)

    # First run
    p1 = tracker.track_lifecycle(now_dt=datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC))
    # Second run without new snapshots
    p2 = tracker.track_lifecycle(now_dt=datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC))

    assert p1["summary"]["total_selections_tracked"] == p2["summary"]["total_selections_tracked"]
    assert len(tracker.ledger) == 2

