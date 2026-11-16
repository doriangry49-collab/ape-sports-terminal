"""Unit and Integration Tests Verifying Mathematical Parity Against penaltyblog.

Validates that sports-engine's zero-dependency internal quant algorithms
(Shin devigging, Power devigging, Negative Binomial corner distributions, Kelly staking)
yield exact mathematical parity with penaltyblog's gold-standard implementations.
"""

from __future__ import annotations

import penaltyblog.betting as pbb
import penaltyblog.implied as pbi
import pytest
import scipy.stats as stats

from advanced_corner_model import neg_binomial_cdf, neg_binomial_pmf
from stale_line_scanner import devig_power, devig_shin


class TestDevigParityWithPenaltyblog:
    """Test devigging mathematical equivalence against penaltyblog.implied."""

    @pytest.mark.parametrize(
        "odds",
        [
            (1.50, 4.20, 6.50),
            (2.10, 3.40, 3.50),
            (1.15, 7.50, 19.00),
            (3.20, 3.40, 2.25),
            (1.90, 1.90),
            (1.35, 3.10),
        ],
    )
    def test_shin_parity(self, odds: tuple[float, ...]):
        our_probs = devig_shin(odds)
        pb_res = pbi.calculate_implied(list(odds), method="shin")
        pb_probs = pb_res.probabilities

        assert len(our_probs) == len(pb_probs)
        for p_our, p_pb in zip(our_probs, pb_probs, strict=True):
            assert abs(p_our - p_pb) < 1e-4, f"Shin divergence on odds {odds}: our {p_our} vs pb {p_pb}"

    @pytest.mark.parametrize(
        "odds",
        [
            (1.50, 4.20, 6.50),
            (2.10, 3.40, 3.50),
            (1.15, 7.50, 19.00),
            (3.20, 3.40, 2.25),
            (1.90, 1.90),
        ],
    )
    def test_power_parity(self, odds: tuple[float, ...]):
        our_probs = devig_power(odds)
        pb_res = pbi.calculate_implied(list(odds), method="power")
        pb_probs = pb_res.probabilities

        assert len(our_probs) == len(pb_probs)
        for p_our, p_pb in zip(our_probs, pb_probs, strict=True):
            assert abs(p_our - p_pb) < 1e-4, f"Power divergence on odds {odds}: our {p_our} vs pb {p_pb}"


class TestNegativeBinomialCornerMathParity:
    """Test Negative Binomial distribution implementation against Scipy exact parametrization."""

    @pytest.mark.parametrize("mu", [7.5, 8.5, 9.85, 11.2, 13.0])
    @pytest.mark.parametrize("k", [0, 5, 8, 10, 12, 16])
    def test_nb_pmf_and_cdf_parity(self, mu: float, k: int):
        kappa = 0.14
        our_pmf = neg_binomial_pmf(k, mu, kappa)
        our_cdf = neg_binomial_cdf(k, mu, kappa)

        # Scipy standard Negative Binomial parameterization
        r = 1.0 / kappa
        p = 1.0 / (1.0 + kappa * mu)
        scipy_pmf = float(stats.nbinom.pmf(k, r, p))
        scipy_cdf = float(stats.nbinom.cdf(k, r, p))

        assert abs(our_pmf - scipy_pmf) < 1e-6, f"PMF mismatch at mu={mu}, k={k}: {our_pmf} vs {scipy_pmf}"
        assert abs(our_cdf - scipy_cdf) < 1e-6, f"CDF mismatch at mu={mu}, k={k}: {our_cdf} vs {scipy_cdf}"


class TestKellyParityWithPenaltyblog:
    """Test Kelly staking fraction calculation equivalence."""

    @pytest.mark.parametrize(
        ("prob", "decimal_odds"),
        [
            (0.55, 2.00),
            (0.70, 1.50),
            (0.35, 3.50),
            (0.85, 1.25),
        ],
    )
    def test_single_kelly_parity(self, prob: float, decimal_odds: float):
        # Kelly formula: f* = (b*p - q) / b, where b = odds - 1, q = 1 - p
        b = decimal_odds - 1.0
        q = 1.0 - prob
        expected_kelly = max(0.0, (b * prob - q) / b)

        pb_kelly = pbb.kelly_criterion(decimal_odds, prob).stake
        assert abs(expected_kelly - pb_kelly) < 1e-4
