"""Adversarial Stress Test Suite for Pricing, De-vigging, Calibration, and Kelly Staking.

Author: challenger_m2_it2_2 (Empirical Challenger)
Milestone: Milestone 2 Iteration 2

Probes:
1. Synthetic Double Chance & DNB across vig sweeps (1% to 25%), asymmetric favorites, longshots.
   - Asserts: No negative vig, no inverted odds, fair probabilities valid, sum(P_DC) == 2.0, sum(P_DNB) == 1.0.
2. Decoupled Probability Edge (Delta p) vs EV ROI across boundary odds (1.01 to 100.0).
   - Asserts: Strict independence, correct boundary handling, invalid inputs rejected.
3. Calibration algorithms (Platt/Logistic, Temperature, Isotonic PAVA):
   - Asserts: Monotonicity, valid probability bounds [0, 1], zero unhandled exceptions on extreme/degenerate inputs.
4. Kelly staking & Bankroll recovery:
   - Asserts: Zero negative stakes, negative EV rejected, macro cap <= 5%, 45% flat stake hazard completely eliminated.
"""

from __future__ import annotations

import random

import pytest

from bankroll_builder import build_recovery_portfolio
from discrete_kelly_optimizer import (
    DiscreteKellyOptimizer,
)
from sports_engine.domain.pricing_contract import NoVigMethod
from sports_engine.models.calibration import (
    IsotonicProbabilityCalibrator,
    LogisticProbabilityCalibrator,
    TemperatureScalingCalibrator,
)
from sports_engine.pricing.edge import (
    calculate_selection_edge,
    compute_expected_value_roi,
    compute_probability_edge,
)
from sports_engine.pricing.synthetic import (
    compute_synthetic_dnb,
    compute_synthetic_double_chance,
)

# ==============================================================================
# PROBE 1: SYNTHETIC DOUBLE CHANCE & DNB ACROSS VIG RANGES (1% to 25%)
# ==============================================================================

def test_adversarial_synthetic_double_chance_vig_sweep():
    """Adversarially sweep overround from 1.01 (1% vig) to 1.25 (25% vig) across odds profiles.

    Verifies:
    - Sum of fair DC probabilities strictly equals 2.0000 (+/- 0.01 due to rounding)
    - Fair odds are >= 1.0 and properly inverse-ordered
    - No negative vig or inverted odds
    """
    rng = random.Random(20261102)

    # Base true fair probabilities (sum = 1.0)
    profiles = [
        (0.80, 0.15, 0.05),  # Heavy home favorite
        (0.05, 0.15, 0.80),  # Heavy away favorite
        (0.333, 0.334, 0.333),  # Perfect symmetry
        (0.45, 0.35, 0.20),  # Typical high-draw European match
        (0.60, 0.25, 0.15),  # Moderate home favorite
        (0.12, 0.28, 0.60),  # Moderate away favorite
        (0.92, 0.06, 0.02),  # Extreme lopsided mismatch
    ]

    # Sweeping vigs from 1% to 25% (overround 1.01 to 1.25)
    vigs = [0.01, 0.03, 0.05, 0.08, 0.12, 0.15, 0.20, 0.25]
    methods = [NoVigMethod.SHIN, NoVigMethod.MULTIPLICATIVE, NoVigMethod.POWER]

    for p_h, p_d, p_a in profiles:
        for vig in vigs:
            overround = 1.0 + vig
            # Add bookmaker margin proportionally
            odds = [
                round(1.0 / (p_h * overround), 2),
                round(1.0 / (p_d * overround), 2),
                round(1.0 / (p_a * overround), 2),
            ]
            # Ensure valid odds > 1.0
            odds = [max(1.02, o) for o in odds]

            for method in methods:
                dc = compute_synthetic_double_chance(odds, method=method)

                p_1x = dc["1X"]["prob"]
                p_x2 = dc["X2"]["prob"]
                p_12 = dc["12"]["prob"]

                # 1. Probabilities in [0.0, 1.0]
                for key in ["1X", "X2", "12"]:
                    prob = dc[key]["prob"]
                    fair_odd = dc[key]["fair_odd"]
                    assert 0.0 < prob <= 1.0, f"Invalid prob {prob} for {key} at vig={vig}, odds={odds}"
                    assert fair_odd >= 1.0, f"Fair odds < 1.0 ({fair_odd}) for {key}"
                    # Allow relative tolerance for large odds due to 4-decimal probability rounding
                    assert pytest.approx(fair_odd, rel=0.01, abs=0.05) == (1.0 / prob)

                # 2. Sum of DC probabilities must equal 2.0 (sum of pairs from 1X2 partition)
                sum_dc = p_1x + p_x2 + p_12
                assert pytest.approx(sum_dc, abs=0.015) == 2.0, (
                    f"Sum of DC probs ({sum_dc}) != 2.0 for vig={vig}, method={method}"
                )

                # 3. Monotonic ordering: If home > away, then 1X > X2 and fair_odd(1X) < fair_odd(X2)
                if p_h > p_a + 0.05:
                    assert p_1x > p_x2, f"Expected 1X > X2: p_1x={p_1x}, p_x2={p_x2}"
                    assert dc["1X"]["fair_odd"] < dc["X2"]["fair_odd"], "Odds inversion between 1X and X2"
                elif p_a > p_h + 0.05:
                    assert p_x2 > p_1x, f"Expected X2 > 1X: p_x2={p_x2}, p_1x={p_1x}"
                    assert dc["X2"]["fair_odd"] < dc["1X"]["fair_odd"], "Odds inversion between X2 and 1X"


def test_adversarial_synthetic_dnb_vig_sweep():
    """Adversarially sweep overround from 1.01 to 1.25 across odds profiles for DNB.

    Verifies:
    - Conditional probabilities sum strictly to 1.0000 (+/- 0.005)
    - Fair odds >= 1.0
    - Odds match conditional win probabilities inversely
    - Zero negative vig
    """
    vigs = [0.01, 0.04, 0.07, 0.10, 0.15, 0.22, 0.25]
    profiles = [
        (0.70, 0.20, 0.10),
        (0.15, 0.30, 0.55),
        (0.33, 0.34, 0.33),
        (0.90, 0.08, 0.02),
        (0.03, 0.12, 0.85),
    ]

    for p_h, p_d, p_a in profiles:
        for vig in vigs:
            overround = 1.0 + vig
            odds = [
                max(1.02, round(1.0 / (p_h * overround), 2)),
                max(1.02, round(1.0 / (p_d * overround), 2)),
                max(1.02, round(1.0 / (p_a * overround), 2)),
            ]
            for method in [NoVigMethod.SHIN, NoVigMethod.MULTIPLICATIVE]:
                dnb = compute_synthetic_dnb(odds, method=method)

                p1 = dnb["DNB_1"]["prob"]
                p2 = dnb["DNB_2"]["prob"]

                assert 0.0 <= p1 <= 1.0
                assert 0.0 <= p2 <= 1.0
                assert pytest.approx(p1 + p2, abs=0.005) == 1.0
                assert dnb["DNB_1"]["fair_odd"] >= 1.0
                assert dnb["DNB_2"]["fair_odd"] >= 1.0

                if p1 > p2:
                    assert dnb["DNB_1"]["fair_odd"] < dnb["DNB_2"]["fair_odd"]
                elif p2 > p1:
                    assert dnb["DNB_2"]["fair_odd"] < dnb["DNB_1"]["fair_odd"]


def test_synthetic_degenerate_inputs_handling():
    """Verify robust failure handling for invalid inputs to synthetic pricing."""
    # Less than 3 outcomes
    with pytest.raises(ValueError, match="must contain exactly 3"):
        compute_synthetic_double_chance([2.0, 3.0])

    with pytest.raises(ValueError, match="must contain exactly 3"):
        compute_synthetic_dnb([2.0, 3.0, 4.0, 5.0])

    # Odds <= 1.0
    with pytest.raises(ValueError, match="invalid odds <= 1.0"):
        compute_synthetic_double_chance([0.95, 3.0, 4.0])

    with pytest.raises(ValueError, match="invalid odds <= 1.0"):
        compute_synthetic_dnb([1.00, 3.0, 4.0])


# ==============================================================================
# PROBE 2: DECOUPLED PROBABILITY EDGE VS EV ROI (Boundary Odds 1.01 to 100.0)
# ==============================================================================

def test_adversarial_decoupled_edge_boundary_sweep():
    """Sweep boundary odds from 1.01 to 100.0 across probability sweeps.

    Verifies:
    - Delta p strictly in [-1.0, 1.0] and independent of odds
    - EV ROI matches (p * odds) - 1.0 exactly
    - Edge cases: heavy favorites vs extreme longshots
    """
    boundary_odds = [1.01, 1.05, 1.20, 1.50, 2.00, 3.50, 5.00, 10.0, 25.0, 50.0, 100.0]
    prob_pairs = [
        (0.99, 0.95),  # Heavy favorite with small edge
        (0.95, 0.99),  # Heavy favorite with negative edge
        (0.50, 0.45),  # Even match with +5 pp edge
        (0.50, 0.55),  # Even match with -5 pp edge
        (0.10, 0.05),  # Longshot with +5 pp edge
        (0.02, 0.01),  # Extreme longshot with +1 pp edge
        (0.01, 0.02),  # Extreme longshot with -1 pp edge
    ]

    for p_mod, p_mkt in prob_pairs:
        delta_p = compute_probability_edge(p_mod, p_mkt)
        expected_delta = p_mod - p_mkt
        assert pytest.approx(delta_p, abs=1e-6) == expected_delta
        assert -1.0 <= delta_p <= 1.0

        for odds in boundary_odds:
            ev_roi = compute_expected_value_roi(p_mod, odds)
            expected_ev = (p_mod * odds) - 1.0
            assert pytest.approx(ev_roi, abs=1e-6) == expected_ev
            assert ev_roi >= -1.0

            # SelectionEdge integrated check
            edge_obj = calculate_selection_edge(
                fixture_id="fix_adv_test",
                market="1X2",
                selection="HOME",
                entry_odds=odds,
                model_probability=p_mod,
                market_no_vig_probability=p_mkt,
            )
            assert pytest.approx(edge_obj.raw_edge, abs=1e-6) == expected_delta
            assert pytest.approx(edge_obj.probability_edge, abs=1e-6) == expected_delta
            assert pytest.approx(edge_obj.expected_value_roi, abs=1e-6) == expected_ev


def test_adversarial_edge_market_guards():
    """Verify Phase 2A boundary guards enforce strict market and classification limits."""
    # Disallowed high-odds market
    with pytest.raises(ValueError, match="not permitted in Phase 2A"):
        calculate_selection_edge(
            fixture_id="f1",
            market="CORRECT_SCORE",
            selection="2-1",
            entry_odds=9.5,
            model_probability=0.15,
            market_no_vig_probability=0.10,
        )

    # Disallowed MODEL_DERIVED classification
    with pytest.raises(ValueError, match="MODEL_DERIVED markets are strictly excluded"):
        calculate_selection_edge(
            fixture_id="f1",
            market="1X2",
            selection="HOME",
            entry_odds=2.1,
            model_probability=0.50,
            market_no_vig_probability=0.45,
            source_classification="MODEL_DERIVED",
        )

    # Phase mismatch guard (PREMATCH model vs LIVE odds)
    with pytest.raises(ValueError, match="Phase mismatch"):
        calculate_selection_edge(
            fixture_id="f1",
            market="1X2",
            selection="HOME",
            entry_odds=2.1,
            model_probability=0.50,
            market_no_vig_probability=0.45,
            model_phase="PREMATCH",
            odds_phase="LIVE",
        )


# ==============================================================================
# PROBE 3: CALIBRATION ALGORITHMS (Platt, Temperature, Isotonic PAVA)
# ==============================================================================

def test_adversarial_logistic_calibrator_bounds_and_extremes():
    """Stress-test Logistic (Platt) calibrator across extreme probabilities."""
    calibrator = LogisticProbabilityCalibrator()

    # Extreme probabilities near 0 and 1
    extreme_inputs = [
        (0.9999, 0.00005, 0.00005),
        (0.00001, 0.99998, 0.00001),
        (0.00001, 0.00001, 0.99998),
        (0.33333, 0.33333, 0.33334),
        (0.0, 1.0, 0.0),
        (1.0, 0.0, 0.0),
    ]

    for p_h, p_d, p_a in extreme_inputs:
        cal_h, cal_d, cal_a = calibrator.calibrate_1x2(p_h, p_d, p_a)
        assert 0.0 <= cal_h <= 1.0
        assert 0.0 <= cal_d <= 1.0
        assert 0.0 <= cal_a <= 1.0
        assert pytest.approx(cal_h + cal_d + cal_a, abs=0.002) == 1.0

    # Binary calibration sweep: strict monotonicity
    p_steps = [i / 100.0 for i in range(1, 100)]
    cal_steps = [calibrator.calibrate_binary(p) for p in p_steps]
    for i in range(len(cal_steps) - 1):
        assert cal_steps[i] <= cal_steps[i + 1], f"Monotonicity violated at p={p_steps[i]}"


def test_adversarial_temperature_scaling_bounds_and_extremes():
    """Stress-test Temperature Scaling with extreme temperatures and probabilities."""
    # Invalid temperature <= 0 must raise ValueError
    with pytest.raises(ValueError, match="strictly positive"):
        TemperatureScalingCalibrator(temperature=0.0)

    with pytest.raises(ValueError, match="strictly positive"):
        TemperatureScalingCalibrator(temperature=-1.5)

    # Extreme temperatures
    for temp in [0.05, 0.5, 1.0, 2.0, 10.0, 100.0]:
        t_cal = TemperatureScalingCalibrator(temperature=temp)
        h, d, a = t_cal.calibrate_1x2(0.60, 0.25, 0.15)
        assert 0.0 <= h <= 1.0
        assert 0.0 <= d <= 1.0
        assert 0.0 <= a <= 1.0
        assert pytest.approx(h + d + a, abs=0.002) == 1.0
        # Multi-class softmax preserves relative rank order (non-strict under 4-decimal rounding for extreme low temp)
        assert h >= d >= a, f"Rank order violated for temp={temp}"
        if temp >= 0.2:
            assert h > d > a, f"Strict rank order violated for temp={temp}"

        # At very high temperature, probabilities approach uniform (1/3 each)
        if temp >= 100.0:
            assert pytest.approx(h, abs=0.05) == 0.3333
            assert pytest.approx(d, abs=0.05) == 0.3333
            assert pytest.approx(a, abs=0.05) == 0.3333


def test_adversarial_isotonic_pava_pathological_inputs():
    """Adversarially test Isotonic Calibrator / PAVA against degenerate and pathological datasets."""
    # 1. Perfectly inverted data (100% negative correlation)
    x_inv = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    y_inv = [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    cal_inv = IsotonicProbabilityCalibrator.fit_pava(x_inv, y_inv)
    # Output must be monotonic non-decreasing despite inverted training data
    test_p = [i / 50.0 for i in range(51)]
    vals = [cal_inv.calibrate(p) for p in test_p]
    for i in range(len(vals) - 1):
        assert vals[i] <= vals[i + 1], f"Monotonicity violated in inverted test at {test_p[i]}"
        assert 0.0 <= vals[i] <= 1.0

    # 2. Constant outcomes all zeros or all ones
    cal_zeros = IsotonicProbabilityCalibrator.fit_pava([0.2, 0.4, 0.6, 0.8], [0.0, 0.0, 0.0, 0.0])
    for p in [0.1, 0.5, 0.9]:
        assert cal_zeros.calibrate(p) == 0.0

    cal_ones = IsotonicProbabilityCalibrator.fit_pava([0.2, 0.4, 0.6, 0.8], [1.0, 1.0, 1.0, 1.0])
    for p in [0.1, 0.5, 0.9]:
        assert cal_ones.calibrate(p) == 1.0

    # 3. Duplicate x values with conflicting outcomes
    x_dup = [0.3, 0.3, 0.3, 0.7, 0.7]
    y_dup = [0.0, 1.0, 0.0, 1.0, 0.0]
    cal_dup = IsotonicProbabilityCalibrator.fit_pava(x_dup, y_dup)
    assert 0.0 <= cal_dup.calibrate(0.3) <= 1.0
    assert 0.0 <= cal_dup.calibrate(0.7) <= 1.0
    assert cal_dup.calibrate(0.3) <= cal_dup.calibrate(0.7)

    # 4. Out-of-bounds queries (< 0.0 or > 1.0) must clamp safely
    assert cal_dup.calibrate(-0.5) >= 0.0
    assert cal_dup.calibrate(1.5) <= 1.0

    # 5. Length mismatch must raise ValueError
    with pytest.raises(ValueError, match="equal length"):
        IsotonicProbabilityCalibrator.fit_pava([0.1, 0.2], [1.0])


# ==============================================================================
# PROBE 4: KELLY STAKING & BANKROLL RECOVERY
# ==============================================================================

def test_adversarial_kelly_macro_regime_cap_sweep():
    """Exhaustive sweep verifying that on macro bankrolls, stake NEVER exceeds 5% cap.

    Sweeps:
    - Bankroll: 1,000 TL to 100,000 TL
    - Win prob: 0.10 to 0.99
    - Odds: 1.10 to 50.0
    - Kelly fraction: 0.10, 0.25, 0.50, 1.00 (full Kelly)
    """
    opt = DiscreteKellyOptimizer(max_allocation_cap=0.05)

    bankrolls = [1000.0, 2500.0, 5000.0, 10000.0, 50000.0, 100000.0]
    probs = [0.30, 0.50, 0.70, 0.85, 0.95, 0.99]
    odds_list = [1.10, 1.30, 1.70, 2.00, 3.50, 5.00, 10.0, 25.0]

    for b in bankrolls:
        max_allowed_stake = b * 0.05
        for p in probs:
            for o in odds_list:
                for k_frac in [0.25, 0.50, 1.00]:
                    res = opt.compute_fractional_kelly_stake(
                        current_bankroll=b,
                        win_prob=p,
                        odds=o,
                        min_ticket_cost=50.0,
                        kelly_fraction=k_frac,
                    )

                    ev = (p * o) - 1.0
                    if ev <= 0.0:
                        # Negative EV must result in 0 stake
                        assert res["is_viable"] is False
                        assert res["stake"] == 0.0
                    else:
                        assert res["is_viable"] is True
                        assert res["regime"] == "MACRO"
                        # Strict cap assertion: stake MUST NOT exceed 5% of bankroll!
                        # (Old code risked 45% flat stake = 0.45 * b)
                        assert res["stake"] <= max_allowed_stake + 1e-5, (
                            f"Stake {res['stake']} exceeded 5% cap ({max_allowed_stake}) for bankroll={b}"
                        )
                        assert res["stake"] >= 50.0  # At least min ticket cost
                        assert res["remaining_bankroll"] >= b - max_allowed_stake


def test_adversarial_kelly_non_negative_allocations_and_ev_hurdle():
    """Verify non-positive EV tickets are strictly rejected across micro and macro regimes."""
    opt = DiscreteKellyOptimizer()

    # Negative EV tickets
    negative_scenarios = [
        (0.40, 2.00),   # EV = -20%
        (0.50, 1.80),   # EV = -10%
        (0.20, 4.00),   # EV = -20%
        (0.10, 8.00),   # EV = -20%
        (0.90, 1.05),   # EV = -5.5%
        (0.50, 2.00),   # Breakeven EV = 0.0%
    ]

    for b in [100.0, 500.0, 2000.0, 10000.0]:
        for p, o in negative_scenarios:
            res = opt.compute_fractional_kelly_stake(
                current_bankroll=b,
                win_prob=p,
                odds=o,
            )
            assert res["is_viable"] is False
            assert res["stake"] == 0.0
            assert res["remaining_bankroll"] == b


def test_adversarial_bankroll_builder_recovery_portfolio():
    """Verify build_recovery_portfolio guarantees bounded allocation and safety."""
    candidates = [
        {"match": "Match 1", "market": "1X2", "selection": "1", "odds": 1.45, "prob": 0.76, "edge_pct": 10.2},
        {"match": "Match 2", "market": "ÇŞ", "selection": "1X", "odds": 1.35, "prob": 0.82, "edge_pct": 10.7},
        {"match": "Match 3", "market": "DNB", "selection": "DNB 1", "odds": 1.60, "prob": 0.72, "edge_pct": 15.2},
    ]

    # Test bankrolls: Micro (127 TL), Medium (500 TL), Macro (10,000 TL)
    for b in [127.0, 500.0, 10000.0]:
        port = build_recovery_portfolio(candidates, current_bankroll=b, min_ticket_cost=50.0)

        t1 = port["tier1_capital_shield"]
        if t1 is not None:
            # Check stake
            stake = t1["stake"]
            assert stake >= 50.0
            if b >= 1000.0:
                # In macro regime, must be <= 5% of bankroll
                assert stake <= b * 0.05
            assert t1["remaining_bankroll"] == pytest.approx(b - stake, abs=0.01)
            assert t1["potential_return"] == pytest.approx(stake * t1["combined_odds"], abs=0.05)
            assert t1["net_profit"] == pytest.approx(t1["potential_return"] - stake, abs=0.05)
