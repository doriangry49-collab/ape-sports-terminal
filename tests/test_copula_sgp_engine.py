"""Unit tests for CopulaSGPEngine (Proposal 4)."""

from __future__ import annotations

import pytest

from copula_sgp_engine import (
    CopulaSGPEngine,
    SGPLeg,
)


def test_copula_independence_at_zero_correlation():
    """Verify Gaussian Copula reduces to independent product when rho = 0."""
    engine = CopulaSGPEngine()
    p1 = 0.60
    p2 = 0.50
    joint_prob = engine.compute_gaussian_copula_joint_prob(p1, p2, rho=0.0)
    assert pytest.approx(joint_prob, abs=1e-3) == (p1 * p2)


def test_copula_positive_correlation_lift():
    """Verify positive correlation increases joint probability above independence."""
    engine = CopulaSGPEngine()
    p1 = 0.55
    p2 = 0.60
    joint_independent = p1 * p2  # 0.330
    joint_correlated = engine.compute_gaussian_copula_joint_prob(p1, p2, rho=0.35)
    assert joint_correlated > joint_independent
    assert pytest.approx(joint_correlated, abs=0.08) == 0.385


def test_gumbel_copula_tail_dependence():
    """Verify Gumbel Copula handles upper tail dependence for explosive scoring combos."""
    engine = CopulaSGPEngine()
    p1 = 0.52
    p2 = 0.55
    joint_gumbel = engine.compute_gumbel_copula_joint_prob(p1, p2, rho=0.60)
    assert joint_gumbel > (p1 * p2)
    assert 0.30 <= joint_gumbel <= 0.50


def test_evaluate_sgp_recommendation_and_spec0015():
    """Verify SGP pricing, edge calculation, and constitutional SPEC-0015 stake."""
    engine = CopulaSGPEngine()
    leg_a = SGPLeg(
        market="1X2",
        selection="MS 1",
        marginal_prob=0.62,
        offered_odd=1.55,
    )
    leg_b = SGPLeg(
        market="KORNER",
        selection="9.5 ÜST",
        marginal_prob=0.58,
        offered_odd=1.65,
    )

    rec = engine.evaluate_sgp(
        fixture_id="SGP_TEST_01",
        home_team="Real Madrid",
        away_team="Valencia",
        leg_a=leg_a,
        leg_b=leg_b,
        offered_sgp_odds=2.45,
    )

    assert rec.fixture_id == "SGP_TEST_01"
    assert rec.home_team == "Real Madrid"
    assert rec.joint_prob > rec.independent_prob
    assert rec.correlation_lift_pct > 0.0
    assert rec.stake >= 50.0  # SPEC-0015 compliance
    assert rec.fair_sgp_odds < (1.0 / rec.independent_prob)


def test_scan_bulletin_for_sgp():
    """Test full bulletin scan with realistic Nesine fixture data."""
    engine = CopulaSGPEngine()
    bulletin = [
        {
            "nesine_code": "401991",
            "home": "Arsenal",
            "away": "Chelsea",
            "nesine_1x2": (1.60, 3.80, 5.20),
            "nesine_corners": {
                "8.5": {"under": 2.10, "over": 1.62},
                "9.5": {"under": 1.75, "over": 1.95},
            },
            "nesine_ou25": (1.65, 2.10),
        }
    ]

    recs = engine.scan_bulletin_for_sgp(bulletin, min_edge_pct=2.0)
    assert len(recs) >= 1
    rec = recs[0]
    assert rec.home_team == "Arsenal"
    assert rec.stake >= 50.0
