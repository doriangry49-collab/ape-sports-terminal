"""
Unit tests for sports_engine.src.value_engine.
Verifies SPEC-0012 (Fail-closed), SPEC-0013 (Kickoff TRT timing),
SPEC-0014 (12-Hour window), Shin devigged +EV edge detection, and Telegram formatting.
"""

import os
import sys
from datetime import UTC, datetime

import pytest

# Ensure src directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from value_engine import (
    TRT_TZ,
    MatchTimingError,
    ValueEngineError,
    ValueScannerEngine,
    check_kickoff_window,
    compute_half_kelly,
    normalize_to_trt,
)


def test_normalize_to_trt():
    utc_dt = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    trt_dt = normalize_to_trt(utc_dt)
    assert trt_dt.hour == 13
    assert trt_dt.tzinfo == TRT_TZ


def test_check_kickoff_window_spec0013_expired_match():
    # Match kickoff is in the past or within 3 minutes from now
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    expired_kickoff = datetime(2026, 11, 3, 12, 2, tzinfo=UTC)  # only +2 min (< +3 min)

    valid, reason = check_kickoff_window(expired_kickoff, reference_now=now_ref)
    assert not valid
    assert "SPEC-0013 Violation" in reason


def test_check_kickoff_window_spec0014_exceeds_12h():
    # Match kickoff is 15 hours in the future
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    future_kickoff = datetime(2026, 11, 4, 4, 0, tzinfo=UTC)  # +16 hours

    valid, reason = check_kickoff_window(future_kickoff, reference_now=now_ref)
    assert not valid
    assert "SPEC-0014 Violation" in reason


def test_check_kickoff_window_valid():
    # Match kickoff is 4 hours in the future (within [now+3m, now+12h])
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    valid_kickoff = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)

    valid, reason = check_kickoff_window(valid_kickoff, reference_now=now_ref)
    assert valid
    assert reason == "OK"


def test_compute_half_kelly():
    # 50% win probability at 2.20 odds -> EV = 0.5 * 2.2 - 1 = +10%
    # Full Kelly = 0.10 / (2.2 - 1) = 0.10 / 1.2 = 0.0833
    # Half Kelly = 0.5 * 0.0833 = 0.0417 (~4.17%)
    k = compute_half_kelly(0.50, 2.20)
    assert 0.04 <= k <= 0.05

    # Negative EV should yield 0.0
    assert compute_half_kelly(0.40, 2.00) == 0.0


def test_scan_1x2_fixture_positive_ev_detected():
    engine = ValueScannerEngine(min_ev_roi=0.03, min_prob_edge=0.015)
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    kickoff = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)  # +3h (valid)

    # Market odds: Home=2.40, Draw=3.20, Away=3.20 (Fair home ~39%)
    # Model assigns 48% to Home win -> EV = 0.48 * 2.40 - 1 = +15.2% ROI!
    market_odds = [2.40, 3.20, 3.20]
    model_probs = [0.48, 0.28, 0.24]

    signals = engine.scan_1x2_fixture(
        fixture_id="fix-101",
        league="Turkish Süper Lig",
        home_team="Galatasaray",
        away_team="Fenerbahce",
        kickoff_dt=kickoff,
        market_odds=market_odds,
        model_probs=model_probs,
        bookmaker="Nesine",
        reference_now=now_ref,
    )

    assert len(signals) == 1
    sig = signals[0]
    assert sig.fixture_id == "fix-101"
    assert sig.home_team == "Galatasaray"
    assert "1" in sig.selection
    assert sig.offered_odds == 2.40
    assert sig.ev_roi > 10.0  # +15.2%
    assert sig.edge_pct > 5.0
    assert sig.half_kelly > 0.0
    assert sig.shin_margin > 0.0

    # Verify Telegram formatting
    msg = engine.format_vip_telegram_message(sig)
    assert "Galatasaray" in msg
    assert "Fenerbahce" in msg
    assert "EV DEĞER SİNYALİ" in msg
    assert "Nesine" in msg


def test_scan_1x2_fixture_timing_violation_raises():
    engine = ValueScannerEngine()
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    expired_kickoff = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)  # in the past

    with pytest.raises(MatchTimingError, match="SPEC-0013"):
        engine.scan_1x2_fixture(
            fixture_id="fix-999",
            league="Premier League",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_dt=expired_kickoff,
            market_odds=[2.0, 3.4, 3.8],
            reference_now=now_ref,
        )


def test_scan_1x2_fail_closed_degenerate_odds():
    engine = ValueScannerEngine(enforce_time_window=False)
    now_ref = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    kickoff = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)

    # Odds <= 1.0 must fail closed (SPEC-0012)
    with pytest.raises(ValueEngineError, match="SPEC-0012 Violation"):
        engine.scan_1x2_fixture(
            fixture_id="fix-err",
            league="La Liga",
            home_team="Real Madrid",
            away_team="Barcelona",
            kickoff_dt=kickoff,
            market_odds=[0.95, 3.5, 4.0],
            reference_now=now_ref,
        )
