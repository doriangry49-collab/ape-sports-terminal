"""Baseline Poisson goal expectancy model for football match 1X2 prediction."""

import math
from dataclasses import dataclass
from typing import Any


def bivariate_poisson_pmf(
    x: int,
    y: int,
    lambda_1: float,
    lambda_2: float,
    lambda_3: float = 0.0,
) -> float:
    """Exact Bivariate Poisson joint probability mass function P(X=x, Y=y).

    Based on the trivariate reduction method (Karlis & Ntzoufras, 2003):
    X = X_1 + X_3, Y = X_2 + X_3 where:
    - X_1 ~ Poisson(lambda_1)
    - X_2 ~ Poisson(lambda_2)
    - X_3 ~ Poisson(lambda_3)
    are independent random variables.
    Marginal expectations: E[X] = lambda_1 + lambda_3, E[Y] = lambda_2 + lambda_3.
    Covariance: Cov(X, Y) = lambda_3 >= 0.

    Formula:
    P(X=x, Y=y) = exp(-(l1 + l2 + l3)) * sum_{k=0}^{min(x, y)} [ (l1^(x-k) * l2^(y-k) * l3^k) / ((x-k)! * (y-k)! * k!) ]
    """
    if x < 0 or y < 0:
        return 0.0

    l1 = max(0.0, float(lambda_1))
    l2 = max(0.0, float(lambda_2))
    l3 = max(0.0, float(lambda_3))

    if l3 == 0.0:
        # Fast independent Poisson path
        p_x = (math.exp(-l1) * (l1**x)) / math.factorial(x) if l1 > 0 else (1.0 if x == 0 else 0.0)
        p_y = (math.exp(-l2) * (l2**y)) / math.factorial(y) if l2 > 0 else (1.0 if y == 0 else 0.0)
        return p_x * p_y

    base_exp = math.exp(-(l1 + l2 + l3))
    min_xy = min(x, y)
    term_sum = 0.0

    for k in range(min_xy + 1):
        if x - k == 0:
            term1 = 1.0
        elif l1 > 0:
            term1 = (l1 ** (x - k)) / math.factorial(x - k)
        else:
            term1 = 0.0

        if y - k == 0:
            term2 = 1.0
        elif l2 > 0:
            term2 = (l2 ** (y - k)) / math.factorial(y - k)
        else:
            term2 = 0.0

        if k == 0:
            term3 = 1.0
        else:
            term3 = (l3 ** k) / math.factorial(k)

        term_sum += term1 * term2 * term3

    return base_exp * term_sum


def dixon_coles_tau(
    x: int,
    y: int,
    lambda_1: float,
    lambda_2: float,
    rho: float = -0.06,
) -> float:
    """Compute Dixon & Coles (1997) low-score adjustment factor tau(x, y).

    Adjusts joint probabilities for low-scoring football scorelines: (0,0), (1,0), (0,1), (1,1).
    Scores with x > 1 or y > 1 are unaffected (tau = 1.0).

    Strictly enforces dynamic and calibrated bounds for rho in [-0.15, 0.05],
    and guarantees tau(x, y) >= 0.0:
    - tau(0, 0) = 1.0 - lambda_1 * lambda_2 * rho
    - tau(0, 1) = 1.0 + lambda_1 * rho
    - tau(1, 0) = 1.0 + lambda_2 * rho
    - tau(1, 1) = 1.0 - rho
    """
    if x > 1 or y > 1 or x < 0 or y < 0:
        return 1.0

    l1 = max(0.001, float(lambda_1))
    l2 = max(0.001, float(lambda_2))

    # Dynamic non-negativity bounds for rho:
    min_rho = max(-0.15, -0.999 / l1, -0.999 / l2)
    max_rho = min(0.05, 0.999, 0.999 / (l1 * l2))
    clamped_rho = max(min_rho, min(max_rho, float(rho)))

    if x == 0 and y == 0:
        tau = 1.0 - (l1 * l2 * clamped_rho)
    elif x == 0 and y == 1:
        tau = 1.0 + (l1 * clamped_rho)
    elif x == 1 and y == 0:
        tau = 1.0 + (l2 * clamped_rho)
    elif x == 1 and y == 1:
        tau = 1.0 - clamped_rho
    else:
        tau = 1.0

    return max(0.0, tau)


def compute_bivariate_score_grid(
    lambda_h: float,
    lambda_a: float,
    lambda_3: float = 0.05,
    rho: float = -0.06,
    max_goals: int = 8,
) -> dict[tuple[int, int], float]:
    """Generate normalized Bivariate Poisson score grid with Dixon-Coles adjustment.

    Args:
        lambda_h: Marginal expected goals for home team (lambda_h > 0).
        lambda_a: Marginal expected goals for away team (lambda_a > 0).
        lambda_3: Covariance parameter in [0.0, 0.35].
        rho: Dixon-Coles low-score correlation in [-0.15, 0.05].
        max_goals: Maximum goals evaluated per side (0 to max_goals).

    Returns:
        Dict mapping (x, y) score tuples to strictly normalized probabilities summing to 1.0 +/- 1e-6.
    """
    lam_h = max(0.05, float(lambda_h))
    lam_a = max(0.05, float(lambda_a))

    # Clamping lambda_3 into [0.0, min(0.35, lam_h - 0.01, lam_a - 0.01)]
    max_cov = max(0.0, min(0.35, lam_h - 0.01, lam_a - 0.01))
    l3_eff = max(0.0, min(max_cov, float(lambda_3)))

    # Marginal decomposition: lambda_1 = lam_h - lambda_3, lambda_2 = lam_a - lambda_3
    l1 = max(0.001, lam_h - l3_eff)
    l2 = max(0.001, lam_a - l3_eff)

    raw_grid: dict[tuple[int, int], float] = {}
    total_p = 0.0

    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            p_biv = bivariate_poisson_pmf(x, y, l1, l2, l3_eff)
            tau = dixon_coles_tau(x, y, lam_h, lam_a, rho)
            p_val = max(0.0, p_biv * tau)
            raw_grid[(x, y)] = p_val
            total_p += p_val

    # Strict normalization
    normalized_grid: dict[tuple[int, int], float] = {}
    if total_p > 0.0:
        for score, p_val in raw_grid.items():
            normalized_grid[score] = p_val / total_p
    else:
        n_cells = (max_goals + 1) ** 2
        for score in raw_grid:
            normalized_grid[score] = 1.0 / n_cells

    return normalized_grid



@dataclass(frozen=True)
class MatchPredictionOutput:
    """Output container for match prediction probabilities and fair odds."""

    home_team: str
    away_team: str
    expected_home_goals: float
    expected_away_goals: float
    home_probability: float
    draw_probability: float
    away_probability: float
    fair_home_odds: float
    fair_draw_odds: float
    fair_away_odds: float
    model_name: str
    model_version: str
    feature_set_version: str
    metadata: dict[str, Any]


class PoissonGoalModel:
    """Bivariate Poisson goal expectancy model with empirical Bayesian shrinkage.

    Estimates team-specific attack and defense ratings from historical match records,
    computes expected home/away goals (lambda), and calculates 1X2 match probabilities
    and fair odds across an 8x8 score grid.
    """

    MODEL_NAME = "poisson_bivariate_baseline"
    MODEL_VERSION = "0.1.0"
    FEATURE_SET_VERSION = "fs_v0.1_goals"

    def __init__(
        self,
        shrinkage_weight: float = 3.0,
        max_goals: int = 8,
        lambda_3: float = 0.05,
        rho: float = -0.06,
    ):
        """
        Args:
            shrinkage_weight: Pseudo-matches used for empirical Bayesian shrinkage towards league mean.
            max_goals: Maximum goals per team evaluated in probability grid (0 to max_goals).
            lambda_3: Bivariate Poisson covariance parameter in [0.0, 0.35].
            rho: Dixon-Coles low-score adjustment correlation parameter in [-0.15, 0.05].
        """
        self.shrinkage_weight = shrinkage_weight
        self.max_goals = max_goals
        self.lambda_3 = lambda_3
        self.rho = rho
        self.is_fitted = False

        # League parameters
        self.league_avg_home_goals = 1.45
        self.league_avg_away_goals = 1.15
        self.total_matches = 0

        # Team statistics
        self.team_stats: dict[str, dict[str, float]] = {}

    def fit(self, matches: list[dict[str, Any]]) -> "PoissonGoalModel":
        """Fit attack and defense ratings from historical match records.

        Each match dict must contain:
        - 'home_team': canonical or normalized team string
        - 'away_team': canonical or normalized team string
        - 'home_score': int (goals scored by home team)
        - 'away_score': int (goals scored by away team)
        """
        if not matches:
            raise ValueError("Cannot fit PoissonGoalModel on empty match list.")

        total_home_goals = 0
        total_away_goals = 0
        n_matches = 0

        stats: dict[str, dict[str, float]] = {}

        def get_team_bucket(name: str) -> dict[str, float]:
            if name not in stats:
                stats[name] = {
                    "home_played": 0.0,
                    "away_played": 0.0,
                    "home_scored": 0.0,
                    "home_conceded": 0.0,
                    "away_scored": 0.0,
                    "away_conceded": 0.0,
                }
            return stats[name]

        for m in matches:
            h_team = str(m["home_team"])
            a_team = str(m["away_team"])
            h_score = float(m["home_score"])
            a_score = float(m["away_score"])

            total_home_goals += h_score
            total_away_goals += a_score
            n_matches += 1

            h_bucket = get_team_bucket(h_team)
            h_bucket["home_played"] += 1.0
            h_bucket["home_scored"] += h_score
            h_bucket["home_conceded"] += a_score

            a_bucket = get_team_bucket(a_team)
            a_bucket["away_played"] += 1.0
            a_bucket["away_scored"] += a_score
            a_bucket["away_conceded"] += h_score

        self.total_matches = n_matches
        self.league_avg_home_goals = max(0.5, total_home_goals / max(1, n_matches))
        self.league_avg_away_goals = max(0.5, total_away_goals / max(1, n_matches))

        # Calculate shrunk attack and defense ratings
        k = self.shrinkage_weight
        self.team_stats = {}

        for team, s in stats.items():
            h_played = s["home_played"]
            a_played = s["away_played"]

            # Shrunk home attack = (home_scored + k * mu_H) / (h_played * mu_H + k * mu_H)
            expected_base_h = h_played * self.league_avg_home_goals
            h_attack = (s["home_scored"] + k * self.league_avg_home_goals) / (expected_base_h + k * self.league_avg_home_goals)

            # Shrunk away attack = (away_scored + k * mu_A) / (a_played * mu_A + k * mu_A)
            expected_base_a = a_played * self.league_avg_away_goals
            a_attack = (s["away_scored"] + k * self.league_avg_away_goals) / (expected_base_a + k * self.league_avg_away_goals)

            # Shrunk home defense = (home_conceded + k * mu_A) / (h_played * mu_A + k * mu_A)
            expected_concede_h = h_played * self.league_avg_away_goals
            h_defense = (s["home_conceded"] + k * self.league_avg_away_goals) / (expected_concede_h + k * self.league_avg_away_goals)

            # Shrunk away defense = (away_conceded + k * mu_H) / (a_played * mu_H + k * mu_H)
            expected_concede_a = a_played * self.league_avg_home_goals
            a_defense = (s["away_conceded"] + k * self.league_avg_home_goals) / (expected_concede_a + k * self.league_avg_home_goals)

            self.team_stats[team] = {
                "home_attack": round(h_attack, 4),
                "away_attack": round(a_attack, 4),
                "home_defense": round(h_defense, 4),
                "away_defense": round(a_defense, 4),
                "matches_played": h_played + a_played,
            }

        self.is_fitted = True
        return self

    def predict_match(
        self,
        home_team: str,
        away_team: str,
        calibrate: bool = True,
    ) -> MatchPredictionOutput:
        """Predict 1X2 probabilities and fair odds for a matchup."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict_match can be called.")

        h_stats = self.team_stats.get(
            home_team,
            {"home_attack": 1.0, "away_attack": 1.0, "home_defense": 1.0, "away_defense": 1.0, "matches_played": 0},
        )
        a_stats = self.team_stats.get(
            away_team,
            {"home_attack": 1.0, "away_attack": 1.0, "home_defense": 1.0, "away_defense": 1.0, "matches_played": 0},
        )

        # Expected goals lambda_H and lambda_A
        # Home goals expectancy = League home avg * Home attack * Away defense
        lambda_h = max(0.1, self.league_avg_home_goals * h_stats["home_attack"] * a_stats["away_defense"])
        # Away goals expectancy = League away avg * Away attack * Home defense
        lambda_a = max(0.1, self.league_avg_away_goals * a_stats["away_attack"] * h_stats["home_defense"])

        # Compute normalized Bivariate Poisson + Dixon-Coles probability grid
        grid_matrix = compute_bivariate_score_grid(
            lambda_h=lambda_h,
            lambda_a=lambda_a,
            lambda_3=self.lambda_3,
            rho=self.rho,
            max_goals=self.max_goals,
        )

        prob_home = sum(p for (h, a), p in grid_matrix.items() if h > a)
        prob_draw = sum(p for (h, a), p in grid_matrix.items() if h == a)
        prob_away = sum(p for (h, a), p in grid_matrix.items() if h < a)

        # String-keyed grid dict for backward compatibility
        grid = {f"{h}-{a}": round(p, 6) for (h, a), p in grid_matrix.items()}

        raw_home, raw_draw, raw_away = prob_home, prob_draw, prob_away
        if calibrate:
            try:
                from sports_engine.models.calibration import recalibrate_1x2
                prob_home, prob_draw, prob_away = recalibrate_1x2(prob_home, prob_draw, prob_away, method="logistic")
            except ImportError:
                pass

        # Fair odds calculation (1.0 / p)
        fair_h_odds = round(1.0 / max(prob_home, 0.0001), 2)
        fair_d_odds = round(1.0 / max(prob_draw, 0.0001), 2)
        fair_a_odds = round(1.0 / max(prob_away, 0.0001), 2)

        return MatchPredictionOutput(
            home_team=home_team,
            away_team=away_team,
            expected_home_goals=round(lambda_h, 3),
            expected_away_goals=round(lambda_a, 3),
            home_probability=round(prob_home, 4),
            draw_probability=round(prob_draw, 4),
            away_probability=round(prob_away, 4),
            fair_home_odds=fair_h_odds,
            fair_draw_odds=fair_d_odds,
            fair_away_odds=fair_a_odds,
            model_name=self.MODEL_NAME,
            model_version=self.MODEL_VERSION,
            feature_set_version=self.FEATURE_SET_VERSION,
            metadata={
                "league_avg_home_goals": round(self.league_avg_home_goals, 3),
                "league_avg_away_goals": round(self.league_avg_away_goals, 3),
                "training_sample_matches": self.total_matches,
                "home_team_attack": h_stats["home_attack"],
                "home_team_defense": h_stats["home_defense"],
                "away_team_attack": a_stats["away_attack"],
                "away_team_defense": a_stats["away_defense"],
                "lambda_3": self.lambda_3,
                "rho": self.rho,
                "grid_probability_sum": round(raw_home + raw_draw + raw_away, 6),
                "calibrated": calibrate,
                "raw_probabilities": {"home": round(raw_home, 4), "draw": round(raw_draw, 4), "away": round(raw_away, 4)},
                "most_likely_score": max(grid.items(), key=lambda kv: kv[1])[0],
            },
        )
