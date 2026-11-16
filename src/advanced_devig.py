"""
Advanced Odds Devigging & Mathematical Sports Modeling Module.
Part of APE Sports-Engine Phase 1 Adoption.
Uses penaltyblog to strip bookmaker margins (Shin, Power, Multiplicative)
and fit bivariate Poisson / Dixon-Coles models.
Adheres strictly to GEMINI.md:
- Fail-closed execution (ValueError / RuntimeError on degenerate odds)
- Probabilities sum to 1.0 (Kolmogorov Normalization)
- Monotonicity checks
"""

from typing import Any

import numpy as np
import penaltyblog.implied as pbi
import penaltyblog.models as pbm


class DevigError(Exception):
    """Raised fail-closed when odds cannot be devigged or are invalid."""

    pass


def devig_odds_shin(odds: list[float]) -> dict[str, Any]:
    """
    Strips bookmaker overround using Shin's method to extract true implied probabilities.

    Args:
        odds: List of decimal odds, e.g. [2.10, 3.40, 3.80] for 1X2 market.

    Returns:
        Dict containing:
            - 'probabilities': List of fair probabilities summing to 1.0
            - 'margin': Bookmaker overround/margin
            - 'z': Insider trading proportion parameter
            - 'method': 'shin'
    """
    if not odds or len(odds) < 2:
        raise DevigError("At least 2 odds required for devigging.")

    if any(o <= 1.0 for o in odds):
        raise DevigError("Invalid odds detected: All odds must be strictly > 1.0.")

    # Check overround: sum(1/odds) must exceed 1.0 for standard bookmaker margin
    inv_sum = sum(1.0 / o for o in odds)
    if inv_sum <= 1.0:
        raise DevigError(f"Market has no overround (sum of inverted odds = {inv_sum:.4f} <= 1.0).")

    try:
        res = pbi.calculate_implied(odds, method=pbi.ImpliedMethod.SHIN)
        probs = [float(p) for p in res.probabilities]

        # Invariant verification: sum of probabilities == 1.0
        prob_sum = sum(probs)
        if not np.isclose(prob_sum, 1.0, atol=1e-5):
            raise DevigError(
                f"Mathematical invariant broken: Probabilities sum to {prob_sum}, expected 1.0"
            )

        z_param = res.method_params.get("z", 0.0) if res.method_params else 0.0

        return {
            "probabilities": probs,
            "margin": float(res.margin),
            "z": float(z_param),
            "method": "shin",
        }
    except Exception as e:
        if isinstance(e, DevigError):
            raise
        raise DevigError(f"Shin solver execution failed: {str(e)}") from e


def devig_odds_multi(odds: list[float], method: str = "shin") -> dict[str, Any]:
    """
    General devigging function supporting multiple algorithms:
    'shin', 'power', 'multiplicative', 'additive', 'logarithmic'.
    """
    if not odds or len(odds) < 2:
        raise DevigError("At least 2 odds required for devigging.")

    if any(o <= 1.0 for o in odds):
        raise DevigError("Invalid odds detected: All odds must be strictly > 1.0.")

    method_map = {
        "shin": pbi.ImpliedMethod.SHIN,
        "power": pbi.ImpliedMethod.POWER,
        "multiplicative": pbi.ImpliedMethod.MULTIPLICATIVE,
        "additive": pbi.ImpliedMethod.ADDITIVE,
        "logarithmic": pbi.ImpliedMethod.LOGARITHMIC,
    }

    normalized_method = method.lower()
    if normalized_method not in method_map:
        raise DevigError(
            f"Unsupported devigging method '{method}'. Supported: {list(method_map.keys())}"
        )

    target_method = method_map[normalized_method]

    try:
        res = pbi.calculate_implied(odds, method=target_method)
        probs = [float(p) for p in res.probabilities]

        prob_sum = sum(probs)
        if not np.isclose(prob_sum, 1.0, atol=1e-5):
            raise DevigError(
                f"Mathematical invariant broken: Probabilities sum to {prob_sum}, expected 1.0"
            )

        return {
            "probabilities": probs,
            "margin": float(res.margin),
            "method": normalized_method,
            "method_params": res.method_params or {},
        }
    except Exception as e:
        if isinstance(e, DevigError):
            raise
        raise DevigError(f"{method.capitalize()} solver execution failed: {str(e)}") from e


def fit_dixon_coles_model(
    goals_home: list[int],
    goals_away: list[int],
    teams_home: list[str],
    teams_away: list[str],
    target_home: str,
    target_away: str,
    max_goals: int = 10,
) -> dict[str, Any]:
    """
    Fits Dixon-Coles goal model on historical match scores and predicts 1X2 probabilities.
    """
    if (
        len(goals_home) != len(goals_away)
        or len(goals_home) != len(teams_home)
        or len(goals_home) != len(teams_away)
    ):
        raise DevigError("Input arrays must have equal length.")

    if len(goals_home) < 10:
        raise DevigError(
            "Insufficient match history: Dixon-Coles requires at least 10 matches to calibrate."
        )

    try:
        model = pbm.DixonColesGoalModel(
            goals_home=goals_home,
            goals_away=goals_away,
            teams_home=teams_home,
            teams_away=teams_away,
        )
        model.fit()

        probs = model.predict(target_home, target_away, max_goals=max_goals)

        home_win = float(probs.home_win)
        draw = float(probs.draw)
        away_win = float(probs.away_win)

        total_p = home_win + draw + away_win
        if not np.isclose(total_p, 1.0, atol=1e-4):
            raise DevigError(f"Dixon-Coles probability normalization breach: sum = {total_p}")

        return {
            "home_win": home_win,
            "draw": draw,
            "away_win": away_win,
            "home_exp_goals": float(probs.home_goal_expectation),
            "away_exp_goals": float(probs.away_goal_expectation),
            "btts_yes": float(probs.btts_yes),
            "double_chance_1x": float(probs.double_chance_1x),
            "draw_no_bet_home": float(probs.draw_no_bet_home),
            "model": "dixon_coles",
        }
    except Exception as e:
        if isinstance(e, DevigError):
            raise
        raise DevigError(f"Dixon-Coles fitting/prediction failed: {str(e)}") from e
