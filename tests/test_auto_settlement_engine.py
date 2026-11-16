"""Unit tests for AutoSettlementEngine."""

from __future__ import annotations

import csv
import pytest
import sys
from pathlib import Path

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from sports_engine.models.auto_settlement_engine import AutoSettlementEngine


@pytest.fixture
def sample_ledger(tmp_path):
    ledger_file = tmp_path / "test_ledger.csv"
    rows = [
        {
            "captured_at_utc": "2026-11-12T10:00:00Z",
            "league": "Brezilya Serie A",
            "home": "Santos",
            "away": "Palmeiras",
            "market": "ALT/ÜST",
            "outcome": "2.5 ALT",
            "soft_book": "NESINE",
            "soft_odds": "1.73",
            "shin_fair_odds": "1.65",
            "shin_fair_prob": "0.60",
            "edge_pct": "5.0",
            "kelly_pct": "4.0",
            "clv_ratio": "1.00",
            "result_score": "Bekliyor",
            "status": "PENDING",
            "pnl_units": "0.00",
        },
        {
            "captured_at_utc": "2026-11-12T10:00:00Z",
            "league": "MLS",
            "home": "Charlotte",
            "away": "Montreal",
            "market": "ALT/ÜST",
            "outcome": "2.5 ALT",
            "soft_book": "NESINE",
            "soft_odds": "2.50",
            "shin_fair_odds": "2.30",
            "shin_fair_prob": "0.43",
            "edge_pct": "8.0",
            "kelly_pct": "3.0",
            "clv_ratio": "1.00",
            "result_score": "Bekliyor",
            "status": "PENDING",
            "pnl_units": "0.00",
        },
    ]

    fieldnames = list(rows[0].keys())
    with open(ledger_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return ledger_file


def test_settle_won_and_lost_bets(sample_ledger):
    """Verify that Santos 1-0 settles as WON (+36.5 TL) and Charlotte 2-1 settles as LOST (-50.0 TL)."""
    engine = AutoSettlementEngine(ledger_path=sample_ledger)

    mock_espn = {
        "santos vs palmeiras": {
            "home": "santos",
            "away": "palmeiras",
            "hg": 1,
            "ag": 0,
            "score_str": "1-0",
            "tot_goals": 1,
        },
        "charlotte vs montreal": {
            "home": "charlotte",
            "away": "montreal",
            "hg": 2,
            "ag": 1,
            "score_str": "2-1",
            "tot_goals": 3,
        },
    }

    updated_rows = engine.settle_pending_bets(mock_results=mock_espn)

    assert len(updated_rows) == 2
    # Santos bet (2.5 ALT on 1-0) -> WON
    assert updated_rows[0]["status"] == "WON"
    assert updated_rows[0]["result_score"] == "1-0"
    assert updated_rows[0]["pnl_units"] == "+36.50"

    # Charlotte bet (2.5 ALT on 2-1) -> LOST
    assert updated_rows[1]["status"] == "LOST"
    assert updated_rows[1]["result_score"] == "2-1"
    assert updated_rows[1]["pnl_units"] == "-50.00"


def test_market_outcome_evaluation_matrix():
    """Verify various market outcome evaluations."""
    engine = AutoSettlementEngine()

    # 1X2
    assert engine.evaluate_bet_outcome("MS", "MS 1 (Kazanır)", 2, 0) is True
    assert engine.evaluate_bet_outcome("MS", "MS X (Beraberlik)", 1, 1) is True
    assert engine.evaluate_bet_outcome("MS", "MS 2 (Kazanır)", 0, 2) is True

    # Double Chance
    assert engine.evaluate_bet_outcome("Çifte Şans", "1-X", 1, 0) is True
    assert engine.evaluate_bet_outcome("Çifte Şans", "1-X", 1, 1) is True
    assert engine.evaluate_bet_outcome("Çifte Şans", "1-X", 0, 1) is False

    # BTTS
    assert engine.evaluate_bet_outcome("KG", "KG Var", 1, 1) is True
    assert engine.evaluate_bet_outcome("KG", "KG Var", 2, 0) is False
