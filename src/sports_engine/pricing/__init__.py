"""Pricing Intelligence module for sports-engine (Phase 2A).

Provides:
- No-Vig calculations (Multiplicative, Shin, Power)
- Overround, raw implied probability, and market fair odds derivation
- Selection-level edge calculation with PREMATCH/LIVE phase guards
- Strict exclusion of MODEL_DERIVED and high-odds markets in Phase 2A
"""

from sports_engine.domain.pricing_contract import (
    MarketPricingResult,
    NoVigMethod,
    Phase2ASupportedMarket,
    SelectionEdge,
)
from sports_engine.pricing.edge import (
    calculate_selection_edge,
    is_phase_2a_allowed_market,
)
from sports_engine.pricing.no_vig import (
    calculate_overround,
    compute_no_vig,
    no_vig_multiplicative,
    no_vig_power,
    no_vig_shin,
)

__all__ = [
    "NoVigMethod",
    "Phase2ASupportedMarket",
    "MarketPricingResult",
    "SelectionEdge",
    "calculate_overround",
    "no_vig_multiplicative",
    "no_vig_shin",
    "no_vig_power",
    "compute_no_vig",
    "is_phase_2a_allowed_market",
    "calculate_selection_edge",
]
