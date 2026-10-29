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

