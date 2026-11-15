"""Unit tests for sports-engine/src/paper_trader.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paper_trader import PaperTradingEngine, evaluate_outcome_win  # noqa: E402


def test_evaluate_outcome_win_all_markets():
    assert evaluate_outcome_win("1X2", "HOME", 2, 1) is True
    assert evaluate_outcome_win("1X2", "DRAW", 1, 1) is True
    assert evaluate_outcome_win("1X2", "AWAY", 0, 2) is True
    assert evaluate_outcome_win("OU_2.5", "OVER_2.5", 2, 1) is True
    assert evaluate_outcome_win("OU_2.5", "UNDER_2.5", 1, 1) is True
    assert evaluate_outcome_win("OU_2.5", "UNDER_2.5", 2, 1) is False


def test_paper_trading_deduplication_clv_and_settlement(tmp_path):
    ledger_file = tmp_path / "paper_ledger.csv"
    engine = PaperTradingEngine(ledger_path=ledger_file)

    signals = [
        {
            "event_id": "631919",
            "match_id": "631919_unibet",
            "timestamp_mode": "2026-10-29T10:00:00Z",
            "kickoff": "2026-10-31T14:00:00Z",
            "league": "İtalya Serie B (I2) [UNIBET]",
            "tier": "TIER_1_SEC",
            "home": "Cremonese",
            "away": "Benevento",
            "market": "1X2",
            "outcome": "DRAW",
            "soft_book": "unibet",
            "sharp_odds": 3.08,
            "soft_odds": 3.45,
            "fair_prob": 0.3086,
            "fair_odds": 3.24,
            "edge_pct": 6.48,
            "kelly_pct": 1.32,
            "steam_drift_pp": 1.45,
            "is_steam_confirmed": True,
        }
    ]

    r1 = engine.record_signals(signals)
    assert r1 == {"inserted": 1, "updated": 0, "total": 1}

    # Second scan: Pinnacle draw steamed further down (fair_odds dropped from 3.24 to 3.05)
    signals[0]["fair_odds"] = 3.05
    signals[0]["steam_drift_pp"] = 3.10
    r2 = engine.record_signals(signals)
    assert r2 == {"inserted": 0, "updated": 1, "total": 1}

    rows = engine.load_rows()
    assert len(rows) == 1
    assert float(rows[0]["clv_ratio"]) == pytest.approx(3.45 / 3.05, abs=1e-3)

    # Settle match as 1-1 draw (WON)
    settle_res = engine.settle_with_scores(
        [{"home": "US Cremonese", "away": "Benevento Calcio", "hg": 1, "ag": 1, "done": True}]
    )
    assert settle_res["settled_now"] == 1

    summary = engine.compute_summary()
    assert summary["settled_count"] == 1
    assert summary["won_count"] == 1
    assert summary["win_rate_pct"] == 100.0
    assert summary["net_units"] == pytest.approx(2.45, abs=1e-2)
    assert summary["roi_pct"] == pytest.approx(245.0, abs=1e-1)
    assert summary["beat_clv_pct"] == 100.0
    assert summary["brier_advantage"] > 0.0


def test_turkish_national_team_names_settle_against_espn_english_names(tmp_path):
    ledger_file = tmp_path / "paper_tr_ledger.csv"
    engine = PaperTradingEngine(ledger_path=ledger_file)
    engine.save_rows([
        {
            "signal_id": "tr_1",
            "event_id": "e_tr_1",
            "home": "Sırbistan",
            "away": "Almanya",
            "market": "Korner 9.5",
            "outcome": "Korner 9.5 ÜST",
            "soft_odds": "1.76",
            "shin_fair_prob": "0.60",
            "status": "PENDING",
            "kickoff": "2026-11-12T19:45:00Z",
        },
        {
            "signal_id": "tr_2",
            "event_id": "e_tr_2",
            "home": "Hollanda",
            "away": "Yunanistan",
            "market": "Korner 10.5",
            "outcome": "Korner 10.5 ÜST",
            "soft_odds": "2.32",
            "shin_fair_prob": "0.50",
            "status": "PENDING",
            "kickoff": "2026-11-12T19:45:00Z",
        },
    ])
    settle_res = engine.settle_with_scores([
        {"home": "Serbia", "away": "Germany", "hg": 1, "ag": 3, "corners": 6, "done": True},
        {"home": "Netherlands", "away": "Greece", "hg": 7, "ag": 0, "corners": 9, "done": True},
    ])
    assert settle_res["settled_now"] == 2
    rows = {r["signal_id"]: r for r in engine.load_rows()}
    assert rows["tr_1"]["status"] == "LOST"
    assert rows["tr_2"]["status"] == "LOST"


def test_paper_trader_limits_corner_signals_to_single_highest_ev_per_match(tmp_path):
    ledger_file = tmp_path / "paper_corner_cap.csv"
    engine = PaperTradingEngine(ledger_path=ledger_file)

    batch_1 = [
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "Korner 8.5",
            "selection": "Korner 8.5 ÜST",
            "offered_odds": 1.52,
            "fair_odds_shin": 1.45,
            "fair_prob_shin": 0.69,
            "edge_pct": 4.80,
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "Korner 10.5",
            "selection": "Korner 10.5 ÜST",
            "offered_odds": 2.32,
            "fair_odds_shin": 2.09,
            "fair_prob_shin": 0.478,
            "edge_pct": 10.92,
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "Korner 9.5",
            "selection": "Korner 9.5 ÜST",
            "offered_odds": 1.80,
            "fair_odds_shin": 1.70,
            "fair_prob_shin": 0.589,
            "edge_pct": 6.07,
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "1X2",
            "selection": "MS 1",
            "offered_odds": 1.75,
            "fair_odds_shin": 1.65,
            "fair_prob_shin": 0.606,
            "edge_pct": 6.06,
        },
    ]

    r1 = engine.record_value_signals(batch_1)
    assert r1 == {"inserted": 2, "updated": 0, "total": 2}
    rows = engine.load_rows()
    corner_rows = [r for r in rows if "Korner" in r["market"]]
    assert len(corner_rows) == 1
    assert corner_rows[0]["market"] == "Korner 10.5"

    # Subsequent scan later: an alternative corner line arrives alongside a CLV update for Korner 10.5
    batch_2 = [
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "Korner 9.5",
            "selection": "Korner 9.5 ÜST",
            "offered_odds": 1.95,
            "fair_odds_shin": 1.70,
            "fair_prob_shin": 0.589,
            "edge_pct": 14.7,
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "kickoff": "2026-11-13T19:45:00Z",
            "market": "Korner 10.5",
            "selection": "Korner 10.5 ÜST",
            "offered_odds": 2.32,
            "fair_odds_shin": 2.02,
            "fair_prob_shin": 0.495,
            "edge_pct": 14.8,
        },
    ]
    r2 = engine.record_value_signals(batch_2)
    assert r2 == {"inserted": 0, "updated": 1, "total": 2}
    rows_after = engine.load_rows()
    corner_after = [r for r in rows_after if "Korner" in r["market"]]
    assert len(corner_after) == 1
    assert corner_after[0]["market"] == "Korner 10.5"
    assert corner_after[0]["latest_pinnacle_fair_odds"] == "2.020"


def test_evaluate_outcome_win_1x2_does_not_substring_match_12():
    with pytest.raises(ValueError):
        evaluate_outcome_win("1X2", "12", 2, 0)
    assert evaluate_outcome_win("1X2", "MS 1", 2, 0) is True
    assert evaluate_outcome_win("1X2", "MS 2", 2, 0) is False




