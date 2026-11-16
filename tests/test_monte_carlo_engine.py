"""Unit and Integration tests for Monte Carlo Simulation Engine."""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from sports_engine.models.monte_carlo_engine import MonteCarloEngine, SimulationSummary


@pytest.fixture
def mc_engine():
    return MonteCarloEngine(default_trials=5000, seed=123)


def test_simulate_match_goals_distribution(mc_engine):
    """Verify that match goal distribution matches theoretical Poisson bounds."""
    # Balanced match with 1.4 goals each (expected ~2.8 total goals)
    sim = mc_engine.simulate_match_goals(home_exp_goals=1.4, away_exp_goals=1.4)

    assert 0.30 <= sim["p_home"] <= 0.45
    assert 0.20 <= sim["p_draw"] <= 0.32
    assert 0.30 <= sim["p_away"] <= 0.45
    assert 0.45 <= sim["p_over_25"] <= 0.60
    assert 0.40 <= sim["p_under_25"] <= 0.55
    assert sim["p_6plus"] <= 0.08  # Baseline 6+ goals is low


def test_simulate_two_leg_accumulator_coupon(mc_engine):
    """Verify accumulator coupon simulation computes EV, VaR, and risk tier."""
    selections = [
        {"prob": 0.75, "market": "1-X Çifte Şans"},
        {"prob": 0.70, "market": "3.5 ALT"},
    ]
    # Offered odds 2.10 vs true joint prob ~ 0.525 (fair odds ~ 1.90)
    summary = mc_engine.simulate_coupon(
        selections=selections,
        offered_total_odds=2.10,
        stake=50.0,
    )

    assert summary.trials == 5000
    assert 0.49 <= summary.win_probability <= 0.56
    assert summary.expected_value_pct > 0.0  # Positive EV!
    assert summary.risk_tier in ("PRIME_VALUE", "CONTROLLED_RISK")
    assert summary.var_95_pct == -50.0       # Max loss in worst 5% is the stake


def test_negative_ev_trap_detection(mc_engine):
    """Verify that a speculative low-probability coupon is classified as a trap."""
    selections = [
        {"prob": 0.30, "market": "MS X"},
        {"prob": 0.30, "market": "MS X"},
    ]
    # Joint prob ~ 0.09 (fair ~ 11.1), offered only 8.00 -> negative EV
    summary = mc_engine.simulate_coupon(
        selections=selections,
        offered_total_odds=8.00,
        stake=50.0,
    )

    assert summary.expected_value_pct < 0.0
    assert summary.risk_tier == "HIGH_VARIANCE_TRAP"
