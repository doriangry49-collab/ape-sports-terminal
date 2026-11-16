"""Tests for TASK-022: Out-Of-Sample (OOS) Performance & Market Calibration Audit."""

import json

from sports_engine.oos_audit.auditor import OOSPerformanceAuditor, compute_binary_metrics
from sports_engine.oos_audit.cli import format_oos_audit_table
from sports_engine.oos_audit.domain import AuditStatus, SegmentStatus


def test_compute_binary_metrics_exact_math():
    records = [
        {"status": "WON", "model_probability": 0.80, "bookmaker_odds": 1.25},  # mod p=0.8, mkt p=0.8
        {"status": "LOST", "model_probability": 0.20, "bookmaker_odds": 5.00}, # mod p=0.2, mkt p=0.2
    ]
    # For WON: (0.8 - 1)^2 = 0.04. For LOST: (0.2 - 0)^2 = 0.04. Mean Brier = 0.04
    mod_brier, mkt_brier, mod_ll, mkt_ll = compute_binary_metrics(records)
    assert mod_brier == 0.04
    assert mkt_brier == 0.04
    assert mod_ll is not None
    assert mkt_ll is not None


def test_compute_binary_metrics_ignores_push():
    records = [
        {"status": "PUSH", "model_probability": 0.50, "bookmaker_odds": 2.00},
        {"status": "WON", "model_probability": 0.70, "bookmaker_odds": 1.40},
    ]
    mod_brier, mkt_brier, _, _ = compute_binary_metrics(records)
    # Only WON record evaluated: (0.7 - 1)^2 = 0.09
    assert mod_brier == 0.09


def test_independent_events_clustering():
    # 10 selections belonging to only 2 unique matches
    records = [
        {"event_id": "match_1", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 5.0},
        {"event_id": "match_1", "status": "LOST", "stake": 1.0, "profit": -1.0, "bookmaker_odds": 3.0, "model_ev_percent": 5.0},
        {"event_id": "match_1", "status": "LOST", "stake": 1.0, "profit": -1.0, "bookmaker_odds": 4.0, "model_ev_percent": 5.0},
        {"event_id": "match_2", "status": "WON", "stake": 1.0, "profit": 2.0, "bookmaker_odds": 3.0, "model_ev_percent": 5.0},
        {"event_id": "match_2", "status": "LOST", "stake": 1.0, "profit": -1.0, "bookmaker_odds": 5.0, "model_ev_percent": 5.0},
    ]

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=5)
    report = auditor.audit(settled_records_override=records)

    overall = report.segments["All Selections"]
    assert overall.raw_selections_count == 5
    assert overall.independent_events_count == 2
    # Since 2 < threshold 5, it MUST be flagged INSUFFICIENT_SAMPLE
    assert overall.status == SegmentStatus.INSUFFICIENT_SAMPLE


def test_sample_sufficiency_threshold():
    # Create 12 unique matches
    records = [
        {
            "event_id": f"unique_match_{i}",
            "status": "WON" if i % 2 == 0 else "LOST",
            "stake": 1.0,
            "profit": 1.0 if i % 2 == 0 else -1.0,
            "bookmaker_odds": 2.0,
            "model_ev_percent": 2.0,
        }
        for i in range(12)
    ]

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=10)
    report = auditor.audit(settled_records_override=records)

    overall = report.segments["All Selections"]
    assert overall.independent_events_count == 12
    assert overall.status == SegmentStatus.SUFFICIENT_SAMPLE


def test_no_data_segment_handling():
    # Records with odds only up to 3.0
    records = [
        {"event_id": "m1", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 1.0}
    ]

    auditor = OOSPerformanceAuditor()
    report = auditor.audit(settled_records_override=records)

    high_odds = report.segments["Odds >= 50.0"]
    assert high_odds.status == SegmentStatus.NO_DATA
    assert high_odds.raw_selections_count == 0
    assert high_odds.model_brier_score is None


def test_awaiting_kickoff_status_when_all_pending(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    data = {
        "s1": {"event_id": "e1", "status": "PENDING", "bookmaker_odds": 2.0, "model_ev_percent": 4.0},
        "s2": {"event_id": "e2", "status": "PENDING", "bookmaker_odds": 3.0, "model_ev_percent": 2.0},
    }
    ledger_path.write_text(json.dumps(data), encoding="utf-8")

    auditor = OOSPerformanceAuditor(settlement_ledger_path=ledger_path)
    report = auditor.audit()

    assert report.audit_status == AuditStatus.AWAITING_KICKOFF_AND_SETTLEMENT
    assert report.total_settled_records == 0
    assert report.total_pending_records == 2
    assert "Zero synthetic match scores generated" in report.summary_findings[1]


def test_ev_segmentation():
    records = [
        {"event_id": "m1", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 2.0},
        {"event_id": "m2", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 6.0},
        {"event_id": "m3", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 12.0},
        {"event_id": "m4", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 25.0},
    ]

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(settled_records_override=records)

    assert report.segments["EV > 0%"].raw_selections_count == 4
    assert report.segments["EV > 5%"].raw_selections_count == 3
    assert report.segments["EV > 10%"].raw_selections_count == 2
    assert report.segments["EV > 20%"].raw_selections_count == 1


def test_odds_bands_segmentation():
    records = [
        {"event_id": "m1", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.5},
        {"event_id": "m2", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 6.0},
        {"event_id": "m3", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 15.0},
        {"event_id": "m4", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 25.0},
        {"event_id": "m5", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 60.0},
        {"event_id": "m6", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 120.0},
    ]

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(settled_records_override=records)

    assert report.segments["Odds >= 2.0"].raw_selections_count == 6
    assert report.segments["Odds >= 5.0"].raw_selections_count == 5
    assert report.segments["Odds >= 10.0"].raw_selections_count == 4
    assert report.segments["Odds >= 20.0"].raw_selections_count == 3
    assert report.segments["Odds >= 50.0"].raw_selections_count == 2
    assert report.segments["Odds >= 100.0"].raw_selections_count == 1


def test_market_families_segmentation():
    records = [
        {"event_id": "m1", "market": "1x2", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0},
        {"event_id": "m2", "market": "totals", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0},
        {"event_id": "m3", "market": "btts", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0},
        {"event_id": "m4", "market": "correct_score", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0},
        {"event_id": "m5", "market": "ht_ft", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0},
    ]

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(settled_records_override=records)

    assert report.segments["Market: 1X2"].raw_selections_count == 1
    assert report.segments["Market: Totals"].raw_selections_count == 1
    assert report.segments["Market: BTTS"].raw_selections_count == 1
    assert report.segments["Market: Correct Score"].raw_selections_count == 1
    assert report.segments["Market: HT/FT"].raw_selections_count == 1


def test_brier_advantage_calculation():
    # Model assigns 0.90 to WON (accurate). Market assigns 0.50 (inaccurate).
    records = [
        {"status": "WON", "model_probability": 0.90, "bookmaker_odds": 2.00},
    ]
    # Model Brier = (0.9 - 1)^2 = 0.01
    # Market Brier = (0.5 - 1)^2 = 0.25
    # Brier advantage = Market - Model = 0.25 - 0.01 = +0.24 (Model wins!)
    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(settled_records_override=records)

    overall = report.segments["All Selections"]
    assert overall.model_brier_score == 0.01
    assert overall.market_brier_score == 0.25
    assert overall.brier_advantage == 0.24


def test_cli_table_formatting_runs_cleanly():
    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    records = [
        {"event_id": "m1", "market": "1x2", "status": "WON", "stake": 1.0, "profit": 1.0, "bookmaker_odds": 2.0, "model_ev_percent": 5.0}
    ]
    report = auditor.audit(settled_records_override=records)
    table_str = format_oos_audit_table(report)
    assert "TASK-022: OUT-OF-SAMPLE (OOS) PERFORMANCE" in table_str
    assert "All Selections" in table_str


def test_model_and_movement_alignment_segmentation():
    records = [
        {
            "event_id": "m1",
            "market": "1x2",
            "selection": "Arsenal",
            "bookmaker": "Bet365",
            "status": "WON",
            "stake": 1.0,
            "profit": 1.5,
            "bookmaker_odds": 2.5,
            "model_ev_percent": 10.0,
        },
        {
            "event_id": "m2",
            "market": "1x2",
            "selection": "Chelsea",
            "bookmaker": "Bet365",
            "status": "LOST",
            "stake": 1.0,
            "profit": -1.0,
            "bookmaker_odds": 3.0,
            "model_ev_percent": 8.0,
        },
    ]

    lifecycle = {
        "l1": {
            "event_id": "m1",
            "market": "1x2",
            "selection": "Arsenal",
            "bookmaker": "Bet365",
            "movement": {"direction": "SHORTENED", "delta_odds": -0.20},
        },
        "l2": {
            "event_id": "m2",
            "market": "1x2",
            "selection": "Chelsea",
            "bookmaker": "Bet365",
            "movement": {"direction": "DRIFTED", "delta_odds": 0.30},
        },
    }

    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(
        settled_records_override=records,
        lifecycle_ledger_override=lifecycle,
    )

    shortened_seg = report.segments["Model EV > 0 & Pre-Closing Shortened"]
    drifted_seg = report.segments["Model EV > 0 & Pre-Closing Drifted"]

    assert shortened_seg.raw_selections_count == 1
    assert shortened_seg.won_count == 1
    assert drifted_seg.raw_selections_count == 1
    assert drifted_seg.lost_count == 1


def test_log_loss_advantage_computation():
    records = [
        {"status": "WON", "model_probability": 0.95, "bookmaker_odds": 1.50},  # mkt prob = 0.6667
        {"status": "LOST", "model_probability": 0.05, "bookmaker_odds": 3.00}, # mkt prob = 0.3333
    ]
    auditor = OOSPerformanceAuditor(min_independent_events_threshold=1)
    report = auditor.audit(settled_records_override=records)

    overall = report.segments["All Selections"]
    assert overall.model_log_loss is not None
    assert overall.market_log_loss is not None
    # Model is far more confident on the correct outcome (0.95 vs 0.67, and 0.05 vs 0.33), so Model LL is much lower
    assert overall.model_log_loss < overall.market_log_loss
    assert overall.log_loss_advantage > 0

