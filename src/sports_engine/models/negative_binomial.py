"""Negative Binomial distribution engine for overdispersed goal and corner modeling.

Handles count variables where empirical variance exceeds the mean (Var > mu),
such as football corners (Var/mu ~ 1.3 - 1.8) and high-variance domestic football leagues.
"""

from __future__ import annotations

import math
from typing import Any

from sports_engine.models.poisson import MatchPredictionOutput, dixon_coles_tau

DEFAULT_CORNER_KAPPA = 0.14
DEFAULT_GOAL_KAPPA = 0.08


def neg_binomial_pmf(k: int, mu: float, kappa: float = DEFAULT_GOAL_KAPPA) -> float:
    """Exact Negative Binomial Probability Mass Function P(Y = k).

    Parameterized by mean mu and overdispersion kappa >= 0:
    Var(Y) = mu + kappa * mu^2.
    Shape parameter r = 1 / kappa.
    Success probability p = r / (r + mu) = 1 / (1 + kappa * mu).

    Uses log-gamma for numerical stability across large factorial values.
    Falls back to Poisson when kappa <= 1e-6.
    """
    if k < 0:
        return 0.0
    if mu <= 0.0:
        return 1.0 if k == 0 else 0.0
    if kappa <= 1e-6:
        return (math.exp(-mu) * (mu**k)) / math.factorial(k)

    r = 1.0 / kappa
    p = r / (r + mu)

    # ln P(k) = ln Gamma(k + r) - ln Gamma(r) - ln Gamma(k + 1) + r ln(p) + k ln(1 - p)
    log_comb = math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
    log_prob = log_comb + (r * math.log(p)) + (k * math.log(1.0 - p))
    return math.exp(log_prob)


def neg_binomial_cdf(k: int, mu: float, kappa: float = DEFAULT_GOAL_KAPPA) -> float:
    """Exact Cumulative Distribution Function P(Y <= k)."""
    if k < 0:
        return 0.0
    return sum(neg_binomial_pmf(i, mu, kappa) for i in range(k + 1))


def neg_binomial_over_prob(line: float, mu: float, kappa: float = DEFAULT_GOAL_KAPPA) -> float:
    """Compute Over probability P(Y > line). For example, line=2.5 computes P(Y >= 3)."""
    threshold = math.floor(line)
    return max(0.0, 1.0 - neg_binomial_cdf(threshold, mu, kappa))


def neg_binomial_under_prob(line: float, mu: float, kappa: float = DEFAULT_GOAL_KAPPA) -> float:
    """Compute Under probability P(Y < line). For example, line=2.5 computes P(Y <= 2)."""
    threshold = math.floor(line)
    return max(0.0, min(1.0, neg_binomial_cdf(threshold, mu, kappa)))


def neg_binomial_corner_pmf(k: int, mu: float, kappa: float = DEFAULT_CORNER_KAPPA) -> float:
    """Corner-specific Negative Binomial PMF using corner overdispersion kappa=0.14."""
    return neg_binomial_pmf(k=k, mu=mu, kappa=kappa)


def neg_binomial_corner_cdf(k: int, mu: float, kappa: float = DEFAULT_CORNER_KAPPA) -> float:
    """Corner-specific Negative Binomial CDF using corner overdispersion kappa=0.14."""
    return neg_binomial_cdf(k=k, mu=mu, kappa=kappa)


def neg_binomial_corner_over_prob(line: float, mu: float, kappa: float = DEFAULT_CORNER_KAPPA) -> float:
    """Exact P(Corners > line) using Negative Binomial with kappa=0.14."""
    threshold = math.floor(line)
    return max(0.0, 1.0 - neg_binomial_cdf(threshold, mu, kappa))


def neg_binomial_corner_under_prob(line: float, mu: float, kappa: float = DEFAULT_CORNER_KAPPA) -> float:
    """Exact P(Corners < line) using Negative Binomial with kappa=0.14."""
    threshold = math.floor(line)
    return max(0.0, min(1.0, neg_binomial_cdf(threshold, mu, kappa)))


def estimate_dispersion_kappa(counts: list[float | int]) -> float:
    """Estimate empirical overdispersion parameter kappa from observed historical sample.

    Formula: kappa = max(0.0, (s^2 - mu) / mu^2) where s^2 is sample variance and mu is sample mean.
    """
    if len(counts) < 2:
        return 0.0
    n = len(counts)
    mean_val = sum(counts) / float(n)
    if mean_val <= 0.0:
        return 0.0
    var_val = sum((c - mean_val) ** 2 for c in counts) / float(n - 1)
    if var_val <= mean_val:
        return 0.0
    return max(0.0, (var_val - mean_val) / (mean_val**2))


def compute_neg_binomial_score_grid(
    lambda_h: float,
    lambda_a: float,
    kappa_h: float = DEFAULT_GOAL_KAPPA,
    kappa_a: float = DEFAULT_GOAL_KAPPA,
    rho: float = -0.06,
    max_goals: int = 8,
) -> dict[tuple[int, int], float]:
    """Generate normalized score grid using Negative Binomial marginals and Dixon-Coles adjustment.

    Guarantees strict score probability grid normalization: sum_{x,y} P(x, y) = 1.0 +/- 1e-6.
    """
    lam_h = max(0.05, float(lambda_h))
    lam_a = max(0.05, float(lambda_a))
    k_h = max(0.0, float(kappa_h))
    k_a = max(0.0, float(kappa_a))

    raw_grid: dict[tuple[int, int], float] = {}
    total_p = 0.0

    for x in range(max_goals + 1):
        p_x = neg_binomial_pmf(x, lam_h, k_h)
        for y in range(max_goals + 1):
            p_y = neg_binomial_pmf(y, lam_a, k_a)
            tau = dixon_coles_tau(x, y, lam_h, lam_a, rho)
            p_score = max(0.0, p_x * p_y * tau)
            raw_grid[(x, y)] = p_score
            total_p += p_score

    normalized_grid: dict[tuple[int, int], float] = {}
    if total_p > 0.0:
        for score, p_score in raw_grid.items():
            normalized_grid[score] = p_score / total_p
    else:
        n_cells = (max_goals + 1) ** 2
        for score in raw_grid:
            normalized_grid[score] = 1.0 / n_cells

    return normalized_grid


class NegativeBinomialGoalModel:
    """Overdispersed goal expectancy model with empirical Bayesian shrinkage and dispersion estimation."""

    MODEL_NAME = "negative_binomial_goal_model"
    MODEL_VERSION = "0.2.0"
    FEATURE_SET_VERSION = "fs_v0.2_negbin_dispersion"

    def __init__(
        self,
        shrinkage_weight: float = 3.0,
        max_goals: int = 8,
        default_kappa: float = DEFAULT_GOAL_KAPPA,
        rho: float = -0.06,
    ):
        self.shrinkage_weight = shrinkage_weight
        self.max_goals = max_goals
        self.default_kappa = default_kappa
        self.rho = rho
        self.is_fitted = False

        self.league_avg_home_goals = 1.45
        self.league_avg_away_goals = 1.15
        self.league_kappa_h = default_kappa
        self.league_kappa_a = default_kappa
        self.total_matches = 0
        self.team_stats: dict[str, dict[str, float]] = {}

    def fit(self, matches: list[dict[str, Any]]) -> NegativeBinomialGoalModel:
        """Fit ratings and empirical dispersion from historical match records."""
        if not matches:
            raise ValueError("Cannot fit NegativeBinomialGoalModel on empty match list.")

        h_scores = [float(m["home_score"]) for m in matches]
        a_scores = [float(m["away_score"]) for m in matches]
        self.total_matches = len(matches)

        self.league_avg_home_goals = max(0.5, sum(h_scores) / max(1, self.total_matches))
        self.league_avg_away_goals = max(0.5, sum(a_scores) / max(1, self.total_matches))

        # Empirical dispersion estimation from match distribution
        self.league_kappa_h = estimate_dispersion_kappa(h_scores) or self.default_kappa
        self.league_kappa_a = estimate_dispersion_kappa(a_scores) or self.default_kappa

        stats: dict[str, dict[str, float]] = {}

        def get_bucket(name: str) -> dict[str, float]:
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
            h_team = str(m["home_team"]).strip().lower()
            a_team = str(m["away_team"]).strip().lower()
            h_s = float(m["home_score"])
            a_s = float(m["away_score"])

            hb = get_bucket(h_team)
            hb["home_played"] += 1.0
            hb["home_scored"] += h_s
            hb["home_conceded"] += a_s

            ab = get_bucket(a_team)
            ab["away_played"] += 1.0
            ab["away_scored"] += a_s
            ab["away_conceded"] += h_s

        k = self.shrinkage_weight
        self.team_stats = {}
        for team, s in stats.items():
            hp = s["home_played"]
            ap = s["away_played"]

            exp_h_att = hp * self.league_avg_home_goals
            h_att = (s["home_scored"] + k * self.league_avg_home_goals) / (exp_h_att + k * self.league_avg_home_goals)

            exp_a_att = ap * self.league_avg_away_goals
            a_att = (s["away_scored"] + k * self.league_avg_away_goals) / (exp_a_att + k * self.league_avg_away_goals)

            exp_h_def = hp * self.league_avg_away_goals
            h_def = (s["home_conceded"] + k * self.league_avg_away_goals) / (exp_h_def + k * self.league_avg_away_goals)

            exp_a_def = ap * self.league_avg_home_goals
            a_def = (s["away_conceded"] + k * self.league_avg_home_goals) / (exp_a_def + k * self.league_avg_home_goals)

            self.team_stats[team] = {
                "home_attack": round(h_att, 4),
                "away_attack": round(a_att, 4),
                "home_defense": round(h_def, 4),
                "away_defense": round(a_def, 4),
                "matches_played": hp + ap,
            }

        self.is_fitted = True
        return self

    def predict_match(
        self,
        home_team: str,
        away_team: str,
        calibrate: bool = False,
    ) -> MatchPredictionOutput:
        """Predict match probabilities using Negative Binomial overdispersed distribution."""
        if not self.is_fitted:
            raise RuntimeError("NegativeBinomialGoalModel must be fitted before predict_match.")

        norm_h = str(home_team).strip().lower()
        norm_a = str(away_team).strip().lower()

        default_stat = {"home_attack": 1.0, "away_attack": 1.0, "home_defense": 1.0, "away_defense": 1.0, "matches_played": 0}
        h_stats = self.team_stats.get(norm_h, default_stat)
        a_stats = self.team_stats.get(norm_a, default_stat)

        lambda_h = max(0.1, self.league_avg_home_goals * h_stats["home_attack"] * a_stats["away_defense"])
        lambda_a = max(0.1, self.league_avg_away_goals * a_stats["away_attack"] * h_stats["home_defense"])

        grid_matrix = compute_neg_binomial_score_grid(
            lambda_h=lambda_h,
            lambda_a=lambda_a,
            kappa_h=self.league_kappa_h,
            kappa_a=self.league_kappa_a,
            rho=self.rho,
            max_goals=self.max_goals,
        )

        p_home = sum(p for (h, a), p in grid_matrix.items() if h > a)
        p_draw = sum(p for (h, a), p in grid_matrix.items() if h == a)
        p_away = sum(p for (h, a), p in grid_matrix.items() if h < a)

        grid_str = {f"{h}-{a}": round(p, 6) for (h, a), p in grid_matrix.items()}

        prob_home = round(p_home, 4)
        prob_draw = round(p_draw, 4)
        prob_away = round(p_away, 4)
        fair_h = round(1.0 / max(prob_home, 0.0001), 2)
        fair_d = round(1.0 / max(prob_draw, 0.0001), 2)
        fair_a = round(1.0 / max(prob_away, 0.0001), 2)

        if calibrate:
            try:
                from sports_engine.models.calibration import recalibrate_1x2
                prob_home, prob_draw, prob_away = recalibrate_1x2(prob_home, prob_draw, prob_away)
                fair_h = round(1.0 / max(prob_home, 0.0001), 2)
                fair_d = round(1.0 / max(prob_draw, 0.0001), 2)
                fair_a = round(1.0 / max(prob_away, 0.0001), 2)
            except Exception:
                pass

        return MatchPredictionOutput(
            home_team=home_team,
            away_team=away_team,
            expected_home_goals=round(lambda_h, 3),
            expected_away_goals=round(lambda_a, 3),
            home_probability=prob_home,
            draw_probability=prob_draw,
            away_probability=prob_away,
            fair_home_odds=fair_h,
            fair_draw_odds=fair_d,
            fair_away_odds=fair_a,
            model_name=self.MODEL_NAME,
            model_version=self.MODEL_VERSION,
            feature_set_version=self.FEATURE_SET_VERSION,
            metadata={
                "league_avg_home_goals": round(self.league_avg_home_goals, 3),
                "league_avg_away_goals": round(self.league_avg_away_goals, 3),
                "league_kappa_h": round(self.league_kappa_h, 4),
                "league_kappa_a": round(self.league_kappa_a, 4),
                "rho": self.rho,
                "grid_probability_sum": round(prob_home + prob_draw + prob_away, 6),
                "most_likely_score": max(grid_str.items(), key=lambda kv: kv[1])[0],
            },
        )
