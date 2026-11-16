"""Unit tests for Synthetic Pricing De-vigging & Edge Harmonization (Feature F6).

Verifies:
1. Synthetic Double Chance eliminates double-margin penalty: sum(1 / O_DC) == 2.0000.
2. Synthetic Draw No Bet (DNB) produces pure conditional no-vig probabilities: sum(P_DNB) == 1.0000.
3. Clean separation between Probability Edge (Delta p) and Expected Value ROI (EV_ROI).
4. SelectionEdge preserves raw_edge backward compatibility while exposing decoupled metrics.
"""

from __future__ import annotations

import pytest

from sports_engine.domain.pricing_contract import NoVigMethod
from sports_engine.pricing.edge import (
    calculate_selection_edge,
    compute_expected_value_roi,
    compute_probability_edge,
)
from sports_engine.pricing.synthetic import (
    compute_synthetic_dnb,
    compute_synthetic_double_chance,
)


def test_synthetic_double_chance_eliminates_double_overround():
    """Double chance fair prices derived from de-vigged 1X2 must have sum(P) == 2.0 exactly."""
    # Typical soft bookmaker odds with ~12% overround
    # 1 / 1.95 + 1 / 3.40 + 1 / 3.80 = 0.5128 + 0.2941 + 0.2632 = 1.0701
    odds = [1.95, 3.40, 3.80]

    dc_shin = compute_synthetic_double_chance(odds, method=NoVigMethod.SHIN)
    assert set(dc_shin.keys()) == {"1X", "X2", "12"}

    p_1x = dc_shin["1X"]["prob"]
    p_x2 = dc_shin["X2"]["prob"]
    p_12 = dc_shin["12"]["prob"]

    # Since P(1X) + P(X2) + P(12) = (P1 + PX) + (PX + P2) + (P1 + P2) = 2 * (P1 + PX + P2) = 2.0:
    sum_dc_probs = p_1x + p_x2 + p_12
    assert pytest.approx(sum_dc_probs, abs=0.01) == 2.0

    # Invert fair odds and check they match 1.0 / prob
    assert pytest.approx(dc_shin["1X"]["fair_odd"], abs=0.02) == (1.0 / p_1x)
    assert pytest.approx(dc_shin["X2"]["fair_odd"], abs=0.02) == (1.0 / p_x2)
    assert pytest.approx(dc_shin["12"]["fair_odd"], abs=0.02) == (1.0 / p_12)


def test_synthetic_double_chance_mapping_input():
    """compute_synthetic_double_chance accepts dictionary input {"HOME": ..., "DRAW": ..., "AWAY": ...}."""
    odds_dict = {"HOME": 2.10, "DRAW": 3.25, "AWAY": 3.50}
    dc = compute_synthetic_double_chance(odds_dict, method=NoVigMethod.MULTIPLICATIVE)
    assert "1X" in dc and "X2" in dc and "12" in dc
    assert dc["1X"]["fair_odd"] > 1.0


def test_synthetic_dnb_fair_probabilities_sum_to_one():
    """DNB conditional probabilities must sum strictly to 1.0000 without bookmaker margin."""
    odds = [2.20, 3.10, 3.40]
    dnb = compute_synthetic_dnb(odds, method=NoVigMethod.SHIN)

    p1 = dnb["DNB_1"]["prob"]
    p2 = dnb["DNB_2"]["prob"]
    assert pytest.approx(p1 + p2, abs=0.005) == 1.0

    # Fair odds are exact reciprocals of conditional probabilities
    assert pytest.approx(dnb["DNB_1"]["fair_odd"], abs=0.02) == (1.0 / p1)
    assert pytest.approx(dnb["DNB_2"]["fair_odd"], abs=0.02) == (1.0 / p2)


def test_compute_probability_edge():
    """Probability edge is strictly Delta p = p_model - p_market_no_vig in [-1.0, 1.0]."""
    # Positive edge: model estimates 60%, market fair consensus is 50% -> +0.10 (+10 pp)
    assert pytest.approx(compute_probability_edge(0.60, 0.50)) == 0.10

    # Negative edge: model estimates 30%, market fair consensus is 40% -> -0.10 (-10 pp)
    assert pytest.approx(compute_probability_edge(0.30, 0.40)) == -0.10

    # Bounds validation
    with pytest.raises(ValueError):
        compute_probability_edge(1.20, 0.50)
    with pytest.raises(ValueError):
        compute_probability_edge(0.50, -0.10)


def test_compute_expected_value_roi():
    """Expected Value ROI is strictly (p * odds) - 1.0 in (-1.0, +inf)."""
    # Breakeven bet: 50% win probability at odds 2.0 -> EV = 0.0 (0% ROI)
    assert pytest.approx(compute_expected_value_roi(0.50, 2.0)) == 0.0

    # +10% ROI bet: 55% win probability at odds 2.0 -> EV = +0.10 (+10% ROI)
    assert pytest.approx(compute_expected_value_roi(0.55, 2.0)) == 0.10

    # Negative EV: 40% win probability at odds 2.0 -> EV = -0.20 (-20% ROI)
    assert pytest.approx(compute_expected_value_roi(0.40, 2.0)) == -0.20

    # Guard against invalid odds
    with pytest.raises(ValueError):
        compute_expected_value_roi(0.50, 0.95)
    with pytest.raises(ValueError):
        compute_expected_value_roi(-0.10, 2.0)


def test_edge_metric_separation_contrast():
    """Demonstrate why separating Delta p and EV ROI is essential for favorite vs underdog."""
    # Favorite: p_mod = 0.85, odds = 1.20, p_mkt = 0.80
    delta_p_fav = compute_probability_edge(0.85, 0.80)
    ev_roi_fav = compute_expected_value_roi(0.85, 1.20)

    # Underdog: p_mod = 0.13, odds = 10.0, p_mkt = 0.08
    delta_p_und = compute_probability_edge(0.13, 0.08)
    ev_roi_und = compute_expected_value_roi(0.13, 10.0)

    # Both have IDENTICAL probability edge: +0.05 (+5 pp)
    assert pytest.approx(delta_p_fav, abs=1e-5) == 0.05
    assert pytest.approx(delta_p_und, abs=1e-5) == 0.05

    # But EV ROI is vastly different: +2% for favorite vs +30% for underdog (15x difference!)
    assert pytest.approx(ev_roi_fav, abs=1e-5) == 0.02
    assert pytest.approx(ev_roi_und, abs=1e-5) == 0.30


def test_calculate_selection_edge_binds_both_metrics():
    """SelectionEdge contains raw_edge, probability_edge, and expected_value_roi."""
    edge = calculate_selection_edge(
        fixture_id="fix_test_001",
        market="1X2",
        selection="HOME",
        entry_odds=2.20,
        model_probability=0.52,
        market_no_vig_probability=0.46,
    )

    assert edge.raw_edge == pytest.approx(0.06, abs=1e-5)
    assert edge.probability_edge == pytest.approx(0.06, abs=1e-5)
    assert edge.expected_value_roi == pytest.approx((0.52 * 2.20) - 1.0, abs=1e-5)
    assert edge.model_fair_odds == pytest.approx(1.0 / 0.52, abs=1e-3)
