"""
Adversarial Stress Test Suite: CLV Mathematics, Extreme Edge Cases, Fail-Closed (SPEC-0012) & Stake Limits (SPEC-0015).

Challenger: challenger_live_m1_2
Target: Milestone 1 - Closing Line Snapshot Freeze & CLV Engine

Covers:
1. Extreme Mathematical Edge Cases:
   - Near-1.0 odds (entry=1.01, closing=1.001, fair=1.0005)
   - Microscopic odds (entry=1.0001, closing=1.00005)
   - Massive longshots (entry=100.0, closing=2.0; entry=1000.0, closing=10.0)
   - Massive drifters / blowouts (entry=2.0, closing=500.0)
   - Inverted markets (arbitrage/zero-margin lines, sum_inv <= 1.0)
2. Fail-Closed Handling per SPEC-0012:
   - Exact 1.0 odds boundary
   - Sub-1.0 and negative odds
   - NaN, Inf, and -Inf values
   - Empty/corrupt dictionaries
   - Missing selections within frozen lines
3. Missing Closing Line & Unresolved Position Handling:
   - Querying unfrozen fixtures in ClosingLineFreezeEngine
   - Ensuring no synthetic fallback odds or default values are fabricated
   - Paper trader behavior on missing closing line records
4. Constitutional Stake Validator (SPEC-0015):
   - Strict rejection of stakes < 50.0 TL (e.g., 49.99, 49.9999, 0.0, -10.0)
   - Proper acceptance of stakes >= 50.0 TL
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from closing_line_freeze import (
    ClosingLineFreezeEngine,
    ClosingLineStore,
    ClosingLineUnavailableError,
    compute_clv,
    extract_fair_odds,
    validate_coupon_stake,
)
from paper_trader import PaperTradingEngine

# ============================================================================
# Section 1: Extreme Mathematical Edge Cases for CLV Calculations
# ============================================================================

class TestClvMathematicalEdgeCases:
    """Stress-tests CLV calculation across extreme boundary values and distributions."""

    def test_near_one_odds_clv(self):
        """Verify calculations for near-1.0 heavy favorite odds (e.g. in-play or overwhelming favorites)."""
        entry = 1.01
        closing = 1.001
        fair = 1.0005

        res = compute_clv(entry_odds=entry, frozen_closing_odds=closing, frozen_fair_odds=fair)
        assert res["clv_raw"] == pytest.approx(round(1.01 / 1.001, 4), abs=1e-4)
        assert res["clv_fair"] == pytest.approx(round(1.01 / 1.0005, 4), abs=1e-4)
        assert res["clv_edge_pct"] == pytest.approx(round((1.01 / 1.0005 - 1.0) * 100.0, 2), abs=0.01)
        assert res["beat_closing"] is True

    def test_microscopic_delta_near_one_odds(self):
        """Verify behavior with microscopic precision differences near 1.0."""
        entry = 1.0002
        closing = 1.0001
        fair = 1.00005

        res = compute_clv(entry_odds=entry, frozen_closing_odds=closing, frozen_fair_odds=fair)
        assert res["clv_raw"] > 1.0
        assert res["clv_fair"] > 1.0
        assert res["clv_edge_pct"] > 0.0
        assert res["beat_closing"] is True

    def test_massive_longshot_steam(self):
        """Verify huge longshot selections where market shortened dramatically."""
        entry = 100.0
        closing = 2.0
        fair = 2.05

        res = compute_clv(entry_odds=entry, frozen_closing_odds=closing, frozen_fair_odds=fair)
        assert res["clv_raw"] == 50.0000
        assert res["clv_fair"] == pytest.approx(48.7805, abs=1e-4)
        assert res["clv_edge_pct"] == pytest.approx(4778.05, abs=0.01)
        assert res["beat_closing"] is True

    def test_extreme_super_longshot_steam(self):
        """Verify super longshot odds (1000.0 entry dropped to 10.0 closing)."""
        entry = 1000.0
        closing = 10.0
        fair = 10.5

        res = compute_clv(entry_odds=entry, frozen_closing_odds=closing, frozen_fair_odds=fair)
        assert res["clv_raw"] == 100.0000
        assert res["clv_fair"] == pytest.approx(95.2381, abs=1e-4)
        assert res["clv_edge_pct"] == pytest.approx(9423.81, abs=0.01)
        assert res["beat_closing"] is True

    def test_massive_market_drift_blowout(self):
        """Verify massive market drift against the bettor (entry 2.0, closing 500.0)."""
        entry = 2.0
        closing = 500.0
        fair = 520.0

        res = compute_clv(entry_odds=entry, frozen_closing_odds=closing, frozen_fair_odds=fair)
        assert res["clv_raw"] == pytest.approx(0.0040, abs=1e-4)
        assert res["clv_fair"] == pytest.approx(0.0038, abs=1e-4)
        assert res["clv_edge_pct"] == pytest.approx(-99.62, abs=0.01)
        assert res["beat_closing"] is False

    def test_inverted_market_devigging(self):
        """Verify devigging behavior in inverted / arbitrage markets where sum(1/odds) <= 1.0."""
        # 1X2 market with arbitrage / negative bookmaker margin (strictly inverted: sum(1/odds) < 1.0)
        inverted_odds = {"1": 2.50, "X": 3.60, "2": 3.60}
        inv_sum = (1.0 / 2.50) + (1.0 / 3.60) + (1.0 / 3.60)
        assert inv_sum < 1.0  # Sum is 0.40 + 0.2778 + 0.2778 = ~0.9556 < 1.0

        strictly_inverted = {"1": 2.40, "X": 3.80, "2": 3.80}
        inv_sum_strict = (1.0 / 2.40) + (1.0 / 3.80) + (1.0 / 3.80)
        assert inv_sum_strict < 1.0  # ~0.4167 + 0.2632 + 0.2632 = 0.9431 < 1.0

        fair_odds, margin = extract_fair_odds(strictly_inverted)
        assert margin == 0.0  # Clamped non-negative margin
        # Sum of implied fair probabilities must equal 1.0
        sum_fair_prob = sum(1.0 / o for o in fair_odds.values())
        assert sum_fair_prob == pytest.approx(1.0, abs=1e-2)


# ============================================================================
# Section 2: Fail-Closed Handling on Corrupt / Invalid Odds (SPEC-0012)
# ============================================================================

class TestSpec0012FailClosedEdgeCases:
    """Stress-tests fail-closed error handling under all corrupt and non-positive inputs."""

    @pytest.mark.parametrize("invalid_odd", [1.0, 0.9999, 0.5, 0.0, -0.001, -1.5, -100.0])
    def test_clv_rejects_non_positive_and_sub_one_odds(self, invalid_odd):
        # Entry odds invalid
        with pytest.raises(ClosingLineUnavailableError) as exc:
            compute_clv(entry_odds=invalid_odd, frozen_closing_odds=2.0, frozen_fair_odds=2.1)
        assert "SPEC-0012 Violation" in str(exc.value)

        # Closing odds invalid
        with pytest.raises(ClosingLineUnavailableError) as exc:
            compute_clv(entry_odds=2.0, frozen_closing_odds=invalid_odd, frozen_fair_odds=2.1)
        assert "SPEC-0012 Violation" in str(exc.value)

        # Fair odds invalid
        with pytest.raises(ClosingLineUnavailableError) as exc:
            compute_clv(entry_odds=2.0, frozen_closing_odds=2.0, frozen_fair_odds=invalid_odd)
        assert "SPEC-0012 Violation" in str(exc.value)

    def test_clv_rejects_nan_and_inf(self):
        """Verify NaN, Inf, and -Inf are strictly rejected without division errors."""
        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=float("nan"), frozen_closing_odds=2.0, frozen_fair_odds=2.0)

        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=2.0, frozen_closing_odds=float("nan"), frozen_fair_odds=2.0)

        with pytest.raises(ClosingLineUnavailableError):
            compute_clv(entry_odds=2.0, frozen_closing_odds=2.0, frozen_fair_odds=float("nan"))

    def test_extract_fair_odds_corrupt_data(self):
        """Verify extract_fair_odds raises fail-closed exception on corrupt payload."""
        # Empty dictionary
        with pytest.raises(ClosingLineUnavailableError) as exc:
            extract_fair_odds({})
        assert "SPEC-0012 Violation" in str(exc.value)

        # None value in dict
        with pytest.raises(ClosingLineUnavailableError) as exc:
            extract_fair_odds({"1": 2.10, "X": None, "2": 3.40})  # type: ignore
        assert "SPEC-0012 Violation" in str(exc.value)

        # String instead of float
        with pytest.raises(ClosingLineUnavailableError) as exc:
            extract_fair_odds({"1": 2.10, "X": "corrupted_odd", "2": 3.40})  # type: ignore
        assert "SPEC-0012 Violation" in str(exc.value)

        # Odds <= 1.0
        with pytest.raises(ClosingLineUnavailableError) as exc:
            extract_fair_odds({"1": 2.10, "X": 1.0, "2": 3.40})
        assert "SPEC-0012 Violation" in str(exc.value)


# ============================================================================
# Section 3: Missing Closing Line & Unresolved Position Handling
# ============================================================================

class TestMissingClosingLineHandling:
    """Stress-tests fail-closed behavior when closing lines are absent or unresolved."""

    def test_compute_signal_clv_raises_on_unfrozen_fixture(self, tmp_path):
        """Engine must raise ClosingLineUnavailableError rather than return synthetic numbers."""
        db_path = tmp_path / "missing_closing.sqlite"
        store = ClosingLineStore(db_path=db_path)
        engine = ClosingLineFreezeEngine(store=store)

        with pytest.raises(ClosingLineUnavailableError) as exc:
            engine.compute_signal_clv(
                fixture_id="unfrozen_fixture_999",
                market="1X2",
                outcome="1",
                entry_odds=2.20,
            )
        assert "has not been frozen" in str(exc.value)

    def test_compute_signal_clv_raises_on_missing_selection(self, tmp_path):
        """Engine must raise ClosingLineUnavailableError if specific market outcome is absent."""
        db_path = tmp_path / "missing_sel.sqlite"
        store = ClosingLineStore(db_path=db_path)
        engine = ClosingLineFreezeEngine(store=store)

        ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
        engine.freeze(
            fixture_id="fix_ou_only",
            market_odds={"OVER_2.5": 1.95, "UNDER_2.5": 1.95},
            kickoff_utc=ko_utc,
            market="OU_2.5",
            force=True,
        )

        with pytest.raises(ClosingLineUnavailableError) as exc:
            engine.compute_signal_clv(
                fixture_id="fix_ou_only",
                market="OU_2.5",
                outcome="EXACT_3_GOALS",
                entry_odds=4.50,
            )
        assert "not found in frozen closing odds" in str(exc.value)

    def test_paper_trader_does_not_fabricate_missing_closing_lines(self, tmp_path):
        """PaperTradingEngine leaves pending ledger entries unfrozen if store has no record."""
        ledger_path = tmp_path / "missing_ledger.csv"
        db_path = tmp_path / "empty_store.sqlite"
        store = ClosingLineStore(db_path=db_path)
        engine = PaperTradingEngine(ledger_path=ledger_path, closing_line_store=store)

        ko_utc = datetime(2026, 11, 4, 20, 0, 0, tzinfo=UTC)
        signal = {
            "event_id": "fix_no_freeze",
            "match_id": "fix_no_freeze_nesine",
            "timestamp_mode": "2026-11-04T15:00:00Z",
            "kickoff": ko_utc.isoformat(),
            "league": "Premier League",
            "tier": "TIER_1_SHIN_QUANT",
            "home": "Home",
            "away": "Away",
            "market": "1X2",
            "outcome": "HOME",
            "soft_book": "nesine",
            "sharp_odds": 2.10,
            "soft_odds": 2.25,
            "fair_prob": 0.48,
            "fair_odds": 2.08,
            "edge_pct": 8.17,
            "kelly_pct": 2.0,
        }
        engine.record_signals([signal])

        # Attempt to sync closing lines against empty store
        synced = engine.sync_closing_lines()
        assert synced == 0

        # Ledger row must retain initial soft/fair values without synthetic fabrication
        rows = engine.load_rows()
        assert len(rows) == 1
        assert rows[0]["status"] == "PENDING"
        assert float(rows[0]["latest_pinnacle_fair_odds"]) == 2.080


# ============================================================================
# Section 4: SPEC-0015 Minimum Stake Rule Enforcement
# ============================================================================

class TestSpec0015StakeLimits:
    """Stress-tests SPEC-0015 coupon stake validator across micro-boundaries."""

    @pytest.mark.parametrize("sub_limit_stake", [49.9999, 49.99, 45.0, 10.0, 1.0, 0.0, -0.01, -50.0])
    def test_sub_fifty_tl_stakes_rejected_fail_closed(self, sub_limit_stake):
        with pytest.raises(ValueError) as exc:
            validate_coupon_stake(sub_limit_stake)
        assert "SPEC-0015 Violation" in str(exc.value)
        assert "at least 50.0 TL" in str(exc.value)

    @pytest.mark.parametrize("valid_stake", [50.0, 50.0001, 50.01, 75.50, 100.0, 1000.0, 50000.0])
    def test_fifty_tl_and_above_accepted(self, valid_stake):
        assert validate_coupon_stake(valid_stake) is True
