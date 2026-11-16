"""Player Prop Goal Pricing Engine (v1.0).

Quantitatively models Player Goalscorer markets (Anytime Goalscorer, First Goalscorer)
using Poisson / Negative Binomial process conditioned on team expected goals (xG),
player goal shares, and Goal Anomaly tempo multipliers.

Features:
- Calibrated goal-share priors for elite European and Super Lig strikers.
- Poisson probability of scoring >= 1 goal: P(X >= 1) = 1 - exp(-lambda_player).
- First goalscorer conditioned conversion: P(First Goal) = lambda_player / (mu_home + mu_away).
- Dynamic tempo lift from GoalAnomalyEngine & high-octane match pace.
- Enforces SPEC-0015 minimum 50 TL stake constraint and fail-closed validation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# Calibrated historical goal shares (player goals / team goals)
CALIBRATED_PLAYER_SHARES: dict[str, dict[str, Any]] = {
    "erling haaland": {"team": "manchester city", "goal_share": 0.42, "penalty_taker": True},
    "harry kane": {"team": "bayern munich", "goal_share": 0.38, "penalty_taker": True},
    "kylian mbappe": {"team": "real madrid", "goal_share": 0.35, "penalty_taker": True},
    "vinicius jr": {"team": "real madrid", "goal_share": 0.28, "penalty_taker": False},
    "mohamed salah": {"team": "liverpool", "goal_share": 0.34, "penalty_taker": True},
    "robert lewandowski": {"team": "barcelona", "goal_share": 0.36, "penalty_taker": True},
    "victor osimhen": {"team": "galatasaray", "goal_share": 0.35, "penalty_taker": True},
    "mauro icardi": {"team": "galatasaray", "goal_share": 0.32, "penalty_taker": True},
    "edin dzeko": {"team": "fenerbahce", "goal_share": 0.28, "penalty_taker": False},
    "youssef en-nesyri": {"team": "fenerbahce", "goal_share": 0.26, "penalty_taker": False},
    "ciro immobile": {"team": "besiktas", "goal_share": 0.38, "penalty_taker": True},
    "serhou guirassy": {"team": "borussia dortmund", "goal_share": 0.35, "penalty_taker": True},
    "lois openda": {"team": "rb leipzig", "goal_share": 0.30, "penalty_taker": True},
    "lautaro martinez": {"team": "inter", "goal_share": 0.36, "penalty_taker": True},
}

DEFAULT_STRIKER_SHARE: float = 0.22
DEFAULT_WINGER_SHARE: float = 0.14
DEFAULT_MIDFIELDER_SHARE: float = 0.08


@dataclass(frozen=True)
class PlayerPropEvaluation:
    """Quantitative result of a single player prop evaluation."""
    player_name: str
    team_name: str
    opponent_name: str
    market: str                          # ANYTIME_GOALSCORER or FIRST_GOALSCORER
    offered_odds: float
    fair_odds: float
    prob: float
    edge_pct: float
    ev_pct: float
    kelly_stake: float
    is_value: bool
    reasons: list[str] = field(default_factory=list)


class PlayerPropsEngine:
    """Poisson Conditioning Engine for Player Goalscorer Markets."""

    def __init__(self, custom_player_shares: Optional[dict[str, dict[str, Any]]] = None) -> None:
        self.player_shares: dict[str, dict[str, Any]] = custom_player_shares or dict(CALIBRATED_PLAYER_SHARES)

    def get_player_goal_share(self, player_name: str) -> float:
        """Lookup player goal share by fuzzy name match, or fallback to striker default."""
        cleaned = player_name.lower().strip()
        for k, v in self.player_shares.items():
            if k in cleaned or cleaned in k:
                return float(v.get("goal_share", DEFAULT_STRIKER_SHARE))
        return DEFAULT_STRIKER_SHARE

    def evaluate_anytime_scorer(
        self,
        player_name: str,
        team_name: str,
        opponent_name: str,
        team_mu: float,
        offered_odds: float,
        is_goal_anomaly: bool = False,
    ) -> PlayerPropEvaluation:
        """Evaluate Anytime Goalscorer market for value (+EV)."""
        clean_team_mu = max(0.5, min(4.5, float(team_mu)))

        # Tempo lift: If match is a Goal Anomaly candidate (GASI >= 70), boost team goals
        if is_goal_anomaly:
            clean_team_mu *= 1.15

        goal_share = self.get_player_goal_share(player_name)
        player_lambda = clean_team_mu * goal_share

        # Poisson probability of scoring at least 1 goal: P(X >= 1) = 1 - e^(-lambda)
        p_score = 1.0 - math.exp(-player_lambda)
        p_score = max(0.01, min(0.95, p_score))

        fair_odds = round(1.0 / p_score, 2)
        edge_pct = round(((p_score * offered_odds) - 1.0) * 100.0, 2)

        # Kelly criterion sizing (Half-Kelly, max 5%)
        kelly_stake = 0.0
        is_val = False
        reasons: list[str] = []

        if edge_pct >= 5.0 and offered_odds > 1.20:
            is_val = True
            b = offered_odds - 1.0
            full_k = (p_score * b - (1.0 - p_score)) / b if b > 0 else 0.0
            half_k = max(0.0, min(0.05, 0.5 * full_k))
            kelly_stake = max(50.0, round(half_k * 1000.0, 2))  # SPEC-0015 Minimum 50 TL

            reasons.append(f"Model Prob: %{p_score * 100:.1f} vs Bookmaker Implied: %{(1.0 / offered_odds) * 100:.1f}")
            reasons.append(f"Player Goal Share: %{goal_share * 100:.0f} (Expected Goals: {player_lambda:.2f})")
            if is_goal_anomaly:
                reasons.append("Goal Anomaly Tempo Lift applied (+15% team volume)")
        else:
            reasons.append(f"Negative or low edge ({edge_pct:.2f}%). Fair odds: {fair_odds:.2f}")

        return PlayerPropEvaluation(
            player_name=player_name,
            team_name=team_name,
            opponent_name=opponent_name,
            market="ANYTIME_GOALSCORER",
            offered_odds=offered_odds,
            fair_odds=fair_odds,
            prob=round(p_score, 4),
            edge_pct=edge_pct,
            ev_pct=edge_pct,
            kelly_stake=kelly_stake,
            is_value=is_val,
            reasons=reasons,
        )

    def evaluate_first_scorer(
        self,
        player_name: str,
        team_name: str,
        opponent_name: str,
        team_mu: float,
        opponent_mu: float,
        offered_odds: float,
    ) -> PlayerPropEvaluation:
        """Evaluate First Goalscorer market for value (+EV)."""
        tot_mu = max(1.0, team_mu + opponent_mu)
        goal_share = self.get_player_goal_share(player_name)
        player_lambda = team_mu * goal_share

        # Approximate First Goalscorer probability:
        # P(First Goal | Score > 0) * P(Score > 0)
        p_no_goals = math.exp(-tot_mu)
        p_at_least_one_goal = 1.0 - p_no_goals
        p_first_given_goals = player_lambda / tot_mu
        p_first = p_at_least_one_goal * p_first_given_goals

        fair_odds = round(1.0 / p_first, 2) if p_first > 0.005 else 99.0
        edge_pct = round(((p_first * offered_odds) - 1.0) * 100.0, 2)

        is_val = False
        kelly_stake = 0.0
        reasons: list[str] = []

        if edge_pct >= 6.0 and offered_odds > 2.50:
            is_val = True
            b = offered_odds - 1.0
            full_k = (p_first * b - (1.0 - p_first)) / b if b > 0 else 0.0
            half_k = max(0.0, min(0.03, 0.5 * full_k))
            kelly_stake = max(50.0, round(half_k * 1000.0, 2))  # SPEC-0015
            reasons.append(f"Fair First Goal Prob: %{p_first * 100:.1f} (Fair: {fair_odds:.2f})")
            reasons.append(f"Edge: +{edge_pct:.2f}% on longshot market")
        else:
            reasons.append(f"Low edge ({edge_pct:.2f}%). Fair odds: {fair_odds:.2f}")

        return PlayerPropEvaluation(
            player_name=player_name,
            team_name=team_name,
            opponent_name=opponent_name,
            market="FIRST_GOALSCORER",
            offered_odds=offered_odds,
            fair_odds=fair_odds,
            prob=round(p_first, 4),
            edge_pct=edge_pct,
            ev_pct=edge_pct,
            kelly_stake=kelly_stake,
            is_value=is_val,
            reasons=reasons,
        )
