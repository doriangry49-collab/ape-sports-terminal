"""Advanced Negative Binomial & Game-State Corner Pricing Engine (Compatibility Module).

Re-exports AdvancedCornerEngine, Negative Binomial distribution functions, and Shin/Power
two-way de-vigging helpers from advanced_corner_model.
"""

from __future__ import annotations

try:
    from advanced_corner_model import (
        DEFAULT_CORNER_BASELINE,
        DEFAULT_KAPPA,
        LEAGUE_CORNER_BASELINES,
        TEAM_PROFILES_PATH,
        AdvancedCornerEngine,
        devig_two_way_shin_power,
        neg_binomial_cdf,
        neg_binomial_pmf,
    )
except ImportError:
    from src.advanced_corner_model import (
        DEFAULT_CORNER_BASELINE,
        DEFAULT_KAPPA,
        LEAGUE_CORNER_BASELINES,
        TEAM_PROFILES_PATH,
        AdvancedCornerEngine,
        devig_two_way_shin_power,
        neg_binomial_cdf,
        neg_binomial_pmf,
    )

__all__ = [
    "AdvancedCornerEngine",
    "DEFAULT_CORNER_BASELINE",
    "DEFAULT_KAPPA",
    "LEAGUE_CORNER_BASELINES",
    "TEAM_PROFILES_PATH",
    "devig_two_way_shin_power",
    "neg_binomial_cdf",
    "neg_binomial_pmf",
]

