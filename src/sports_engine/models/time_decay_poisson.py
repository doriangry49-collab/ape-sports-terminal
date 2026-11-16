"""Model C: Time-Decayed Bivariate Poisson Goal Expectancy Engine (TASK-016 & TASK-017).

Features:
- Empirical Bayesian shrinkage (k=3.0) towards league mean goals.
- Exponential time-decay weighting (default half-life = 180 days).
- Strict point-in-time data cutoff (anti-leakage guarantee).
- League eligibility guard (minimum sample threshold, default 30 matches).
- Explicit status: MODEL_C_AVAILABLE vs INSUFFICIENT_HISTORY.
- Independent output: generates probabilities and fair odds without bookmaker odds input.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sports_engine.models.poisson import MatchPredictionOutput, compute_bivariate_score_grid


class ModelCStatus:
    AVAILABLE = "MODEL_C_AVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


@dataclass(frozen=True)
class LeagueEligibility:
    """Eligibility status of a competition for Model C execution."""
    competition_id: str
    competition_name: str
    historical_matches_count: int
    min_required_matches: int
    status: str
    reason: str


class TimeDecayedPoissonModel:
    """Time-decayed bivariate Poisson model for team rating and goal expectancy."""

    MODEL_NAME = "model_c_timedecayed_poisson"
    MODEL_VERSION = "0.2.0"
    FEATURE_SET_VERSION = "fs_v0.2_decay180d_shrink3k"
    RATING_VERSION = "eb_shrinkage_k3_decay180d"

    def __init__(
        self,
        decay_half_life_days: float = 180.0,
        shrinkage_weight: float = 3.0,
        min_required_matches: int = 30,
        max_goals: int = 8,
        lambda_3: float = 0.05,
        rho: float = -0.06,
    ):
        self.decay_half_life_days = decay_half_life_days
        self.decay_rate = math.log(2.0) / max(1.0, decay_half_life_days)
        self.shrinkage_weight = shrinkage_weight
        self.min_required_matches = min_required_matches
        self.max_goals = max_goals
        self.lambda_3 = lambda_3
        self.rho = rho
        self.is_fitted = False

        self.league_avg_home_goals = 1.45
        self.league_avg_away_goals = 1.15
        self.total_matches = 0
        self.total_weighted_matches = 0.0
        self.team_stats: dict[str, dict[str, float]] = {}
        self.data_cutoff: datetime | None = None

    def check_eligibility(
        self,
        competition_id: str,
        competition_name: str,
        matches: list[dict[str, Any]],
    ) -> LeagueEligibility:
        """Check if competition satisfies minimum historical sample requirement."""
        count = len(matches)
        if count >= self.min_required_matches:
            return LeagueEligibility(
                competition_id=competition_id,
                competition_name=competition_name,
                historical_matches_count=count,
                min_required_matches=self.min_required_matches,
                status=ModelCStatus.AVAILABLE,
                reason=f"Sufficient history: {count} matches >= {self.min_required_matches} required.",
            )
        return LeagueEligibility(
            competition_id=competition_id,
            competition_name=competition_name,
            historical_matches_count=count,
            min_required_matches=self.min_required_matches,
            status=ModelCStatus.INSUFFICIENT_HISTORY,
            reason=f"Insufficient history: {count} matches < {self.min_required_matches} required threshold.",
        )

    def fit(
        self,
        matches: list[dict[str, Any]],
        data_cutoff: datetime | None = None,
    ) -> "TimeDecayedPoissonModel":
        """Fit time-decayed attack and defense ratings strictly up to data_cutoff.

        Each match must contain:
        - 'home_team', 'away_team', 'home_score', 'away_score', 'event_date'
        """
        if not matches:
            raise ValueError("Cannot fit TimeDecayedPoissonModel on empty match list.")

        self.data_cutoff = data_cutoff

        # Filter strictly before data_cutoff (anti-leakage)
        filtered_matches = []
        for m in matches:
            raw_dt = m.get("event_date")
            if not raw_dt:
                continue
            if isinstance(raw_dt, datetime):
                dt = raw_dt if raw_dt.tzinfo is not None else raw_dt.replace(tzinfo=UTC)
            else:
                dt = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)

            if data_cutoff is not None and dt >= data_cutoff:
                # Discard future matches
                continue
            filtered_matches.append((m, dt))

        if len(filtered_matches) < self.min_required_matches:
            raise ValueError(
                f"Cannot fit Model C: after cutoff filter, {len(filtered_matches)} matches remain, "
                f"which is less than required minimum {self.min_required_matches}."
            )

        ref_time = data_cutoff or datetime.now(UTC)
        total_weighted_h = 0.0
        total_weighted_a = 0.0
        total_weight = 0.0

        stats: dict[str, dict[str, float]] = {}

        def get_bucket(name: str) -> dict[str, float]:
            if name not in stats:
                stats[name] = {
                    "h_weight": 0.0,
                    "a_weight": 0.0,
                    "h_scored_w": 0.0,
                    "h_conceded_w": 0.0,
                    "a_scored_w": 0.0,
                    "a_conceded_w": 0.0,
                    "matches_count": 0.0,
                }
            return stats[name]

        for m, dt in filtered_matches:
            h_team = str(m["home_team"]).strip().lower()
            a_team = str(m["away_team"]).strip().lower()
            h_score = float(m["home_score"])
            a_score = float(m["away_score"])

            # Time decay weight: w = exp(-lambda * delta_t_days)
            age_days = max(0.0, (ref_time - dt).total_seconds() / 86400.0)
            w = math.exp(-self.decay_rate * age_days)

            total_weighted_h += h_score * w
            total_weighted_a += a_score * w
            total_weight += w

            h_b = get_bucket(h_team)
            h_b["h_weight"] += w
            h_b["h_scored_w"] += h_score * w
            h_b["h_conceded_w"] += a_score * w
            h_b["matches_count"] += 1.0

            a_b = get_bucket(a_team)
            a_b["a_weight"] += w
            a_b["a_scored_w"] += a_score * w
            a_b["a_conceded_w"] += h_score * w
            a_b["matches_count"] += 1.0

        self.total_matches = len(filtered_matches)
        self.total_weighted_matches = total_weight
        self.league_avg_home_goals = max(0.5, total_weighted_h / max(0.01, total_weight))
        self.league_avg_away_goals = max(0.5, total_weighted_a / max(0.01, total_weight))

        # Shrunk team ratings with Empirical Bayes shrinkage
        k = self.shrinkage_weight
        mu_h = self.league_avg_home_goals
        mu_a = self.league_avg_away_goals
        self.team_stats = {}

        for team, s in stats.items():
            h_w = s["h_weight"]
            a_w = s["a_weight"]

            # Home attack = (weighted_scored + k * mu_H) / (h_weight * mu_H + k * mu_H)
            h_att = (s["h_scored_w"] + k * mu_h) / (h_w * mu_h + k * mu_h)
            # Away attack = (weighted_scored + k * mu_A) / (a_w * mu_A + k * mu_A)
            a_att = (s["a_scored_w"] + k * mu_a) / (a_w * mu_a + k * mu_a)
            # Home defense = (weighted_conceded + k * mu_A) / (h_w * mu_A + k * mu_A)
            h_def = (s["h_conceded_w"] + k * mu_a) / (h_w * mu_a + k * mu_a)
            # Away defense = (weighted_conceded + k * mu_H) / (a_w * mu_H + k * mu_H)
            a_def = (s["a_conceded_w"] + k * mu_h) / (a_w * mu_h + k * mu_h)

            self.team_stats[team] = {
                "home_attack": round(h_att, 4),
                "away_attack": round(a_att, 4),
                "home_defense": round(h_def, 4),
                "away_defense": round(a_def, 4),
                "matches_played": s["matches_count"],
            }

        self.is_fitted = True
        return self

    def predict_match(
        self,
        home_team: str,
        away_team: str,
        prediction_timestamp: datetime | None = None,
    ) -> MatchPredictionOutput:
        """Derive expected goals lambda_h and lambda_a for a matchup."""
        if not self.is_fitted:
            raise RuntimeError("Model C must be fitted before predict_match can be called.")

        norm_h = str(home_team).strip().lower()
        norm_a = str(away_team).strip().lower()

        # Fallback to 1.0 (league average rating) if team has no historical records
        default_stat = {"home_attack": 1.0, "away_attack": 1.0, "home_defense": 1.0, "away_defense": 1.0, "matches_played": 0}
        h_s = self.team_stats.get(norm_h, default_stat)
        a_s = self.team_stats.get(norm_a, default_stat)

        # Expected goals lambda
        lambda_h = max(0.1, self.league_avg_home_goals * h_s["home_attack"] * a_s["away_defense"])
        lambda_a = max(0.1, self.league_avg_away_goals * a_s["away_attack"] * h_s["home_defense"])

        # Compute exact Bivariate Poisson + Dixon-Coles normalized score distribution
        grid_matrix = compute_bivariate_score_grid(
            lambda_h=lambda_h,
            lambda_a=lambda_a,
            lambda_3=self.lambda_3,
            rho=self.rho,
            max_goals=self.max_goals,
        )

        p_home = sum(p for (x, y), p in grid_matrix.items() if x > y)
        p_draw = sum(p for (x, y), p in grid_matrix.items() if x == y)
        p_away = sum(p for (x, y), p in grid_matrix.items() if x < y)

        p_ts = (prediction_timestamp or datetime.now(UTC)).isoformat()
        cutoff_iso = self.data_cutoff.isoformat() if self.data_cutoff else p_ts

        return MatchPredictionOutput(
            home_team=home_team,
            away_team=away_team,
            expected_home_goals=round(lambda_h, 4),
            expected_away_goals=round(lambda_a, 4),
            home_probability=round(p_home, 4),
            draw_probability=round(p_draw, 4),
            away_probability=round(p_away, 4),
            fair_home_odds=round(1.0 / max(0.0001, p_home), 2),
            fair_draw_odds=round(1.0 / max(0.0001, p_draw), 2),
            fair_away_odds=round(1.0 / max(0.0001, p_away), 2),
            model_name=self.MODEL_NAME,
            model_version=self.MODEL_VERSION,
            feature_set_version=self.FEATURE_SET_VERSION,
            metadata={
                "rating_version": self.RATING_VERSION,
                "decay_half_life_days": self.decay_half_life_days,
                "shrinkage_weight": self.shrinkage_weight,
                "lambda_3": self.lambda_3,
                "rho": self.rho,
                "grid_sum": round(p_home + p_draw + p_away, 6),
                "historical_data_cutoff": cutoff_iso,
                "prediction_timestamp": p_ts,
                "home_team_ratings": h_s,
                "away_team_ratings": a_s,
                "league_avg_home_goals": round(self.league_avg_home_goals, 4),
                "league_avg_away_goals": round(self.league_avg_away_goals, 4),
            },
        )
