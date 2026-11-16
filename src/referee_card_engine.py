"""Referee Discipline & Card Pricing Engine for Sports-Engine.

Profiles referee card tendencies from historical matches and computes Poisson
fair odds for Total Cards (3.5, 4.5, 5.5).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
REFEREE_PARQUET = ROOT_DIR / "data" / "gold" / "referee_profiles.parquet"

DEFAULT_CARD_LAMBDA = 4.10


def poisson_pmf(k: int, lmbda: float) -> float:
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def poisson_cdf(k: int, lmbda: float) -> float:
    return sum(poisson_pmf(i, lmbda) for i in range(k + 1))


def get_referee_card_lambda(referee_name: str | None = None, league_default: float = DEFAULT_CARD_LAMBDA) -> float:
    """Look up empirical referee card expectation or fallback to league baseline."""
    if not referee_name or not REFEREE_PARQUET.exists():
        return league_default

    try:
        df = pd.read_parquet(REFEREE_PARQUET)
        match = df[df["referee"].str.lower() == referee_name.strip().lower()]
        if not match.empty:
            avg_c = float(match["avg_total_cards"].iloc[0])
            # Regress towards league mean if small sample
            n_matches = int(match["matches_officiated"].iloc[0])
            weight = min(1.0, n_matches / 30.0)
            return round(weight * avg_c + (1.0 - weight) * league_default, 2)
    except Exception:
        pass

    return league_default


def price_card_lines(lmbda: float, offered_odds: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """Price 3.5, 4.5, 5.5 Total Card lines."""
    results: dict[str, Any] = {
        "lambda_cards": lmbda,
        "lines": {},
        "edges": [],
    }

    for line in [3.5, 4.5, 5.5]:
        k = int(math.floor(line))  # 3, 4, 5
        p_under = poisson_cdf(k, lmbda)
        p_over = 1.0 - p_under

        fair_u = round(1.0 / p_under, 2) if p_under > 0.001 else 99.0
        fair_o = round(1.0 / p_over, 2) if p_over > 0.001 else 99.0

        line_str = str(line)
        results["lines"][line_str] = {
            "p_under": round(p_under, 4),
            "p_over": round(p_over, 4),
            "fair_under": fair_u,
            "fair_over": fair_o,
        }

        if offered_odds and line_str in offered_odds:
            o_odds = offered_odds[line_str]
            u_odd = o_odds.get("under", 0.0)
            o_odd = o_odds.get("over", 0.0)

            if u_odd > 1.01:
                edge_u = round(((p_under * u_odd) - 1.0) * 100.0, 2)
                results["edges"].append({
                    "line": line_str,
                    "side": "ALT",
                    "offered_odds": u_odd,
                    "fair_odds": fair_u,
                    "prob": round(p_under, 4),
                    "edge_pct": edge_u,
                })
            if o_odd > 1.01:
                edge_o = round(((p_over * o_odd) - 1.0) * 100.0, 2)
                results["edges"].append({
                    "line": line_str,
                    "side": "ÜST",
                    "offered_odds": o_odd,
                    "fair_odds": fair_o,
                    "prob": round(p_over, 4),
                    "edge_pct": edge_o,
                })

    return results

