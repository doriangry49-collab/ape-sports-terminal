"""Tests for Phase 2A Pricing Intelligence contract and engines.

Validates:
- 1X2 No-vig probability distributions sum to exactly 1.0 (Shin, Multiplicative, Power)
- Fair odds are exact inverse of no-vig probability (1 / p)
- Raw edge definition: model_probability - market_no_vig_probability
- Direction and sign of raw edge
- PREMATCH vs LIVE phase guards
- Exclusion of MODEL_DERIVED and high-odds markets in Phase 2A
- Unknown uncertainty does not create fake adjusted edge (strictly None)
- Overround and raw implied probabilities are preserved
"""

import math

import pytest

from sports_engine.domain.pricing_contract import (
    NoVigMethod,
)
from sports_engine.pricing import (
    calculate_selection_edge,
    compute_no_vig,
)


def test_1x2_no_vig_probability_sums_to_one():
    """Verify that Shin, Multiplicative, and Power methods produce probabilities summing to 1.0."""
    odds_1x2 = {"HOME": 2.10, "DRAW": 3.40, "AWAY": 3.60}

    for method in [NoVigMethod.SHIN, NoVigMethod.MULTIPLICATIVE, NoVigMethod.POWER]:
        result = compute_no_vig(odds_1x2, market_name="1X2", method=method)
        total_p = sum(result.no_vig_probabilities.values())
        assert math.isclose(total_p, 1.0, abs_tol=1e-6), f"{method} sum was {total_p}"
        assert all(0.0 < p < 1.0 for p in result.no_vig_probabilities.values())

    # Totals (2-way)
    odds_totals = {"OVER_2.5": 1.95, "UNDER_2.5": 1.85}
    for method in [NoVigMethod.SHIN, NoVigMethod.MULTIPLICATIVE]:
        res_tot = compute_no_vig(odds_totals, market_name="TOTALS", method=method)
        assert math.isclose(sum(res_tot.no_vig_probabilities.values()), 1.0, abs_tol=1e-6)

    # BTTS (2-way)
    odds_btts = {"YES": 1.75, "NO": 2.05}
    res_btts = compute_no_vig(odds_btts, market_name="BTTS", method=NoVigMethod.SHIN)
    assert math.isclose(sum(res_btts.no_vig_probabilities.values()), 1.0, abs_tol=1e-6)


def test_no_vig_fair_odds_are_inverse_probability():
    """Verify that fair odds are calculated as exactly 1.0 / no_vig_probability."""
    odds = {"HOME": 1.50, "DRAW": 4.20, "AWAY": 7.00}
    result = compute_no_vig(odds, market_name="1X2", method=NoVigMethod.SHIN)

    for selection, prob in result.no_vig_probabilities.items():
        expected_fair_odd = 1.0 / prob
        actual_fair_odd = result.fair_odds[selection]
        assert math.isclose(actual_fair_odd, expected_fair_odd, abs_tol=1e-6)
        # Bookmaker offered odds must be less than fair odds (bookmaker margin)
        assert odds[selection] < actual_fair_odd


def test_raw_edge_definition():
    """Verify raw edge definition: model_probability - market_no_vig_probability."""
    fixture_id = "20261009_galatasaray_vs_kasimpasa"
    market = "1X2"
    selection = "HOME"
    entry_odds = 1.25

    # Case 1: Positive edge (model is more optimistic than market fair price)
    model_p = 0.85
    market_p = 0.78
    edge_pos = calculate_selection_edge(
        fixture_id=fixture_id,
        market=market,
        selection=selection,
        entry_odds=entry_odds,
        model_probability=model_p,
        market_no_vig_probability=market_p,
        model_phase="PREMATCH",
        odds_phase="PREMATCH",
    )
    assert math.isclose(edge_pos.raw_edge, 0.07, abs_tol=1e-6)
    assert math.isclose(edge_pos.model_fair_odds, 1.0 / 0.85, abs_tol=1e-6)

    # Case 2: Negative edge (market prices higher than model)
    model_p_neg = 0.70
    market_p_neg = 0.78
    edge_neg = calculate_selection_edge(
        fixture_id=fixture_id,
        market=market,
        selection=selection,
        entry_odds=entry_odds,
        model_probability=model_p_neg,
        market_no_vig_probability=market_p_neg,
        model_phase="PREMATCH",
        odds_phase="PREMATCH",
    )
    assert math.isclose(edge_neg.raw_edge, -0.08, abs_tol=1e-6)


def test_premarket_live_guard():
    """Verify that comparing PREMATCH model with LIVE odds raises ValueError."""
    fixture_id = "20261009_galatasaray_vs_kasimpasa"

    # PREMATCH model vs LIVE odds must raise
    with pytest.raises(ValueError, match="Phase mismatch violation"):
        calculate_selection_edge(
            fixture_id=fixture_id,
            market="1X2",
            selection="HOME",
            entry_odds=1.50,
            model_probability=0.60,
            market_no_vig_probability=0.55,
            model_phase="PREMATCH",
            odds_phase="LIVE",
        )

    # LIVE model vs PREMATCH odds must raise
    with pytest.raises(ValueError, match="Phase mismatch violation"):
        calculate_selection_edge(
            fixture_id=fixture_id,
            market="1X2",
            selection="HOME",
            entry_odds=1.50,
            model_probability=0.60,
            market_no_vig_probability=0.55,
            model_phase="LIVE",
            odds_phase="PREMATCH",
        )

    # PREMATCH vs PREMATCH is valid
    res = calculate_selection_edge(
        fixture_id=fixture_id,
        market="1X2",
        selection="HOME",
        entry_odds=1.50,
        model_probability=0.60,
        market_no_vig_probability=0.55,
        model_phase="PREMATCH",
        odds_phase="PREMATCH",
    )
    assert res.match_phase == "PREMATCH"


def test_model_derived_market_excluded_from_phase_2a():
    """Verify that MODEL_DERIVED markets and high-odds markets (Correct Score, HT/FT) are rejected."""
    fixture_id = "20261009_galatasaray_vs_kasimpasa"

    # Reject high-odds / longshot market not permitted in Phase 2A
    with pytest.raises(ValueError, match="not permitted in Phase 2A"):
        calculate_selection_edge(
            fixture_id=fixture_id,
            market="CORRECT_SCORE",
            selection="2-1",
            entry_odds=9.50,
            model_probability=0.12,
            market_no_vig_probability=0.08,
        )

    with pytest.raises(ValueError, match="not permitted in Phase 2A"):
        calculate_selection_edge(
            fixture_id=fixture_id,
            market="HT_FT",
            selection="1/1",
            entry_odds=2.40,
            model_probability=0.45,
            market_no_vig_probability=0.40,
        )

    # Reject if source classification is MODEL_DERIVED
    with pytest.raises(ValueError, match="MODEL_DERIVED markets are strictly excluded"):
        calculate_selection_edge(
            fixture_id=fixture_id,
            market="1X2",
            selection="HOME",
            entry_odds=1.50,
            model_probability=0.60,
            market_no_vig_probability=0.55,
            source_classification="MODEL_DERIVED",
        )


def test_unknown_uncertainty_does_not_create_fake_adjusted_edge():
    """Verify that if uncertainty is unknown/not provided, adjusted_edge is None (UNKNOWN)."""
    fixture_id = "20261009_galatasaray_vs_kasimpasa"

    edge = calculate_selection_edge(
        fixture_id=fixture_id,
        market="1X2",
        selection="HOME",
        entry_odds=1.50,
        model_probability=0.65,
        market_no_vig_probability=0.60,
        uncertainty_penalty=None,
    )
    # Must be None, not some fabricated number
    assert edge.adjusted_edge is None
    assert math.isclose(edge.raw_edge, 0.05, abs_tol=1e-6)

    # When verified uncertainty penalty is provided, adjusted_edge is calculated
    edge_penalized = calculate_selection_edge(
        fixture_id=fixture_id,
        market="1X2",
        selection="HOME",
        entry_odds=1.50,
        model_probability=0.65,
        market_no_vig_probability=0.60,
        uncertainty_penalty=0.02,
    )
    assert edge_penalized.adjusted_edge is not None
    assert math.isclose(edge_penalized.adjusted_edge, 0.03, abs_tol=1e-6)


def test_market_overround_is_preserved():
    """Verify that raw implied probabilities and overround are explicitly recorded and preserved."""
    odds = {"HOME": 2.00, "DRAW": 3.40, "AWAY": 4.00}
    # Raw implied: 1/2.00 = 0.50, 1/3.40 = 0.294118, 1/4.00 = 0.25
    expected_overround = 0.50 + (1.0 / 3.40) + 0.25

    result = compute_no_vig(odds, market_name="1X2", method=NoVigMethod.SHIN)

    assert math.isclose(result.overround, expected_overround, abs_tol=1e-6)
    assert math.isclose(result.raw_implied_probabilities["HOME"], 0.50, abs_tol=1e-6)
    assert math.isclose(result.raw_implied_probabilities["AWAY"], 0.25, abs_tol=1e-6)
    assert result.overround > 1.0  # Vig exists
