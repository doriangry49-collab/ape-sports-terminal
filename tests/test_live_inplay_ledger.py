"""Unit tests for Live In-Play Ambush Paper Trading Ledger."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from live_inplay_ledger import LiveInPlayLedger


@pytest.fixture
def test_ledger(tmp_path):
    f = tmp_path / "test_live_ledger.csv"
    return LiveInPlayLedger(ledger_file=f)


def test_record_in_play_bet_spec0015_compliance(test_ledger):
    """Verify that bets recorded enforce SPEC-0015 minimum 50 TL and capture metadata."""
    sig = {
        "event_id": "test_match_101",
        "league": "Bundesliga",
        "home": "Bayern Munich",
        "away": "Dortmund",
        "elapsed_min": 64,
        "score": "2-1",
        "market": "CANLI GOL PUSU",
        "selection": "4.5 ÜST",
        "line": "4.5 ÜST",
        "book_odd": 2.10,
        "stake": 30.0,  # Below 50 TL -> Must be elevated to 50.0 TL!
        "gasi_score": 88.0,
    }

    recorded = test_ledger.record_in_play_bet(sig)
    assert recorded is True

    # Duplicate check: recording identical event+selection should be blocked
    recorded_again = test_ledger.record_in_play_bet(sig)
    assert recorded_again is False

    # Read back and verify stake
    summary = test_ledger.get_summary()
    assert summary["total_bets"] == 1
    assert summary["settled"] == 0

    with test_ledger.ledger_file.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        assert float(reader[0]["stake"]) == 50.0  # Elevated!
        assert reader[0]["selection"] == "4.5 ÜST"
        assert reader[0]["status"] == "PENDING"


def test_settle_won_goal_bet(test_ledger):
    """Verify settlement of a winning Goal Ambush bet."""
    sig = {
        "event_id": "test_match_102",
        "home": "PSV",
        "away": "Feyenoord",
        "selection": "4.5 ÜST",
        "book_odd": 2.00,
        "stake": 100.0,
    }
    test_ledger.record_in_play_bet(sig)

    # Match ends 3-2 (total 5 goals > 4.5 line -> WON)
    settled = test_ledger.settle_bet(
        event_id="test_match_102",
        selection="4.5 ÜST",
        final_home_goals=3,
        final_away_goals=2,
    )
    assert settled is True

    summary = test_ledger.get_summary()
    assert summary["settled"] == 1
    assert summary["won"] == 1
    assert summary["win_rate_pct"] == 100.0
    assert summary["total_pnl_try"] == 100.0  # (2.00 - 1.0) * 100.0
    assert summary["roi_pct"] == 100.0


def test_settle_lost_goal_bet(test_ledger):
    """Verify settlement of a lost Goal Ambush bet."""
    sig = {
        "event_id": "test_match_103",
        "home": "Lazio",
        "away": "Roma",
        "selection": "3.5 ÜST",
        "book_odd": 2.20,
        "stake": 50.0,
    }
    test_ledger.record_in_play_bet(sig)

    # Match ends 2-1 (total 3 goals <= 3.5 line -> LOST)
    settled = test_ledger.settle_bet(
        event_id="test_match_103",
        selection="3.5 ÜST",
        final_home_goals=2,
        final_away_goals=1,
    )
    assert settled is True

    summary = test_ledger.get_summary()
    assert summary["settled"] == 1
    assert summary["lost"] == 1
    assert summary["total_pnl_try"] == -50.0
    assert summary["roi_pct"] == -100.0


def test_missing_odds_and_missing_corners_fail_closed(test_ledger):
    """SPEC-0012: Missing book_odd must not invent 1.95; missing corners must stay PENDING."""
    assert test_ledger.record_in_play_bet({
        "event_id": "test_no_odds",
        "home": "Team A",
        "away": "Team B",
        "market": "CANLI KORNER",
        "selection": "8.5 ÜST",
        "stake": 50.0,
    }) is False

    assert test_ledger.record_in_play_bet({
        "event_id": "test_corner_pending",
        "home": "Team A",
        "away": "Team B",
        "market": "CANLI KORNER",
        "selection": "8.5 ÜST",
        "book_odd": 1.90,
        "stake": 50.0,
    }) is True

    # Corner settlement without final_corners must remain PENDING (fail-closed)
    assert test_ledger.settle_bet("test_corner_pending", "8.5 ÜST", 2, 1, final_corners=None) is False
    assert test_ledger.get_summary()["settled"] == 0


def test_settle_bet_parses_word_first_selection_line(test_ledger):
    """Ensure regex line parser handles formats like 'ÜST 4.5' or 'Korner 9.5 ÜST'."""
    assert test_ledger.record_in_play_bet({
        "event_id": "test_word_first",
        "home": "Alpha",
        "away": "Beta",
        "market": "CANLI GOL",
        "selection": "ÜST 4.5",
        "book_odd": 2.10,
        "stake": 50.0,
    }) is True
    assert test_ledger.settle_bet("test_word_first", "ÜST 4.5", 3, 2) is True
    assert test_ledger.get_summary()["won"] == 1


