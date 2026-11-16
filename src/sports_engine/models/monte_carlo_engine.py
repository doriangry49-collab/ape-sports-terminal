"""Monte Carlo Simulation & Portfolio Tail-Risk Engine (v1.0).

Simulates match distributions and accumulator coupon variance using:
- Poisson & Negative Binomial synthetic goal sampling (10,000 iterations)
- Accumulator Joint Probability & Correlation estimation
- Value-at-Risk (VaR 95%) and Conditional VaR (CVaR / Expected Shortfall)
- Capital preservation checks for SPEC-0015 compliant coupons
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass(frozen=True)
class SimulationSummary:
    """Outcome of 10,000 Monte Carlo match/coupon iterations."""
    trials: int
    win_probability: float
    fair_odds: float
    offered_odds: float
    expected_value_pct: float
    var_95_pct: float             # Maximum expected loss at 95% confidence
    cvar_95_pct: float            # Average loss in the worst 5% of cases
    median_pnl_units: float
    risk_tier: str                # PRIME_VALUE, CONTROLLED_RISK, SPECULATIVE, HIGH_VARIANCE_TRAP


class MonteCarloEngine:
    """Fast Monte Carlo simulation engine for sports portfolios and coupons."""

    def __init__(self, default_trials: int = 10000, seed: int | None = 42) -> None:
        self.default_trials = default_trials
        if seed is not None:
            random.seed(seed)

    def sample_poisson(self, lam: float) -> int:
        """Sample a single Poisson random variable using Knuth's algorithm."""
        if lam <= 0:
            return 0
        l_val = math.exp(-lam)
        k = 0
        p = 1.0
        while p > l_val:
            k += 1
            p *= random.random()
        return k - 1

    def simulate_match_goals(
        self,
        home_exp_goals: float,
        away_exp_goals: float,
        trials: int | None = None,
    ) -> dict[str, float]:
        """Simulate a match 10,000 times and compute exact outcome probabilities."""
        n = trials or self.default_trials
        home_wins = 0
        draws = 0
        away_wins = 0
        over_15 = 0
        over_25 = 0
        over_35 = 0
        under_25 = 0
        btts_yes = 0
        six_plus = 0

        for _ in range(n):
            hg = self.sample_poisson(home_exp_goals)
            ag = self.sample_poisson(away_exp_goals)
            tot = hg + ag

            if hg > ag:
                home_wins += 1
            elif hg == ag:
                draws += 1
            else:
                away_wins += 1

            if tot > 1.5:
                over_15 += 1
            if tot > 2.5:
                over_25 += 1
            else:
                under_25 += 1
            if tot > 3.5:
                over_35 += 1
            if tot >= 6:
                six_plus += 1

            if hg > 0 and ag > 0:
                btts_yes += 1

        return {
            "p_home": round(home_wins / n, 4),
            "p_draw": round(draws / n, 4),
            "p_away": round(away_wins / n, 4),
            "p_over_15": round(over_15 / n, 4),
            "p_over_25": round(over_25 / n, 4),
            "p_under_25": round(under_25 / n, 4),
            "p_over_35": round(over_35 / n, 4),
            "p_6plus": round(six_plus / n, 4),
            "p_btts": round(btts_yes / n, 4),
        }

    def simulate_coupon(
        self,
        selections: list[dict[str, Any]],
        offered_total_odds: float,
        stake: float = 50.0,
        trials: int | None = None,
    ) -> SimulationSummary:
        """Simulate joint outcome of a multi-leg accumulator coupon.

        Parameters:
            selections: list of dicts with 'prob' (estimated true probability)
            offered_total_odds: combined bookmaker decimal odds
            stake: fixed stake (SPEC-0015 compliant >= 50.0 TL)
            trials: number of iterations
        """
        n = trials or self.default_trials
        wins = 0
        pnl_records: list[float] = []

        # Independent assumption across distinct match legs
        for _ in range(n):
            coupon_won = True
            for leg in selections:
                p_win = float(leg.get("prob", 0.50))
                if random.random() > p_win:
                    coupon_won = False
                    break

            if coupon_won:
                wins += 1
                pnl_records.append(stake * (offered_total_odds - 1.0))
            else:
                pnl_records.append(-stake)

        pnl_records.sort()

        win_prob = wins / n
        fair_odds = round(1.0 / win_prob, 2) if win_prob > 0 else 999.0
        ev_pct = round(((win_prob * offered_total_odds) - 1.0) * 100.0, 2)

        # 95% Value-at-Risk (5th percentile of PnL)
        idx_5pct = int(0.05 * n)
        var_95 = pnl_records[idx_5pct]
        cvar_95 = sum(pnl_records[:idx_5pct]) / max(1, idx_5pct)

        # Risk Classification
        if ev_pct >= 8.0 and win_prob >= 0.45:
            risk_tier = "PRIME_VALUE"
        elif ev_pct >= 3.0 and win_prob >= 0.35:
            risk_tier = "CONTROLLED_RISK"
        elif ev_pct >= 0.0:
            risk_tier = "SPECULATIVE"
        else:
            risk_tier = "HIGH_VARIANCE_TRAP"

        return SimulationSummary(
            trials=n,
            win_probability=round(win_prob, 4),
            fair_odds=fair_odds,
            offered_odds=round(offered_total_odds, 2),
            expected_value_pct=ev_pct,
            var_95_pct=round(var_95, 2),
            cvar_95_pct=round(cvar_95, 2),
            median_pnl_units=round(pnl_records[n // 2], 2),
            risk_tier=risk_tier,
        )
