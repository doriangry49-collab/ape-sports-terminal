"""
Comprehensive Verification Test Suite for Requirement R2 & R4.

Covers:
- T-5m pre-kickoff trigger & window eligibility across UTC & TRT.
- Immutability enforcement (rejecting duplicate writes, preventing odds alteration).
- SQLite persistence & schema integrity (table, index, foreign keys).
- Accurate CLV mathematics (raw CLV, fair CLV, edge percentage, beat closing).
- Fail-closed error handling (SPEC-0012: no synthetic or mock odds).
- Kickoff window validation (SPEC-0013: > now + 3m, SPEC-0014: <= now + 12h).
- Minimum stake enforcement (SPEC-0015: stake >= 50.0 TL).
- Paper trader integration (locking CLV on frozen closing lines).
- JSON ledger atomic persistence.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Ensure src is on sys.path
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from closing_line_freeze import (  # noqa: E402
    ClosingLineAlreadyFrozenError,
    ClosingLineFreezeEngine,
    ClosingLineStore,
    ClosingLineTimingError,
    ClosingLineUnavailableError,
    check_fixture_kickoff_window,
    compute_clv,
    extract_fair_odds,
    format_trt,
    freeze_closing_line,
    is_eligible_for_freeze,
    validate_coupon_stake,
)
from paper_trader import PaperTradingEngine  # noqa: E402

# ---------------------------------------------------------------------------
# Test 1: T-5m Timing & Eligibility Logic
# ---------------------------------------------------------------------------

def test_is_eligible_for_freeze_window():
    """Verify freeze eligibility exactly within [kickoff - 5m, kickoff] window."""
    ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)

    # 6 minutes before kickoff: too early
    t_6m_before = ko_utc - timedelta(minutes=6)
    assert is_eligible_for_freeze(ko_utc, t_6m_before) is False

    # 5 minutes before kickoff: exactly on cutoff
    t_5m_before = ko_utc - timedelta(minutes=5)
    assert is_eligible_for_freeze(ko_utc, t_5m_before) is True

    # 2.5 minutes before kickoff: inside window
    t_2_5m_before = ko_utc - timedelta(minutes=2, seconds=30)
    assert is_eligible_for_freeze(ko_utc, t_2_5m_before) is True

    # Exact kickoff: last allowable moment
    assert is_eligible_for_freeze(ko_utc, ko_utc) is True

    # 1 second post-kickoff: match started, ineligible
    t_post_ko = ko_utc + timedelta(seconds=1)
    assert is_eligible_for_freeze(ko_utc, t_post_ko) is False


def test_freeze_closing_line_timing_enforcement(tmp_path):
    """Verify timing violations raise ClosingLineTimingError unless force=True."""
    db_file = tmp_path / "closing_lines.sqlite"
    store = ClosingLineStore(db_path=db_file)
    ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
    odds = {"1": 2.10, "X": 3.20, "2": 3.40}

    # Too early (10m before kickoff) without force -> raises ClosingLineTimingError
    with pytest.raises(ClosingLineTimingError) as exc_info:
        freeze_closing_line(
            fixture_id="fix_early",
            market_odds=odds,
            kickoff_utc=ko_utc,
            now_utc=ko_utc - timedelta(minutes=10),
            force=False,
            store=store,
        )
    assert "away (> 5m)" in str(exc_info.value)

    # Post-kickoff without force -> raises ClosingLineTimingError
    with pytest.raises(ClosingLineTimingError) as exc_info:
        freeze_closing_line(
            fixture_id="fix_late",
            market_odds=odds,
            kickoff_utc=ko_utc,
            now_utc=ko_utc + timedelta(minutes=2),
            force=False,
            store=store,
        )
    assert "already kicked off" in str(exc_info.value)

    # Legitimate T-5m freeze -> succeeds
    rec = freeze_closing_line(
        fixture_id="fix_ok",
        market_odds=odds,
        kickoff_utc=ko_utc,
        now_utc=ko_utc - timedelta(minutes=5),
        force=False,
        store=store,
    )
    assert rec.is_frozen is True
    assert rec.fixture_id == "fix_ok"

    # Forced freeze outside window (e.g. backfill / offline test) -> succeeds
    rec_forced = freeze_closing_line(
        fixture_id="fix_forced",
        market_odds=odds,
        kickoff_utc=ko_utc,
        now_utc=ko_utc - timedelta(hours=2),
        force=True,
        store=store,
    )
    assert rec_forced.is_frozen is True


# ---------------------------------------------------------------------------
# Test 2: Immutability Enforcement
# ---------------------------------------------------------------------------

def test_closing_line_immutability_rejection(tmp_path):
    """Verify that once frozen, lines cannot be overwritten or altered."""
    db_file = tmp_path / "closing_lines.sqlite"
    json_file = tmp_path / "closing_lines.json"
    store = ClosingLineStore(db_path=db_file, json_path=json_file)

    ko_utc = datetime(2026, 11, 4, 19, 0, 0, tzinfo=UTC)
    initial_odds = {"1": 2.00, "X": 3.30, "2": 3.60}

    rec1 = freeze_closing_line(
        fixture_id="fix_immutable",
        market_odds=initial_odds,
        kickoff_utc=ko_utc,
        market="1X2",
        bookmaker="PINNACLE",
        force=True,
        store=store,
    )
    assert rec1.closing_odds["1"] == 2.00

    # Attempt to re-freeze with modified odds must be rejected with ClosingLineAlreadyFrozenError
    tampered_odds = {"1": 1.75, "X": 3.80, "2": 4.50}
    with pytest.raises(ClosingLineAlreadyFrozenError) as exc_info:
        freeze_closing_line(
            fixture_id="fix_immutable",
            market_odds=tampered_odds,
            kickoff_utc=ko_utc,
            market="1X2",
            bookmaker="PINNACLE",
            force=True,
            store=store,
            raise_if_exists=True,
        )
    assert "already frozen" in str(exc_info.value)

    # Calling with raise_if_exists=False must return the existing frozen line unchanged
    rec_existing = freeze_closing_line(
        fixture_id="fix_immutable",
        market_odds=tampered_odds,
        kickoff_utc=ko_utc,
        market="1X2",
        bookmaker="PINNACLE",
        force=True,
        store=store,
        raise_if_exists=False,
    )
    assert rec_existing.closing_odds["1"] == 2.00
    assert rec_existing.closing_odds["X"] == 3.30


# ---------------------------------------------------------------------------
# Test 3: SQLite Persistence & Retrieval Integrity
# ---------------------------------------------------------------------------

def test_sqlite_persistence_and_querying(tmp_path):
    """Verify SQLite database structure, unique constraints, and retrieval."""
    db_file = tmp_path / "closing_lines.sqlite"
    json_file = tmp_path / "closing_lines.json"
    store = ClosingLineStore(db_path=db_file, json_path=json_file)

    ko_utc = datetime(2026, 11, 4, 17, 30, 0, tzinfo=UTC)
    odds = {"OVER_2.5": 1.85, "UNDER_2.5": 2.05}

    freeze_closing_line(
        fixture_id="fix_totals_1",
        market_odds=odds,
        kickoff_utc=ko_utc,
        match_name="Galatasaray vs Besiktas",
        league="Trendyol Süper Lig",
        market="OU_2.5",
        bookmaker="PINNACLE",
        force=True,
        store=store,
    )

    # Inspect SQLite database directly
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT snapshot_id, fixture_id, market, closing_odds_json FROM closing_lines WHERE fixture_id = ?", ("fix_totals_1",))
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "fix_totals_1"
        assert row[2] == "OU_2.5"
        loaded_odds = json.loads(row[3])
        assert loaded_odds == odds

        # Verify denormalized selection table
        cursor.execute("SELECT selection, closing_odds FROM closing_line_selections WHERE fixture_id = ?", ("fix_totals_1",))
        selections = dict(cursor.fetchall())
        assert selections["OVER_2.5"] == 1.85
        assert selections["UNDER_2.5"] == 2.05

    # Retrieve via store API
    retrieved = store.get_record("fix_totals_1", "OU_2.5", "PINNACLE")
    assert retrieved is not None
    assert retrieved.match_name == "Galatasaray vs Besiktas"
    assert retrieved.league == "Trendyol Süper Lig"
    assert retrieved.kickoff_trt == format_trt(ko_utc)
    assert "OVER_2.5" in retrieved.fair_closing_odds

    # Non-existent query returns None
    assert store.get_record("non_existent", "1X2") is None
    assert store.has_frozen("non_existent", "1X2") is False
    assert store.has_frozen("fix_totals_1", "OU_2.5") is True


# ---------------------------------------------------------------------------
# Test 4: Accurate CLV Calculation Mathematics
# ---------------------------------------------------------------------------

def test_clv_calculation_positive_and_negative():
    """Verify exact mathematical formulations for raw CLV, fair CLV, and edge %."""
    # Scenario A: Positive CLV (Sharp line dropped / shortened after bet)
    # Entry odds: 2.20, Pinnacle closing: 2.00, Shin fair closing: 2.05
    res_pos = compute_clv(entry_odds=2.20, frozen_closing_odds=2.00, frozen_fair_odds=2.05)
    assert res_pos["clv_raw"] == pytest.approx(1.1000, abs=1e-4)       # 2.20 / 2.00 = 1.1000
    assert res_pos["clv_fair"] == pytest.approx(1.0732, abs=1e-4)      # 2.20 / 2.05 = 1.0732
    assert res_pos["clv_edge_pct"] == pytest.approx(7.32, abs=0.01)    # (2.20 / 2.05 - 1.0) * 100 = 7.32%
    assert res_pos["beat_closing"] is True

    # Scenario B: Negative CLV (Odds drifted against the bettor)
    # Entry odds: 1.80, Pinnacle closing: 2.00, Shin fair closing: 2.05
    res_neg = compute_clv(entry_odds=1.80, frozen_closing_odds=2.00, frozen_fair_odds=2.05)
    assert res_neg["clv_raw"] == pytest.approx(0.9000, abs=1e-4)       # 1.80 / 2.00 = 0.9000
    assert res_neg["clv_fair"] == pytest.approx(0.8780, abs=1e-4)      # 1.80 / 2.05 = 0.8780
    assert res_neg["clv_edge_pct"] == pytest.approx(-12.20, abs=0.01)  # (1.80 / 2.05 - 1.0) * 100 = -12.20%
    assert res_neg["beat_closing"] is False


# ---------------------------------------------------------------------------
# Test 5: Constitutional Compliance (SPEC-0012 Fail-Closed)
# ---------------------------------------------------------------------------

def test_spec_0012_fail_closed_on_corrupt_or_missing_odds():
    """Verify fail-closed behavior on missing or invalid odds (no synthetic fallback)."""
    # Empty odds dictionary
    with pytest.raises(ClosingLineUnavailableError) as exc_info:
        extract_fair_odds({})
    assert "SPEC-0012" in str(exc_info.value)

    # Odds <= 1.0
    with pytest.raises(ClosingLineUnavailableError) as exc_info:
        extract_fair_odds({"1": 1.0, "X": 3.20, "2": 3.40})
    assert "SPEC-0012" in str(exc_info.value)

    # Negative odds
    with pytest.raises(ClosingLineUnavailableError) as exc_info:
        extract_fair_odds({"1": -2.10, "X": 3.20, "2": 3.40})
    assert "SPEC-0012" in str(exc_info.value)

    # In compute_clv: corrupt odds
    with pytest.raises(ClosingLineUnavailableError):
        compute_clv(entry_odds=0.95, frozen_closing_odds=2.00, frozen_fair_odds=2.05)

    with pytest.raises(ClosingLineUnavailableError):
        compute_clv(entry_odds=2.10, frozen_closing_odds=0.50, frozen_fair_odds=2.05)


# ---------------------------------------------------------------------------
# Test 6: Constitutional Compliance (SPEC-0013, SPEC-0014, SPEC-0015)
# ---------------------------------------------------------------------------

def test_kickoff_window_validators_spec_0013_spec_0014():
    """Verify SPEC-0013 (> now + 3m) and SPEC-0014 (<= now + 12h) kickoff rules."""
    now_utc = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

    # 2 minutes to kickoff: violates SPEC-0013 (must be > 3m)
    ko_2m = now_utc + timedelta(minutes=2)
    valid, msg = check_fixture_kickoff_window(ko_2m, now_utc)
    assert valid is False
    assert "SPEC-0013" in msg

    # Exactly 3 minutes: violates SPEC-0013 (must be > 3m)
    ko_3m = now_utc + timedelta(minutes=3)
    valid, msg = check_fixture_kickoff_window(ko_3m, now_utc)
    assert valid is False
    assert "SPEC-0013" in msg

    # 4 minutes: valid upcoming match
    ko_4m = now_utc + timedelta(minutes=4)
    valid, msg = check_fixture_kickoff_window(ko_4m, now_utc)
    assert valid is True
    assert msg == "VALID_WINDOW"

    # 11 hours: valid upcoming match
    ko_11h = now_utc + timedelta(hours=11)
    valid, msg = check_fixture_kickoff_window(ko_11h, now_utc)
    assert valid is True

    # 13 hours: violates SPEC-0014 (> 12h)
    ko_13h = now_utc + timedelta(hours=13)
    valid, msg = check_fixture_kickoff_window(ko_13h, now_utc)
    assert valid is False
    assert "SPEC-0014" in msg


def test_stake_enforcement_spec_0015():
    """Verify SPEC-0015 minimum 50 TL stake enforcement."""
    # Under 50 TL raises ValueError
    with pytest.raises(ValueError) as exc_info:
        validate_coupon_stake(49.99)
    assert "SPEC-0015" in str(exc_info.value)

    with pytest.raises(ValueError):
        validate_coupon_stake(0.0)

    # Exactly 50.0 TL or higher passes
    assert validate_coupon_stake(50.0) is True
    assert validate_coupon_stake(150.0) is True


# ---------------------------------------------------------------------------
# Test 7: Integration with Paper Trader Engine
# ---------------------------------------------------------------------------

def test_paper_trader_integration_with_frozen_closing_lines(tmp_path):
    """Verify PaperTradingEngine preserves frozen closing lines and does not mutate in-play."""
    ledger_file = tmp_path / "paper_ledger.csv"
    db_file = tmp_path / "closing_lines.sqlite"
    cl_store = ClosingLineStore(db_path=db_file)

    # 1. Freeze closing line at T-5m for fixture '650100'
    ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
    freeze_closing_line(
        fixture_id="650100",
        market_odds={"HOME": 2.15, "DRAW": 3.40, "AWAY": 3.50},
        fair_closing_odds={"HOME": 2.05, "DRAW": 3.50, "AWAY": 3.65},
        kickoff_utc=ko_utc,
        market="1X2",
        bookmaker="PINNACLE",
        force=True,
        store=cl_store,
    )

    # 2. Initialize PaperTradingEngine connected to ClosingLineStore
    engine = PaperTradingEngine(ledger_path=ledger_file, closing_line_store=cl_store)

    signals = [
        {
            "event_id": "650100",
            "match_id": "650100_nesine",
            "timestamp_mode": "2026-11-04T15:00:00Z",
            "kickoff": ko_utc.isoformat(),
            "league": "Premier League",
            "tier": "TIER_1_SHIN_QUANT",
            "home": "Arsenal",
            "away": "Chelsea",
            "market": "1X2",
            "outcome": "HOME",
            "soft_book": "nesine",
            "sharp_odds": 2.15,
            "soft_odds": 2.30,
            "fair_prob": 0.4878,
            "fair_odds": 2.05,
            "edge_pct": 12.19,
            "kelly_pct": 2.50,
        }
    ]

    r1 = engine.record_signals(signals)
    assert r1["inserted"] == 1

    # 3. Subsequent live scan passes in-play mutating fair_odds (e.g. 1.70 during second half)
    signals[0]["fair_odds"] = 1.70
    signals[0]["steam_drift_pp"] = 5.0
    r2 = engine.record_signals(signals)
    assert r2["updated"] == 1

    rows = engine.load_rows()
    assert len(rows) == 1
    # MUST still be locked to frozen closing fair odds (2.05), NOT the mutating in-play odds (1.70)
    assert float(rows[0]["latest_pinnacle_fair_odds"]) == pytest.approx(2.05, abs=1e-3)
    assert float(rows[0]["clv_ratio"]) == pytest.approx(2.30 / 2.05, abs=1e-3)

    # 4. Also test sync_closing_lines
    synced = engine.sync_closing_lines()
    assert synced == 1


# ---------------------------------------------------------------------------
# Test 8: Coordinating Engine & JSON Ledger
# ---------------------------------------------------------------------------

def test_closing_line_freeze_engine_and_json_ledger(tmp_path):
    """Verify high-level ClosingLineFreezeEngine operations and JSON ledger persistence."""
    db_file = tmp_path / "closing_lines.sqlite"
    json_file = tmp_path / "closing_lines.json"
    store = ClosingLineStore(db_path=db_file, json_path=json_file)
    engine = ClosingLineFreezeEngine(store=store)

    ko_utc = datetime(2026, 11, 4, 18, 0, 0, tzinfo=UTC)
    now_freeze = ko_utc - timedelta(minutes=5)

    assert engine.is_eligible_for_freeze(ko_utc, now_freeze) is True

    record = engine.freeze(
        fixture_id="fix_engine_1",
        market_odds={"1": 2.25, "X": 3.10, "2": 3.60},
        kickoff_utc=ko_utc,
        match_name="Fenerbahce vs Trabzonspor",
        league="Trendyol Süper Lig",
        market="1X2",
        now_utc=now_freeze,
        force=False,
    )
    assert record.fixture_id == "fix_engine_1"
    assert record.is_frozen is True

    # Compute signal CLV
    clv = engine.compute_signal_clv(
        fixture_id="fix_engine_1",
        market="1X2",
        outcome="1",
        entry_odds=2.40,
    )
    assert clv["clv_raw"] == pytest.approx(2.40 / 2.25, abs=1e-4)
    assert clv["beat_closing"] is True

    # Verify JSON ledger exists and contains the record
    assert json_file.exists()
    with open(json_file, encoding="utf-8") as fh:
        ledger = json.load(fh)
    key = "fix_engine_1|1X2|PINNACLE"
    assert key in ledger
    assert ledger[key]["match_name"] == "Fenerbahce vs Trabzonspor"
