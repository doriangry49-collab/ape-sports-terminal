"""Canonical Synthetic Market Pricing Engine (Feature F6).

Computes clean, de-vigged synthetic probabilities and fair odds for:
- Double Chance (1X, X2, 12)
- Draw No Bet (DNB 1, DNB 2)

Eliminates margin compounding and double overround penalty.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sports_engine.domain.pricing_contract import NoVigMethod
from sports_engine.pricing.no_vig import compute_no_vig


def compute_synthetic_double_chance(
    odds_1x2: Sequence[float] | Mapping[str, float],
    method: NoVigMethod | str = NoVigMethod.SHIN,
) -> dict[str, dict[str, float]]:
    """Compute de-vigged fair Double Chance probabilities and odds from 1X2 market odds.

    Args:
        odds_1x2: 1X2 market odds as a 3-element sequence (home, draw, away)
                  or mapping {"HOME": h, "DRAW": d, "AWAY": a}.
        method: De-vigging method (Shin, Multiplicative, or Power).

    Returns:
        Dictionary mapping "1X", "X2", "12" to {"prob": float, "fair_odd": float}.
    """
    if isinstance(odds_1x2, Mapping):
        odds_dict = {
            "HOME": float(odds_1x2["HOME"]),
            "DRAW": float(odds_1x2["DRAW"]),
            "AWAY": float(odds_1x2["AWAY"]),
        }
    elif len(odds_1x2) == 3:
        odds_dict = {"HOME": float(odds_1x2[0]), "DRAW": float(odds_1x2[1]), "AWAY": float(odds_1x2[2])}
    else:
        raise ValueError(f"odds_1x2 must contain exactly 3 outcomes, got {len(odds_1x2)}")

    if isinstance(method, str):
        method = NoVigMethod(method.upper())

    result = compute_no_vig(odds_dict, market_name="1X2", method=method)
    p_h = result.no_vig_probabilities["HOME"]
    p_d = result.no_vig_probabilities["DRAW"]
    p_a = result.no_vig_probabilities["AWAY"]

    p_1x = min(0.9999, p_h + p_d)
    p_x2 = min(0.9999, p_d + p_a)
    p_12 = min(0.9999, p_h + p_a)

    return {
        "1X": {
            "prob": round(p_1x, 4),
            "fair_odd": round(1.0 / p_1x, 3) if p_1x > 0 else 999.0,
        },
        "X2": {
            "prob": round(p_x2, 4),
            "fair_odd": round(1.0 / p_x2, 3) if p_x2 > 0 else 999.0,
        },
        "12": {
            "prob": round(p_12, 4),
            "fair_odd": round(1.0 / p_12, 3) if p_12 > 0 else 999.0,
        },
    }


def compute_synthetic_dnb(
    odds_1x2: Sequence[float] | Mapping[str, float],
    method: NoVigMethod | str = NoVigMethod.SHIN,
) -> dict[str, dict[str, float]]:
    """Compute de-vigged fair Draw No Bet (DNB) probabilities and odds from 1X2 market odds.

    In DNB, stakes are refunded on a draw. The winning probability is p_team / (p_home + p_away).

    Args:
        odds_1x2: 1X2 market odds as sequence or mapping.
        method: De-vigging method.

    Returns:
        Dictionary mapping "DNB_1", "DNB_2" to {"prob": float, "fair_odd": float}.
    """
    if isinstance(odds_1x2, Mapping):
        odds_dict = {
            "HOME": float(odds_1x2["HOME"]),
            "DRAW": float(odds_1x2["DRAW"]),
            "AWAY": float(odds_1x2["AWAY"]),
        }
    elif len(odds_1x2) == 3:
        odds_dict = {"HOME": float(odds_1x2[0]), "DRAW": float(odds_1x2[1]), "AWAY": float(odds_1x2[2])}
    else:
        raise ValueError(f"odds_1x2 must contain exactly 3 outcomes, got {len(odds_1x2)}")

    if isinstance(method, str):
        method = NoVigMethod(method.upper())

    result = compute_no_vig(odds_dict, market_name="1X2", method=method)
    p_h = result.no_vig_probabilities["HOME"]
    p_a = result.no_vig_probabilities["AWAY"]
    denom = p_h + p_a

    if denom <= 0.0001:
        p_dnb1, p_dnb2 = 0.5, 0.5
    else:
        p_dnb1 = p_h / denom
        p_dnb2 = p_a / denom

    return {
        "DNB_1": {
            "prob": round(p_dnb1, 4),
            "fair_odd": round(1.0 / p_dnb1, 3) if p_dnb1 > 0 else 999.0,
        },
        "DNB_2": {
            "prob": round(p_dnb2, 4),
            "fair_odd": round(1.0 / p_dnb2, 3) if p_dnb2 > 0 else 999.0,
        },
    }
