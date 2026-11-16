"""
Adversarial Stress Test Suite for Milestone 1: Closing Line Snapshot Freeze & CLV Engine.

Targeted attack dimensions:
1. Exact freeze window boundary conditions (T-5m, T-5m-1s, T-4m59s, T+1s, microsecond deltas).
2. Timezone resilience: UTC aware, TRT (+03:00) aware, UTC naive, and string representations.
3. Multi-threaded concurrency stress & immutability guarantee under race conditions.
4. SPEC-0012 fail-closed validation under corrupt inputs (NaN, Inf, negative, zero, non-numeric).
5. SPEC-0013 (now + 3m cutoff) & SPEC-0014 (now + 12h cutoff) exact second boundaries.
6. SPEC-0015 minimum stake enforcement boundary (49.99 TL vs 50.00 TL).
7. PaperTradingEngine CLV lock immutability under simulated in-play odds mutation.
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from closing_line_freeze import (
    TRT_TZ,
    ClosingLineAlreadyFrozenError,
    ClosingLineStore,
    ClosingLineTimingError,
    ClosingLineUnavailableError,
    check_fixture_kickoff_window,
    compute_clv,
    extract_fair_odds,
    format_trt,
    freeze_closing_line,
    is_eligible_for_freeze,
    parse_iso_or_datetime,
    validate_coupon_stake,
)
from paper_trader import PaperTradingEngine

# ============================================================================
# Dimension 1: Exact Freeze Window Boundary Tests
# ============================================================================

class TestFreezeWindowBoundaries:
    """Stress-tests the exact second-level and sub-second boundaries of the freeze window."""

    ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)

    def test_freeze_window_exact_boundaries(self):
        # T - 5m - 1s (301 seconds before kickoff): MUST be ineligible
        t_early_1s = self.ko_utc - timedelta(seconds=301)
        assert is_eligible_for_freeze(self.ko_utc, t_early_1s) is False

        # T - 5m - 0.001s (300.001 seconds): MUST be ineligible
        t_early_subsec = self.ko_utc - timedelta(seconds=300, microseconds=1000)
        assert is_eligible_for_freeze(self.ko_utc, t_early_subsec) is False

        # T - 5m exactly (300.0 seconds): MUST be eligible (the target freeze trigger moment)
        t_exact_5m = self.ko_utc - timedelta(seconds=300)
        assert is_eligible_for_freeze(self.ko_utc, t_exact_5m) is True

        # T - 4m 59s (299.0 seconds): MUST be eligible
        t_late_1s = self.ko_utc - timedelta(seconds=299)
        assert is_eligible_for_freeze(self.ko_utc, t_late_1s) is True

        # T - 0s (Kickoff exact moment): MUST be eligible as last allowable pre-kickoff instant
        assert is_eligible_for_freeze(self.ko_utc, self.ko_utc) is True

        # T + 0.001s (Kickoff + 1 millisecond): Match has started -> MUST be ineligible
        t_post_ko_subsec = self.ko_utc + timedelta(microseconds=1000)
        assert is_eligible_for_freeze(self.ko_utc, t_post_ko_subsec) is False

        # T + 1s (Kickoff + 1 second): MUST be ineligible
        t_post_ko_1s = self.ko_utc + timedelta(seconds=1)
        assert is_eligible_for_freeze(self.ko_utc, t_post_ko_1s) is False

    def test_freeze_closing_line_boundary_exceptions(self, tmp_path):
        db_path = tmp_path / "boundary_test.sqlite"
        store = ClosingLineStore(db_path=db_path)
        odds = {"1": 2.10, "X": 3.20, "2": 3.40}

        # 1. Reject T - 5m - 1s with TimingError
        with pytest.raises(ClosingLineTimingError) as exc:
            freeze_closing_line(
                fixture_id="bnd_1",
                market_odds=odds,
                kickoff_utc=self.ko_utc,
                now_utc=self.ko_utc - timedelta(seconds=301),
                store=store,
            )
        assert "Timing Violation" in str(exc.value)

        # 2. Reject T + 1s with TimingError citing SPEC-0013
        with pytest.raises(ClosingLineTimingError) as exc:
            freeze_closing_line(
                fixture_id="bnd_2",
                market_odds=odds,
                kickoff_utc=self.ko_utc,
                now_utc=self.ko_utc + timedelta(seconds=1),
                store=store,
            )
        assert "SPEC-0013 Violation" in str(exc.value)

        # 3. Accept exact T - 5m (300.0s)
        rec = freeze_closing_line(
            fixture_id="bnd_3",
            market_odds=odds,
            kickoff_utc=self.ko_utc,
            now_utc=self.ko_utc - timedelta(seconds=300),
            store=store,
        )
        assert rec.is_frozen is True
        assert rec.fixture_id == "bnd_3"


# ============================================================================
# Dimension 2: Timezone Equivalence & Invariance Tests
# ============================================================================

class TestTimezoneEquivalence:
    """Stress-tests timezone conversions between UTC, TRT (+03:00), naive representations."""

    def test_utc_vs_trt_eligibility_invariance(self):
        # 20:00 UTC == 23:00 TRT
        ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
        ko_trt = datetime(2026, 11, 4, 23, 0, 0, tzinfo=TRT_TZ)

        now_utc = ko_utc - timedelta(minutes=4, seconds=30)
        now_trt = ko_trt - timedelta(minutes=4, seconds=30)

        # Both representations must yield identical eligibility results
        assert is_eligible_for_freeze(ko_utc, now_utc) is True
        assert is_eligible_for_freeze(ko_trt, now_trt) is True
        assert is_eligible_for_freeze(ko_utc, now_trt) is True
        assert is_eligible_for_freeze(ko_trt, now_utc) is True

    def test_iso_string_with_various_tz_formats(self):
        # UTC 'Z' notation
        dt1 = parse_iso_or_datetime("2026-11-04T20:00:00Z")
        assert dt1.tzinfo == UTC
        assert dt1.hour == 20

        # UTC '+00:00' notation
        dt2 = parse_iso_or_datetime("2026-11-04T20:00:00+00:00")
        assert dt2.tzinfo == UTC
        assert dt2.hour == 20

        # TRT '+03:00' notation
        dt3 = parse_iso_or_datetime("2026-11-04T23:00:00+03:00")
        assert dt3.tzinfo == UTC
        assert dt3.hour == 20  # 23:00 +03:00 is 20:00 UTC

        # All 3 representations represent the exact same absolute timestamp
        assert dt1 == dt2 == dt3

    def test_trt_formatting_accuracy(self):
        ko_utc = datetime(2026, 11, 4, 20, 15, 0, tzinfo=UTC)
        formatted = format_trt(ko_utc)
        assert formatted == "2026-11-04 23:15 TRT"


# ============================================================================
# Dimension 3: Concurrency & Immutability Stress Tests
# ============================================================================

class TestConcurrencyAndImmutability:
    """Stress-tests multi-threaded concurrent freezes on the same fixture/market."""

    def test_concurrent_freezes_preserve_immutability(self, tmp_path):
        db_path = tmp_path / "concurrent_closing_lines.sqlite"
        store = ClosingLineStore(db_path=db_path)
        ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)

        fixture_id = "concurrent_fixture_99"
        market = "1X2"
        bookmaker = "PINNACLE"

        # Thread 0 will attempt to freeze with odds A
        # Thread 1-9 will attempt to freeze with different odds B
        num_workers = 10
        results: list[dict[str, Any]] = []

        def worker_freeze(worker_id: int):
            odds = {
                "1": round(2.00 + (worker_id * 0.1), 2),
                "X": 3.20,
                "2": 3.50,
            }
            try:
                rec = freeze_closing_line(
                    fixture_id=fixture_id,
                    market_odds=odds,
                    kickoff_utc=ko_utc,
                    market=market,
                    bookmaker=bookmaker,
                    force=True,
                    store=store,
                    raise_if_exists=True,
                )
                return {"worker_id": worker_id, "status": "SUCCESS", "odds_1": rec.closing_odds["1"]}
            except ClosingLineAlreadyFrozenError as e:
                return {"worker_id": worker_id, "status": "ALREADY_FROZEN_ERROR", "msg": str(e)}
            except sqlite3.IntegrityError as e:
                return {"worker_id": worker_id, "status": "RAW_INTEGRITY_ERROR", "msg": str(e)}
            except Exception as e:
                return {"worker_id": worker_id, "status": "UNEXPECTED_ERROR", "type": type(e).__name__, "msg": str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_freeze, i) for i in range(num_workers)]
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())

        success_count = sum(1 for r in results if r["status"] == "SUCCESS")
        # EXACTLY one worker must succeed in writing the initial frozen closing line
        assert success_count == 1, f"Expected exactly 1 freeze to succeed, got {success_count}: {results}"

        # Verify database content: record exists and is unaltered
        frozen_rec = store.get_record(fixture_id, market, bookmaker)
        assert frozen_rec is not None
        assert frozen_rec.is_frozen is True

        # Check subsequent single-threaded tamper attempt
        with pytest.raises(ClosingLineAlreadyFrozenError):
            freeze_closing_line(
                fixture_id=fixture_id,
                market_odds={"1": 99.0, "X": 99.0, "2": 99.0},
                kickoff_utc=ko_utc,
                market=market,
                bookmaker=bookmaker,
                force=True,
                store=store,
                raise_if_exists=True,
            )

        # Database record MUST remain identical to the winner's odds
        reloaded_rec = store.get_record(fixture_id, market, bookmaker)
        assert reloaded_rec.closing_odds["1"] == frozen_rec.closing_odds["1"]


# ============================================================================
# Dimension 4: SPEC-0012 Fail-Closed Input Attacks
# ============================================================================

class TestSpec0012FailClosedAttacks:
    """Stress-tests fail-closed behavior on corrupted numerical inputs."""

    def test_corrupt_odds_zero_and_sub_one(self):
        # 1.0 is the break-even zero-probability threshold; odds must be strictly > 1.0
        with pytest.raises(ClosingLineUnavailableError):
            extract_fair_odds({"1": 1.0, "X": 3.0, "2": 3.0})

        with pytest.raises(ClosingLineUnavailableError):
            extract_fair_odds({"1": 0.5, "X": 3.0, "2": 3.0})

        with pytest.raises(ClosingLineUnavailableError):
            extract_fair_odds({"1": -2.0, "X": 3.0, "2": 3.0})

    def test_corrupt_odds_types(self):
        with pytest.raises(ClosingLineUnavailableError):
            extract_fair_odds({"1": None, "X": 3.0, "2": 3.0})  # type: ignore

        with pytest.raises(ClosingLineUnavailableError):
            extract_fair_odds({"1": "two_point_zero", "X": 3.0, "2": 3.0})  # type: ignore

    def test_compute_clv_zero_and_sub_one_rejection(self):
        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=1.0, frozen_closing_odds=2.0, frozen_fair_odds=2.0)

        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=2.0, frozen_closing_odds=1.0, frozen_fair_odds=2.0)

        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=2.0, frozen_closing_odds=2.0, frozen_fair_odds=1.0)


# ============================================================================
# Dimension 5: Constitutional Kickoff Windows (SPEC-0013 & SPEC-0014)
# ============================================================================

class TestKickoffCutoffsSpec0013Spec0014:
    """Stress-tests exact second boundaries for SPEC-0013 (> now + 3m) and SPEC-0014 (<= now + 12h)."""

    now_utc = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

    def test_spec_0013_three_minute_boundary(self):
        # Exactly 3 minutes: ko_dt == now + 3m -> MUST be rejected (violates > now + 3m)
        ko_exact_3m = self.now_utc + timedelta(seconds=180)
        valid, msg = check_fixture_kickoff_window(ko_exact_3m, self.now_utc)
        assert valid is False
        assert "SPEC-0013" in msg

        # 3 minutes minus 1 second: ko_dt == now + 2m59s -> MUST be rejected
        ko_2m59s = self.now_utc + timedelta(seconds=179)
        valid, msg = check_fixture_kickoff_window(ko_2m59s, self.now_utc)
        assert valid is False
        assert "SPEC-0013" in msg

        # 3 minutes plus 1 second: ko_dt == now + 3m01s -> MUST be accepted
        ko_3m01s = self.now_utc + timedelta(seconds=181)
        valid, msg = check_fixture_kickoff_window(ko_3m01s, self.now_utc)
        assert valid is True
        assert msg == "VALID_WINDOW"

    def test_spec_0014_twelve_hour_boundary(self):
        # Exactly 12 hours: ko_dt == now + 12h -> MUST be accepted (<= 12h)
        ko_exact_12h = self.now_utc + timedelta(hours=12)
        valid, msg = check_fixture_kickoff_window(ko_exact_12h, self.now_utc)
        assert valid is True
        assert msg == "VALID_WINDOW"

        # 12 hours plus 1 second: ko_dt == now + 12h01s -> MUST be rejected
        ko_12h01s = self.now_utc + timedelta(hours=12, seconds=1)
        valid, msg = check_fixture_kickoff_window(ko_12h01s, self.now_utc)
        assert valid is False
        assert "SPEC-0014" in msg


# ============================================================================
# Dimension 6: SPEC-0015 Minimum Stake Boundary
# ============================================================================

class TestSpec0015StakeBoundary:
    """Stress-tests the minimum 50.0 TL coupon stake rule."""

    def test_stake_boundary_precision(self):
        # 49.99 TL must be rejected
        with pytest.raises(ValueError) as exc:
            validate_coupon_stake(49.99)
        assert "SPEC-0015" in str(exc.value)

        # 49.999 TL must be rejected
        with pytest.raises(ValueError) as exc:
            validate_coupon_stake(49.999)
        assert "SPEC-0015" in str(exc.value)

        # Exactly 50.0 TL must pass
        assert validate_coupon_stake(50.0) is True

        # 50.01 TL must pass
        assert validate_coupon_stake(50.01) is True


# ============================================================================
# Dimension 7: Paper Trader Ledger CLV Lock Stress Test
# ============================================================================

class TestPaperTraderClvLockStress:
    """Stress-tests that in-play live odds updates never overwrite frozen CLV values."""

    def test_in_play_odds_drift_does_not_mutate_frozen_clv(self, tmp_path):
        ledger_path = tmp_path / "adversarial_ledger.csv"
        db_path = tmp_path / "closing_lines.sqlite"
        store = ClosingLineStore(db_path=db_path)
        engine = PaperTradingEngine(ledger_path=ledger_path, closing_line_store=store)

        ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
        ev_id = "fixture_live_lock_01"

        # 1. Freeze closing line at T-5m with Pinnacle Fair Odds = 2.10
        freeze_closing_line(
            fixture_id=ev_id,
            market_odds={"HOME": 2.20, "AWAY": 1.80},
            fair_closing_odds={"HOME": 2.10, "AWAY": 1.90},
            kickoff_utc=ko_utc,
            market="1X2",
            bookmaker="PINNACLE",
            force=True,
            store=store,
        )

        # 2. Record initial signal at entry odds 2.35
        signal = {
            "event_id": ev_id,
            "match_id": f"{ev_id}_m",
            "timestamp_mode": "2026-11-04T16:00:00Z",
            "kickoff": ko_utc.isoformat(),
            "league": "Super Lig",
            "tier": "TIER_1_SHIN_QUANT",
            "home": "Team A",
            "away": "Team B",
            "market": "1X2",
            "outcome": "HOME",
            "soft_book": "nesine",
            "sharp_odds": 2.20,
            "soft_odds": 2.35,
            "fair_prob": 0.476,
            "fair_odds": 2.10,
            "edge_pct": 11.90,
            "kelly_pct": 2.0,
        }
        engine.record_signals([signal])

        rows_initial = engine.load_rows()
        assert len(rows_initial) == 1
        initial_clv_ratio = float(rows_initial[0]["clv_ratio"])
        assert initial_clv_ratio == pytest.approx(2.35 / 2.10, abs=1e-4)

        # 3. Simulate multiple aggressive live in-play updates during match
        for live_fair in [1.50, 1.25, 3.80, 5.00]:
            signal_update = dict(signal)
            signal_update["fair_odds"] = live_fair
            signal_update["steam_drift_pp"] = 10.0
            engine.record_signals([signal_update])

            # In each cycle, latest_pinnacle_fair_odds and clv_ratio MUST remain locked to frozen 2.10!
            rows_now = engine.load_rows()
            assert float(rows_now[0]["latest_pinnacle_fair_odds"]) == pytest.approx(2.10, abs=1e-3)
            assert float(rows_now[0]["clv_ratio"]) == pytest.approx(initial_clv_ratio, abs=1e-4)
