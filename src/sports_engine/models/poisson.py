"""Baseline Poisson goal expectancy model for football match 1X2 prediction."""

import math
from dataclasses import dataclass
from typing import Any


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

    def __init__(self, shrinkage_weight: float = 3.0, max_goals: int = 8):
        """
        Args:
            shrinkage_weight: Pseudo-matches used for empirical Bayesian shrinkage towards league mean.
            max_goals: Maximum goals per team evaluated in probability grid (0 to max_goals).
        """
        self.shrinkage_weight = shrinkage_weight
        self.max_goals = max_goals
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

    def predict_match(self, home_team: str, away_team: str) -> MatchPredictionOutput:
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

        # Compute probability grid
        prob_home = 0.0
        prob_draw = 0.0
        prob_away = 0.0

        grid: dict[str, float] = {}

        for h_goals in range(self.max_goals + 1):
            p_h = (math.pow(lambda_h, h_goals) * math.exp(-lambda_h)) / math.factorial(h_goals)
            for a_goals in range(self.max_goals + 1):
                p_a = (math.pow(lambda_a, a_goals) * math.exp(-lambda_a)) / math.factorial(a_goals)
                p_score = p_h * p_a
                grid[f"{h_goals}-{a_goals}"] = round(p_score, 6)

                if h_goals > a_goals:
                    prob_home += p_score
                elif h_goals == a_goals:
                    prob_draw += p_score
                else:
                    prob_away += p_score

        # Normalize total sum to 1.0
        total_p = prob_home + prob_draw + prob_away
        if total_p > 0:
            prob_home /= total_p
            prob_draw /= total_p
            prob_away /= total_p

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
                "most_likely_score": max(grid.items(), key=lambda kv: kv[1])[0],
            },
        )
