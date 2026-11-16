"""Unit tests for Draw No Bet (DNB) & Double Chance Precision Engine."""

from dnb_double_chance_engine import (
    calculate_dnb_probabilities,
    calculate_double_chance_probabilities,
    evaluate_safety_markets,
)


def test_calculate_dnb_probabilities():
    p_h, p_x, p_a = 0.50, 0.30, 0.20
    p_dnb_h, fair_dnb_h, p_dnb_a, fair_dnb_a = calculate_dnb_probabilities(p_h, p_x, p_a)

    # DNB prob = 0.50 / (0.50 + 0.20) = 5/7 ≈ 0.7143
    assert round(p_dnb_h, 2) == 0.71
    assert round(p_dnb_a, 2) == 0.29
    assert fair_dnb_h == 1.40
    assert fair_dnb_a == 3.50


def test_calculate_double_chance_probabilities():
    p_h, p_x, p_a = 0.50, 0.30, 0.20
    res = calculate_double_chance_probabilities(p_h, p_x, p_a)

    assert "1X" in res
    assert "X2" in res
    assert "12" in res
    # 1X prob = 0.50 + 0.30 = 0.80
    assert res["1X"][0] == 0.80
    assert res["1X"][1] == 1.25


def test_evaluate_safety_markets():
    cands = evaluate_safety_markets(
        fixture_name="Arsenal vs Chelsea",
        league="Premier League",
        odds_1x2=(1.60, 3.80, 5.00),
    )
    assert len(cands) >= 1
    types = [c["market"] for c in cands]
    assert "Çifte Şans" in types or "Beraberlikte İade" in types
    for c in cands:
        assert c["prob"] >= 0.60

