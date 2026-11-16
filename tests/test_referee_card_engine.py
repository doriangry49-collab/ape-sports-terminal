"""Unit tests for Referee Discipline & Card Pricing Engine."""

from __future__ import annotations

import math

from referee_card_engine import get_referee_card_lambda, price_card_lines


def test_get_referee_card_lambda_fallback():
    assert get_referee_card_lambda(None) == 4.10
    assert get_referee_card_lambda("Unknown Fake Ref") == 4.10


def test_price_card_lines_basic():
    lmbda = 4.5
    res = price_card_lines(lmbda)

    assert "3.5" in res["lines"]
    assert "4.5" in res["lines"]
    assert "5.5" in res["lines"]

    # At lambda 4.5, Under 4.5 and Over 4.5 should be fairly balanced
    p_u45 = res["lines"]["4.5"]["p_under"]
    p_o45 = res["lines"]["4.5"]["p_over"]
    assert math.isclose(p_u45 + p_o45, 1.0)
    assert 0.45 < p_u45 < 0.60


def test_price_card_lines_with_odds():
    lmbda = 5.5  # Very strict referee
    offered = {
        "4.5": {"under": 2.20, "over": 1.65},
    }
    res = price_card_lines(lmbda, offered)
    assert len(res["edges"]) == 2

