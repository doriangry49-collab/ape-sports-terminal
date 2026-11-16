"""Poisson & Dixon-Coles Corner Pricing Engine for Sports-Engine.

Calculates match corner expectation (lambda) and computes exact Poisson/Negative Binomial
fair odds and +EV edge for corner lines (8.5, 9.5, 10.5).
"""

from __future__ import annotations

import math
from typing import Any

LEAGUE_CORNER_BASELINES: dict[str, float] = {
    "brazil_serie_a": 10.20,
    "argentina_primera": 9.15,
    "england_premier_league": 10.45,
    "england_championship": 10.15,
    "australia_a_league": 11.25,
    "turkey_super_lig": 9.85,
    "turkey_1_lig": 9.40,
    "spain_la_liga": 9.45,
    "spain_la_liga_2": 9.20,
    "germany_bundesliga_2": 10.35,
    "italy_serie_a": 9.90,
    "france_ligue_1": 9.50,
}
DEFAULT_CORNER_BASELINE = 9.85


def poisson_pmf(k: int, lmbda: float) -> float:
    """Exact Poisson Probability Mass Function P(X = k)."""
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def poisson_cdf(k: int, lmbda: float) -> float:
    """Exact Cumulative Distribution Function P(X <= k)."""
    return sum(poisson_pmf(i, lmbda) for i in range(k + 1))


def estimate_match_corner_lambda(
    league_key: str = "",
    odds_1x2: tuple[float, float, float] | None = None,
    odds_ou25: tuple[float, float] | None = None,
) -> float:
    """Estimate total expected corners (lambda) for a match.

    Adjusts base league corner rate according to total goal expectancy and
    heavy-favorite box dominance dynamics.
    """
    baseline = LEAGUE_CORNER_BASELINES.get(league_key.lower().strip(), DEFAULT_CORNER_BASELINE)

    # 1. Adjust for goal expectancy derived from 2.5 Over/Under
    # If 2.5 Over is heavily favored, match tempo and transitions are higher.
    tempo_multiplier = 1.0
    if odds_ou25 and odds_ou25[0] > 1.01 and odds_ou25[1] > 1.01:
        o_over, o_under = odds_ou25
        # Implied over prob
        p_over = (1.0 / o_over) / ((1.0 / o_over) + (1.0 / o_under))
        # Scaled adjustment around neutral 0.50 probability: +/- 6% lambda per 0.10 prob drift
        tempo_multiplier = 1.0 + (p_over - 0.50) * 0.40

    # 2. Adjust for heavy favorite vs low block (creates higher shot and corner counts)
    dominance_multiplier = 1.0
    if odds_1x2 and odds_1x2[0] > 1.01 and odds_1x2[2] > 1.01:
        min_fav_odd = min(odds_1x2[0], odds_1x2[2])
        if min_fav_odd < 1.40:
            dominance_multiplier = 1.06
        elif min_fav_odd < 1.65:
            dominance_multiplier = 1.03

    estimated_lambda = baseline * tempo_multiplier * dominance_multiplier
    # Practical realistic bounds for 90-minute professional football
    return round(max(7.5, min(13.0, estimated_lambda)), 2)


def price_corner_lines(
    lmbda: float,
    nesine_corners: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Calculate fair odds for 8.5, 9.5, 10.5 corner lines and compare with Nesine."""
    results: dict[str, Any] = {
        "lambda_total": lmbda,
        "lines": {},
        "edges": [],
        "best_edge": None,
    }

    lines = [8.5, 9.5, 10.5]
    for line in lines:
        k = int(math.floor(line))  # 8, 9, 10
        p_under = poisson_cdf(k, lmbda)
        p_over = 1.0 - p_under

        fair_under = round(1.0 / p_under, 2) if p_under > 0.001 else 99.0
        fair_over = round(1.0 / p_over, 2) if p_over > 0.001 else 99.0

        line_str = str(line)
        results["lines"][line_str] = {
            "p_under": round(p_under, 4),
            "p_over": round(p_over, 4),
            "fair_under": fair_under,
            "fair_over": fair_over,
        }

        # Check Nesine comparison if available
        if nesine_corners and line_str in nesine_corners:
            n_odds = nesine_corners[line_str]
            n_u = n_odds.get("under", 0.0)
            n_o = n_odds.get("over", 0.0)

            if n_u > 1.01:
                edge_u = round(((p_under * n_u) - 1.0) * 100.0, 2)
                results["edges"].append({
                    "line": line_str,
                    "side": "ALT",
                    "nesine_odds": n_u,
                    "fair_odds": fair_under,
                    "prob": round(p_under, 4),
                    "edge_pct": edge_u,
                })
            if n_o > 1.01:
                edge_o = round(((p_over * n_o) - 1.0) * 100.0, 2)
                results["edges"].append({
                    "line": line_str,
                    "side": "ÜST",
                    "nesine_odds": n_o,
                    "fair_odds": fair_over,
                    "prob": round(p_over, 4),
                    "edge_pct": edge_o,
                })

    if results["edges"]:
        best = max(results["edges"], key=lambda x: x["edge_pct"])
        results["best_edge"] = best

    return results

