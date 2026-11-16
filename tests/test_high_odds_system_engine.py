"""Unit tests for High Odds System Engine."""

from __future__ import annotations

import math

from high_odds_system_engine import (
    find_high_value_longshots,
    generate_system_coupon,
    parse_high_odds_markets,
)


def test_parse_high_odds_markets():
    mock_ma = [
        {
            "MTID": 5,
            "OCA": [
                {"N": 1, "O": 3.20},
                {"N": 4, "O": 4.80},
                {"N": 7, "O": 25.0},
            ],
        },
        {
            "MTID": 43,
            "OCA": [
                {"N": 1, "O": 3.10},
                {"N": 4, "O": 14.50},
            ],
        },
        {
            "MTID": 225,
            "OCA": [
                {"N": 1, "O": 3.60},
                {"N": 2, "O": 1.18},
            ],
        },
    ]

    res = parse_high_odds_markets(mock_ma)
    assert res["htft"]["1/1"] == 3.20
    assert res["htft"]["X/1"] == 4.80
    assert res["htft"]["2/1"] == 25.0
    assert res["tg6"] == 14.50
    assert res["iy_kg_var"] == 3.60


def test_find_high_value_longshots():
    high_odds = {
        "htft": {"X/1": 4.60},
        "tg6": 8.50,
        "iy_kg_var": 3.80,
    }
    picks = find_high_value_longshots(
        fixture_name="Arsenal vs Everton",
        league="Premier League",
        high_odds=high_odds,
        odds_1x2=(1.50, 4.20, 6.50),
        odds_ou25=(1.45, 2.60),
    )
    assert len(picks) >= 2
    types = [p["type"] for p in picks]
    assert "HT_FT" in types
    assert "IY_KG" in types


def test_generate_system_coupon_sistem_2_3():
    picks = [
        {"match": "Match A", "selection": "X/1", "odds": 4.50},
        {"match": "Match B", "selection": "İY KG Var", "odds": 3.80},
        {"match": "Match C", "selection": "TG 6+", "odds": 5.00},
    ]

    # Sistem 2-3 with 3 picks: C(3,2) = 3 pairs + C(3,3) = 1 triplet = 4 total tickets
    sys_coupon = generate_system_coupon(picks, k_combos=(2, 3), unit_stake=10.0)
    assert sys_coupon["total_combinations"] == 4
    assert sys_coupon["total_cost"] == 40.0
    assert len(sys_coupon["combos"]["sistem_2"]) == 3
    assert len(sys_coupon["combos"]["sistem_3"]) == 1

    # Check triplet payout: 4.5 * 3.8 * 5.0 * 10 = 855.0
    triplet_payout = sys_coupon["combos"]["sistem_3"][0]["payout"]
    assert math.isclose(triplet_payout, 855.0, rel_tol=1e-3)


def test_dixon_coles_bivariate_matrix_and_htft():
    from high_odds_system_engine import (
        compute_bivariate_score_matrix,
        estimate_lambdas_from_odds,
        price_htft_transitions,
    )

    l_h, l_a = estimate_lambdas_from_odds((1.65, 3.60, 4.50), (1.75, 1.95))
    assert 1.0 <= l_h <= 3.0
    assert 0.5 <= l_a <= 2.0
    assert l_h > l_a  # Home is favored

    matrix = compute_bivariate_score_matrix(l_h, l_a)
    # Total probability in 0-7 matrix should sum close to 1.0
    assert math.isclose(sum(matrix.values()), 1.0, rel_tol=1e-2)

    htft_res = price_htft_transitions(l_h, l_a, {"X/1": 4.80, "1/1": 2.50, "2/1": 25.0})
    assert "X/1" in htft_res
    assert htft_res["X/1"]["prob"] > 0.05
    assert htft_res["X/1"]["fair_odds"] > 1.0
    assert htft_res["X/1"]["edge_pct"] is not None


