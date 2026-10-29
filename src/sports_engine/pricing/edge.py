"""Edge calculation engine strictly enforcing Phase 2A boundaries and Phase Guards.

Phase 2A Boundaries:
- Allowed markets: '1X2', 'TOTALS', 'BTTS'
- Allowed source classification: 'BOOKMAKER_OFFERED' only
- Forbidden in Phase 2A: 'MODEL_DERIVED' markets, high-odds / longshots (Correct Score, HT/FT, etc.)
- Phase guard: PREMATCH model <-> PREMATCH odds, LIVE model <-> LIVE odds
- Explicit separation: raw_edge vs adjusted_edge (no fake uncertainty heuristics)
"""

from typing import Any

from sports_engine.domain.odds_contract import validate_phase_compatibility
from sports_engine.domain.pricing_contract import Phase2ASupportedMarket, SelectionEdge


def is_phase_2a_allowed_market(market_name: str) -> bool:
    """Check if market is permitted in Phase 2A."""
    norm = market_name.upper().strip()
    return norm in {
        Phase2ASupportedMarket.ONE_X_TWO.value,
        Phase2ASupportedMarket.TOTALS.value,
        Phase2ASupportedMarket.BTTS.value,
        "1X2",
        "TOTALS",
        "BTTS",
        "H2H",
        "OVER_UNDER",
    }


def calculate_selection_edge(
    fixture_id: str,
    market: str,
    selection: str,
    entry_odds: float,
    model_probability: float,
    market_no_vig_probability: float,
    model_phase: str = "PREMATCH",
    odds_phase: str = "PREMATCH",
    source_classification: str = "BOOKMAKER_OFFERED",
    uncertainty_penalty: float | None = None,
    notes: str = "",
) -> SelectionEdge:
    """Calculate raw edge and optional uncertainty-adjusted edge for a single selection.

    Formulae:
        raw_edge = model_probability - market_no_vig_probability
        model_fair_odds = 1.0 / model_probability (if model_probability > 0)
        adjusted_edge = raw_edge - uncertainty_penalty (if uncertainty_penalty is provided)

    Direction & Semantics:
        - raw_edge > 0: Model estimates higher probability than market fair consensus.
          (Positive expected value before fees/slippage).
        - raw_edge < 0: Market fair consensus implies higher probability than model.
          (Negative expected value).
        - adjusted_edge: If uncertainty_penalty is None, adjusted_edge is strictly None (UNKNOWN).
          No arbitrary or fake uncertainty penalty is invented.
    """
    # 1. Market Scope Guard (Phase 2A strictly restricts to 1X2, Totals, BTTS)
    if not is_phase_2a_allowed_market(market):
        raise ValueError(
            f"Market '{market}' is not permitted in Phase 2A. "
            f"High-odds / longshot markets (Correct Score, HT/FT, Asian Handicaps, etc.) "
            f"are deferred to Phase 2C."
        )

    # 2. Source Classification Guard (MODEL_DERIVED markets cannot claim bookmaker offers)
    if source_classification.upper().strip() == "MODEL_DERIVED":
        raise ValueError(
            f"Market '{market}' has source_classification='MODEL_DERIVED'. "
            f"MODEL_DERIVED markets are strictly excluded from Phase 2A Edge Engine."
        )

    # 3. Phase Guard: Enforce PREMATCH <-> PREMATCH and LIVE <-> LIVE
    validate_phase_compatibility(model_phase, odds_phase)

    # 4. Numeric Bounds Validation
    if entry_odds <= 1.0:
        raise ValueError(f"Entry odds must be > 1.0, got {entry_odds}")
    if not (0.0 <= model_probability <= 1.0):
        raise ValueError(f"Model probability must be in [0.0, 1.0], got {model_probability}")
    if not (0.0 <= market_no_vig_probability <= 1.0):
        raise ValueError(f"Market no-vig probability must be in [0.0, 1.0], got {market_no_vig_probability}")

    # 5. Raw Edge and Fair Odds Calculation
    raw_edge = model_probability - market_no_vig_probability
    model_fair_odds = 1.0 / model_probability if model_probability > 0 else float("inf")

    # 6. Uncertainty handling (strictly no fake heuristics)
    adjusted_edge: float | None = None
    if uncertainty_penalty is not None:
        if uncertainty_penalty < 0:
            raise ValueError(f"Uncertainty penalty cannot be negative, got {uncertainty_penalty}")
        adjusted_edge = raw_edge - uncertainty_penalty

    return SelectionEdge(
        fixture_id=fixture_id,
        market=market.upper().strip(),
        selection=selection,
        entry_odds=entry_odds,
        model_probability=model_probability,
        model_fair_odds=model_fair_odds,
        market_no_vig_probability=market_no_vig_probability,
        raw_edge=raw_edge,
        adjusted_edge=adjusted_edge,
        source_classification=source_classification,
        match_phase=model_phase.upper().strip(),
        notes=notes,
    )
