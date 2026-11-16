"""Unit tests for Ensemble Pricing & Calibration Engine."""

import pytest

from ensemble_pricing_engine import EnsemblePricingEngine, blend_probabilities


def test_blend_probabilities_fallback_when_no_sharp():
    # Only model probabilities provided
    m_probs = [0.50, 0.30, 0.20]
    blended = blend_probabilities(m_probs, sharp_odds=None)
    assert abs(sum(blended) - 1.0) < 1e-4
    assert blended == pytest.approx(m_probs)


def test_blend_probabilities_with_sharp_odds():
    # Model thinks Home is 0.60, Draw 0.25, Away 0.15
    # Sharp odds suggest Home 2.0 (approx 0.48 fair), Draw 3.4 (approx 0.28 fair), Away 4.0 (approx 0.24 fair)
    m_probs = [0.60, 0.25, 0.15]
    sharp_odds = (2.00, 3.40, 4.00)
    blended = blend_probabilities(m_probs, sharp_odds=sharp_odds, sharp_weight=0.50, method="shin")

    assert abs(sum(blended) - 1.0) < 1e-4
    # Blended home probability should be between sharp (~0.48) and model (0.60)
    assert 0.48 <= blended[0] <= 0.60


def test_ensemble_price_1x2_and_signals():
    engine = EnsemblePricingEngine(default_sharp_weight=0.60)
    m_probs = (0.55, 0.25, 0.20)
    sharp_odds = (1.90, 3.50, 4.20)
    # Soft book offers huge price on home (e.g. 2.15 vs fair ~1.95)
    soft_odds = (2.15, 3.20, 3.30)

    res = engine.price_1x2(
        model_1x2_probs=m_probs,
        sharp_1x2_odds=sharp_odds,
        soft_1x2_odds=soft_odds,
        min_edge_pct=3.0,
    )

    assert res["has_sharp_consensus"] is True
    assert "probs_1x2" in res
    assert "double_chance" in res
    assert "dnb" in res
    assert len(res["signals"]) > 0

    h_sig = next((s for s in res["signals"] if s["selection"] == "MS 1"), None)
    assert h_sig is not None
    assert h_sig["edge_pct"] > 0


def test_ensemble_price_ou25():
    engine = EnsemblePricingEngine(default_sharp_weight=0.50)
    m_ou_probs = (0.65, 0.35)  # (over, under)
    sharp_ou_odds = (1.65, 2.30)
    soft_ou_odds = (1.75, 2.10)

    res = engine.price_ou25(
        model_ou25_probs=m_ou_probs,
        sharp_ou25_odds=sharp_ou_odds,
        soft_ou25_odds=soft_ou_odds,
        min_edge_pct=3.0,
    )

    assert res["has_sharp_consensus"] is True
    assert abs((res["p_over"] + res["p_under"]) - 1.0) < 1e-4
    assert len(res["signals"]) > 0
    over_sig = next((s for s in res["signals"] if s["selection"] == "2.5 ÜST"), None)
    assert over_sig is not None
    assert over_sig["edge_pct"] > 0

