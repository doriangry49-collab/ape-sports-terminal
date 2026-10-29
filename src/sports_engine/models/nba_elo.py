"""NBA Elo Rating Baseline Model with Home Court Advantage."""

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NBAPredictionOutput:
    """Output container for NBA 2-way win probabilities and fair odds."""

    home_team: str
    away_team: str
    home_probability: float
    away_probability: float
    fair_home_odds: float
    fair_away_odds: float
    home_rating: float
    away_rating: float
    model_name: str
    model_version: str
    feature_set_version: str
    metadata: dict[str, Any]


class NBAEloModel:
    """Dynamic Elo rating model for NBA basketball with margin-of-victory adjustments and HCA."""

    MODEL_NAME = "nba_elo_baseline"
    MODEL_VERSION = "0.1.0"
    FEATURE_SET_VERSION = "nba_fs_v0.1"

    def __init__(
        self,
        base_rating: float = 1500.0,
        home_court_advantage: float = 65.0,
        k_factor: float = 20.0,
    ):
        """
        Args:
            base_rating: Initial rating for unranked teams.
            home_court_advantage: Elo bonus added to home team (NBA empirical avg ~65 pts).
            k_factor: Base rating adjustment magnitude.
        """
        self.base_rating = base_rating
        self.hca = home_court_advantage
        self.k_factor = k_factor

        self.team_ratings: dict[str, float] = {}
        self.team_games: dict[str, int] = {}
        self.team_wins: dict[str, int] = {}
        self.total_games_fitted = 0
        self.is_fitted = False

    def get_rating(self, team: str) -> float:
        """Get current rating for a team, defaulting to base_rating."""
        return self.team_ratings.get(team, self.base_rating)

    def calculate_win_probability(self, home_team: str, away_team: str) -> float:
        """Compute expected probability of home team winning."""
        r_home = self.get_rating(home_team) + self.hca
        r_away = self.get_rating(away_team)
        exponent = -(r_home - r_away) / 400.0
        prob_home = 1.0 / (1.0 + math.pow(10.0, exponent))
        return min(max(prob_home, 0.01), 0.99)

    def fit(self, games: list[dict[str, Any]]) -> "NBAEloModel":
        """Train Elo ratings chronologically across completed NBA games.

        Each game dict requires:
        - 'home_team': normalized team name
        - 'away_team': normalized team name
        - 'home_score': int
        - 'away_score': int
        """
        if not games:
            raise ValueError("Cannot fit NBAEloModel on empty games list.")

        self.team_ratings = {}
        self.team_games = {}
        self.team_wins = {}
        self.total_games_fitted = 0

        for g in games:
            h_team = g["home_team"]
            a_team = g["away_team"]
            h_score = int(g["home_score"])
            a_score = int(g["away_score"])

            # Win probability prior to match
            p_home = self.calculate_win_probability(h_team, a_team)
            s_home = 1.0 if h_score > a_score else 0.0

            # Margin of victory adjustment (FiveThirtyEight style dampening)
            margin = abs(h_score - a_score)
            mov_multiplier = math.log(max(margin, 1) + 1.0) * (2.2 / ((self.get_rating(h_team) - self.get_rating(a_team)) * 0.001 + 2.2))
            mov_multiplier = max(0.5, min(mov_multiplier, 3.5))

            delta = self.k_factor * mov_multiplier * (s_home - p_home)

            # Update ratings
            self.team_ratings[h_team] = round(self.get_rating(h_team) + delta, 2)
            self.team_ratings[a_team] = round(self.get_rating(a_team) - delta, 2)

            self.team_games[h_team] = self.team_games.get(h_team, 0) + 1
            self.team_games[a_team] = self.team_games.get(a_team, 0) + 1
            if s_home == 1.0:
                self.team_wins[h_team] = self.team_wins.get(h_team, 0) + 1
            else:
                self.team_wins[a_team] = self.team_wins.get(a_team, 0) + 1

            self.total_games_fitted += 1

        self.is_fitted = True
        return self

    def predict_game(self, home_team: str, away_team: str) -> NBAPredictionOutput:
        """Predict win probabilities and fair odds for an upcoming NBA game."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict_game can be called.")

        p_home = round(self.calculate_win_probability(home_team, away_team), 4)
        p_away = round(1.0 - p_home, 4)

        fair_h_odds = round(1.0 / max(p_home, 0.001), 2)
        fair_a_odds = round(1.0 / max(p_away, 0.001), 2)

        r_h = self.get_rating(home_team)
        r_a = self.get_rating(away_team)

        return NBAPredictionOutput(
            home_team=home_team,
            away_team=away_team,
            home_probability=p_home,
            away_probability=p_away,
            fair_home_odds=fair_h_odds,
            fair_away_odds=fair_a_odds,
            home_rating=r_h,
            away_rating=r_a,
            model_name=self.MODEL_NAME,
            model_version=self.MODEL_VERSION,
            feature_set_version=self.FEATURE_SET_VERSION,
            metadata={
                "home_court_advantage": self.hca,
                "effective_home_rating": round(r_h + self.hca, 2),
                "rating_differential": round((r_h + self.hca) - r_a, 2),
                "home_games_played": self.team_games.get(home_team, 0),
                "away_games_played": self.team_games.get(away_team, 0),
                "total_fitted_games": self.total_games_fitted,
            },
        )
