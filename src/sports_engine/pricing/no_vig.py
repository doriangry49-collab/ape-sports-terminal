"""No-Vig calculation engine supporting Multiplicative, Shin, and Power methods.

Preserves:
- raw implied probability (1 / odds)
- overround (sum of raw implied probabilities)
- fair no-vig probability (strictly normalized, sum = 1.0)
- fair odds (1 / no_vig_probability)
"""

import math
from typing import Mapping

from sports_engine.domain.pricing_contract import MarketPricingResult, NoVigMethod


def calculate_overround(odds: Mapping[str, float]) -> float:
    """Calculate market overround (sum of raw implied probabilities)."""
    return sum(1.0 / price for price in odds.values())


def no_vig_multiplicative(odds: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float], float]:
    """Calculate No-Vig probabilities and fair odds using the Multiplicative (proportional) method.

    p_i = (1 / O_i) / sum(1 / O_j)
    fair_odds_i = 1 / p_i
    """
    raw_implied = {k: 1.0 / v for k, v in odds.items()}
    overround = sum(raw_implied.values())
    if overround <= 0.0:
        raise ValueError(f"Invalid non-positive overround: {overround}")

    no_vig_probs = {k: pi / overround for k, pi in raw_implied.items()}
    # Normalize strictly to sum to 1.0
    total_p = sum(no_vig_probs.values())
    no_vig_probs = {k: p / total_p for k, p in no_vig_probs.items()}

    fair_odds = {k: 1.0 / p if p > 0 else float("inf") for k, p in no_vig_probs.items()}
    return no_vig_probs, fair_odds, overround


def no_vig_shin(
    odds: Mapping[str, float], max_iter: int = 100, tolerance: float = 1e-9
) -> tuple[dict[str, float], dict[str, float], float]:
    """Calculate No-Vig probabilities and fair odds using Shin's (1992, 1993) model.

    Shin's model accounts for the favourite-longshot bias by postulating a proportion z of
    bettors possessing inside information. Solves for z in [0, 1) such that:
        sum_i [ (sqrt(z^2 + 4*(1-z)*pi_i^2 / beta) - z) / (2*(1-z)) ] = 1.0
    where pi_i = 1 / O_i and beta = sum(pi_i).
    """
    raw_implied = {k: 1.0 / v for k, v in odds.items()}
    overround = sum(raw_implied.values())

    if overround <= 1.0:
        # No vig or negative margin; fall back to multiplicative
        return no_vig_multiplicative(odds)

    keys = list(odds.keys())
    pi_values = [raw_implied[k] for k in keys]

    # Binary search for z in [0.0, 1.0)
    low, high = 0.0, 0.999
    z = 0.0

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        val = sum(
            (math.sqrt(mid**2 + 4.0 * (1.0 - mid) * (pi**2) / overround) - mid) / (2.0 * (1.0 - mid))
            for pi in pi_values
        )
        if abs(val - 1.0) < tolerance:
            z = mid
            break
        if val > 1.0:
            low = mid
        else:
            high = mid
    else:
        z = (low + high) / 2.0

    # Compute unnormalized Shin probabilities
    shin_unnorm = [
        (math.sqrt(z**2 + 4.0 * (1.0 - z) * (pi**2) / overround) - z) / (2.0 * (1.0 - z))
        for pi in pi_values
    ]
    total_p = sum(shin_unnorm)
    no_vig_probs = {keys[i]: shin_unnorm[i] / total_p for i in range(len(keys))}
    fair_odds = {k: 1.0 / p if p > 0 else float("inf") for k, p in no_vig_probs.items()}

    return no_vig_probs, fair_odds, overround


def no_vig_power(
    odds: Mapping[str, float], max_iter: int = 100, tolerance: float = 1e-9
) -> tuple[dict[str, float], dict[str, float], float]:
    """Calculate No-Vig probabilities using the Power method (solving sum(pi_i^k) = 1.0)."""
    raw_implied = {k: 1.0 / v for k, v in odds.items()}
    overround = sum(raw_implied.values())

    if overround <= 1.0:
        return no_vig_multiplicative(odds)

    keys = list(odds.keys())
    pi_values = [raw_implied[k] for k in keys]

    # Bisection search for k >= 1.0
    low, high = 1.0, 10.0
    k = 1.0

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        val = sum(pi**mid for pi in pi_values)
        if abs(val - 1.0) < tolerance:
            k = mid
            break
        if val > 1.0:
            low = mid
        else:
            high = mid
    else:
        k = (low + high) / 2.0

    power_unnorm = [pi**k for pi in pi_values]
    total_p = sum(power_unnorm)
    no_vig_probs = {keys[i]: power_unnorm[i] / total_p for i in range(len(keys))}
    fair_odds = {k: 1.0 / p if p > 0 else float("inf") for k, p in no_vig_probs.items()}

    return no_vig_probs, fair_odds, overround


def compute_no_vig(
    odds: Mapping[str, float],
    market_name: str = "1X2",
    method: NoVigMethod = NoVigMethod.SHIN,
) -> MarketPricingResult:
    """Compute market pricing result with raw implied, overround, no-vig probabilities, and fair odds."""
    if not odds:
        raise ValueError("Cannot compute no-vig on empty odds dictionary.")

    for k, v in odds.items():
        if v <= 1.0:
            raise ValueError(f"Selection '{k}' has invalid odds <= 1.0: {v}")

    raw_implied = {k: 1.0 / v for k, v in odds.items()}

    if method == NoVigMethod.SHIN:
        no_vig_probs, fair_odds, overround = no_vig_shin(odds)
    elif method == NoVigMethod.POWER:
        no_vig_probs, fair_odds, overround = no_vig_power(odds)
    elif method == NoVigMethod.MULTIPLICATIVE:
        no_vig_probs, fair_odds, overround = no_vig_multiplicative(odds)
    else:
        raise ValueError(f"Unsupported no-vig method: {method}")

    return MarketPricingResult(
        market_name=market_name,
        method=method,
        overround=overround,
        raw_implied_probabilities=raw_implied,
        no_vig_probabilities=no_vig_probs,
        fair_odds=fair_odds,
    )
