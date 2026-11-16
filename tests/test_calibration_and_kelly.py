"""Unit and property tests for Calibration & Kelly Staking (Feature F6).

Verifies:
1. Platt / Logistic scaling corrects favorite-longshot bias (TASK-016 empirical findings).
2. Multi-class Temperature scaling preserves rank-order and moderates overconfidence.
3. Pure-Python PAVA Isotonic calibration enforces strict monotonicity.
4. Bounded Fractional Kelly eliminates dangerous 45% flat stakes.
5. Dual-regime bankroll sizing: Macro regime (<= 5% cap) vs Micro regime (discrete units with ruin control).
6. Non-positive EV hurdle strictly rejects negative expectation tickets.
"""

from __future__ import annotations

import pytest

from bankroll_builder import build_recovery_portfolio
from discrete_kelly_optimizer import (
    DiscreteKellyOptimizer,
)
from sports_engine.models.calibration import (
    IsotonicProbabilityCalibrator,
    LogisticProbabilityCalibrator,
    TemperatureScalingCalibrator,
    recalibrate_1x2,
    recalibrate_score_grid,
)


def test_logistic_calibrator_corrects_favorite_longshot_bias():
    """Logistic calibrator compresses heavy favorites and lifts underdogs towards empirical reality."""
    calibrator = LogisticProbabilityCalibrator(shrinkage_a=0.68, draw_bias_b=0.08)

    # Favorite: raw 70% probability
    # Underdog: raw 10% probability
    # Draw: raw 20% probability
    p_h_cal, p_d_cal, p_a_cal = calibrator.calibrate_1x2(0.70, 0.20, 0.10)

    # Sum must be 1.0
    assert pytest.approx(p_h_cal + p_d_cal + p_a_cal, abs=1e-3) == 1.0

    # Overconfident favorite is compressed downwards
    assert p_h_cal < 0.70
    assert 0.55 <= p_h_cal <= 0.65

    # Underestimated underdog is lifted upwards
    assert p_a_cal > 0.10
    assert 0.12 <= p_a_cal <= 0.22


def test_recalibrate_1x2_convenience_functions():
    """recalibrate_1x2 supports logistic, temperature, and isotonic methods."""
    for method in ["logistic", "temperature", "isotonic"]:
        h, d, a = recalibrate_1x2(0.50, 0.30, 0.20, method=method)
        assert pytest.approx(h + d + a, abs=1e-3) == 1.0
        assert h > d > a  # Order preserved


def test_temperature_scaling_preserves_ordering():
    """Temperature scaling softens probabilities while strictly preserving relative rank order."""
    temp_cal = TemperatureScalingCalibrator(temperature=1.40)
    h, d, a = temp_cal.calibrate_1x2(0.65, 0.25, 0.10)

    assert pytest.approx(h + d + a, abs=1e-3) == 1.0
    assert h < 0.65  # Softened from extreme
    assert a > 0.10  # Underdog softened upwards
    assert h > d > a  # Rank order strictly identical


def test_isotonic_pava_monotonicity_from_disordered_data():
    """Pure-Python PAVA fits monotonic non-decreasing knots from disordered empirical inputs."""
    # Disordered probabilities and empirical outcomes
    predicted = [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90]
    outcomes = [0.0, 0.5, 0.2, 0.6, 0.4, 0.9, 0.8]  # Non-monotonic raw noise

    cal = IsotonicProbabilityCalibrator.fit_pava(predicted, outcomes)
    knots = cal.knots

    # Knots must be strictly non-decreasing in both x and y
    for i in range(len(knots) - 1):
        assert knots[i].x <= knots[i + 1].x
        assert knots[i].y <= knots[i + 1].y

    # Monotonic evaluation test
    p_vals = [0.05, 0.15, 0.30, 0.45, 0.60, 0.75, 0.85, 0.95]
    cal_vals = [cal.calibrate(p) for p in p_vals]
    for i in range(len(cal_vals) - 1):
        assert cal_vals[i] <= cal_vals[i + 1]


def test_recalibrate_score_grid():
    """Score grid temperature scaling preserves probability mass sum == 1.0."""
    grid = {
        (0, 0): 0.10,
        (1, 0): 0.25,
        (0, 1): 0.15,
        (1, 1): 0.20,
        (2, 0): 0.15,
        (0, 2): 0.10,
        (2, 1): 0.05,
    }
    scaled = recalibrate_score_grid(grid, temperature=1.20)
    assert abs(sum(scaled.values()) - 1.0) < 1e-5


def test_discrete_kelly_ev_hurdle_rejects_negative_ev():
    """DiscreteKellyOptimizer rejects tickets with EV <= 0 (stake == 0, is_viable == False)."""
    opt = DiscreteKellyOptimizer()

    # 40% win prob at odds 2.0 -> EV = (0.40 * 2.0) - 1 = -0.20 (-20% EV)
    res = opt.compute_fractional_kelly_stake(
        current_bankroll=1000.0,
        win_prob=0.40,
        odds=2.0,
    )
    assert res["is_viable"] is False
    assert res["stake"] == 0.0
    assert "below threshold" in res["reason"]


def test_discrete_kelly_macro_regime_caps_to_five_percent():
    """On macro bankrolls, single ticket stake is strictly capped at <= 5% of bankroll."""
    opt = DiscreteKellyOptimizer(max_allocation_cap=0.05)
    macro_bankroll = 10000.0  # 10,000 TL bankroll

    # Even with a massive +EV bet (win_prob 0.80 at odds 2.0 -> EV = +60%, full Kelly = 60%)
    res = opt.compute_fractional_kelly_stake(
        current_bankroll=macro_bankroll,
        win_prob=0.80,
        odds=2.0,
        min_ticket_cost=50.0,
        kelly_fraction=0.25,
    )

    assert res["is_viable"] is True
    assert res["regime"] == "MACRO"
    # Max allocation cap is 5% -> exactly 500 TL (NEVER 45% = 4,500 TL!)
    assert res["stake"] <= 500.0
    assert res["stake"] == 500.0
    assert res["remaining_bankroll"] == 9500.0


def test_discrete_kelly_micro_regime_bounds_to_discrete_unit():
    """On micro bankrolls (< 1,000 TL), stake is bounded to min_ticket_cost with reserve protection."""
    opt = DiscreteKellyOptimizer(max_allocation_cap=0.05)
    micro_bankroll = 127.19

    # Highly favorable bet (75% win prob at odds 1.90)
    res = opt.compute_fractional_kelly_stake(
        current_bankroll=micro_bankroll,
        win_prob=0.75,
        odds=1.90,
        min_ticket_cost=50.0,
    )

    assert res["is_viable"] is True
    assert res["regime"] == "MICRO"
    assert res["stake"] == 50.0  # Discrete unit
    assert res["remaining_bankroll"] == pytest.approx(77.19, abs=0.01)
    assert res["is_bankroll_protected"] is True  # 77.19 TL >= 50 TL reserve


def test_bankroll_builder_eliminates_forty_five_percent_hazard():
    """build_recovery_portfolio eliminates 45% flat stake and enforces Kelly bounds."""
    candidates = [
        {"match": "Match A", "market": "ÇŞ 1X", "odds": 1.40, "prob": 0.80, "edge_pct": 12.0},
        {"match": "Match B", "market": "DNB 1", "odds": 1.50, "prob": 0.75, "edge_pct": 12.5},
    ]

    # Test with macro bankroll of 5,000 TL
    port_macro = build_recovery_portfolio(
        candidates=candidates,
        current_bankroll=5000.0,
        min_ticket_cost=50.0,
    )

    t1 = port_macro["tier1_capital_shield"]
    assert t1 is not None
    # 5% of 5,000 TL is 250 TL. Old 45% formula would stake 2,250 TL!
    assert t1["stake"] <= 250.0
    assert t1["remaining_bankroll"] >= 4750.0
    assert "kelly_metrics" in t1
    assert t1["kelly_metrics"]["regime"] == "MACRO"
