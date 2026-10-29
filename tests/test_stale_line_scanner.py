"""Unit and integration tests for sports-engine/src/stale_line_scanner.py."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stale_line_scanner import (  # noqa: E402
    compute_ev,
    compute_kelly_fraction,
    devig,
    devig_multiplicative,
    devig_power,
    devig_shin,
    scan_stale_lines,
)


def test_devig_probabilities_sum_to_one():
    odds_1x2 = (2.10, 3.40, 3.60)
    for method in ("multiplicative", "power", "shin"):
        probs = devig(odds_1x2, method=method)
        assert len(probs) == 3
        assert math.isclose(sum(probs), 1.0, rel_tol=1e-6)
        assert all(0.0 < p < 1.0 for p in probs)


def test_shin_and_power_penalize_longshot_more_than_multiplicative():
    """Favourite-longshot bias: Shin and Power assign slightly lower fair prob to longshot than multiplicative."""
    odds = (1.35, 5.00, 9.50)
    p_mult = devig_multiplicative(odds)
    p_pow = devig_power(odds)
    p_shin = devig_shin(odds)

    # Favourite probability is higher under power/shin than multiplicative
    assert p_pow[0] > p_mult[0]
    assert p_shin[0] > p_mult[0]
    # Longshot probability is lower under power/shin than multiplicative
    assert p_pow[2] < p_mult[2]
    assert p_shin[2] < p_mult[2]


def test_devig_rejects_invalid_odds():
    with pytest.raises(ValueError):
        devig_multiplicative([1.80])
    with pytest.raises(ValueError):
        devig_shin([1.0, 2.0])
    with pytest.raises(ValueError):
        devig_power([-2.0, 2.0])
    with pytest.raises(ValueError):
        devig([2.0, 2.0], method="nonexistent")


def test_ev_and_kelly_boundaries():
    # Negative EV -> 0 Kelly stake
    assert compute_ev(0.30, 3.10) < 0.0
    assert compute_kelly_fraction(0.30, 3.10) == 0.0

    # Positive EV -> capped at max_stake (default 5%)
    ev = compute_ev(0.35, 3.40)
    assert math.isclose(ev, 0.19, rel_tol=1e-6)
    kelly = compute_kelly_fraction(0.35, 3.40, fraction=0.5, max_stake=0.05)
    assert math.isclose(kelly, min(0.05, 0.5 * (0.19 / 2.40)), rel_tol=1e-6)


def test_lookahead_guardrail_raises_on_mismatched_timestamps():
    bad_input = [
        {
            "home": "Team A",
            "away": "Team B",
            "sharp_timestamp": "closing",
            "soft_timestamp": "opening",
            "sharp_1x2": (2.10, 3.10, 3.80),
            "soft_1x2": (2.05, 3.60, 3.70),
        }
    ]
    with pytest.raises(ValueError, match="Look-ahead violation"):
        scan_stale_lines(bad_input)


def test_scan_stale_lines_detects_draw_and_under_edges():
    matches = [
        {
            "match_id": "M1",
            "league": "I2",
            "home": "Bari",
            "away": "Pisa",
            "sharp_timestamp": "live_t-30m",
            "soft_timestamp": "live_t-30m",
            "sharp_open_1x2": (2.50, 3.20, 3.00),
            "sharp_1x2": (2.65, 2.85, 3.10),  # Sharp draw steamed down to 2.85
            "soft_1x2": (2.45, 3.35, 2.95),   # Soft book still stale at 3.35
            "sharp_ou25": (2.30, 1.68),
            "soft_ou25": (2.15, 1.85),        # Soft book stale on Under 2.5 at 1.85
        }
    ]
    sigs = scan_stale_lines(matches, devig_method="shin", min_edge=0.02)
    assert len(sigs) == 2
    outcomes = {s.outcome: s for s in sigs}
    assert "DRAW" in outcomes
    assert "UNDER_2.5" in outcomes
    assert outcomes["DRAW"].edge_pct > 5.0
    assert outcomes["DRAW"].steam_drift_pp is not None and outcomes["DRAW"].steam_drift_pp > 0

