"""Draw No Bet (DNB) & Double Chance (Çifte Şans) Precision Engine.

Calculates exact fair odds, devigged probabilities, and +EV edges for:
  1. Draw No Bet (Beraberlikte İade: DNB 1, DNB 2) - refunds stake on draw.
  2. Double Chance (Çifte Şans: 1X, X2, 12).
  3. Detects soft bookmaker mispricings in Turkish bulletin (MBS 1).
"""

from __future__ import annotations

from typing import Any


def calculate_dnb_probabilities(
    p_home: float,
    p_draw: float,
    p_away: float,
) -> tuple[float, float, float, float]:
    """Calculate Draw No Bet win probabilities and fair odds.

    Returns:
        (p_dnb_home, fair_dnb_home, p_dnb_away, fair_dnb_away)
    """
    total_non_draw = p_home + p_away
    if total_non_draw <= 0.001:
        return 0.5, 2.0, 0.5, 2.0

    p_dnb_h = p_home / total_non_draw
    p_dnb_a = p_away / total_non_draw

    fair_dnb_h = round(1.0 / p_dnb_h, 2) if p_dnb_h > 0.01 else 99.0
    fair_dnb_a = round(1.0 / p_dnb_a, 2) if p_dnb_a > 0.01 else 99.0

    return round(p_dnb_h, 4), fair_dnb_h, round(p_dnb_a, 4), fair_dnb_a


def calculate_double_chance_probabilities(
    p_home: float,
    p_draw: float,
    p_away: float,
) -> dict[str, tuple[float, float]]:
    """Calculate Double Chance probabilities and fair odds.

    Returns:
        {"1X": (prob, fair_odd), "X2": (prob, fair_odd), "12": (prob, fair_odd)}
    """
    p_1x = min(0.99, p_home + p_draw)
    p_x2 = min(0.99, p_draw + p_away)
    p_12 = min(0.99, p_home + p_away)

    return {
        "1X": (round(p_1x, 4), round(1.0 / p_1x, 2) if p_1x > 0.01 else 99.0),
        "X2": (round(p_x2, 4), round(1.0 / p_x2, 2) if p_x2 > 0.01 else 99.0),
        "12": (round(p_12, 4), round(1.0 / p_12, 2) if p_12 > 0.01 else 99.0),
    }


def evaluate_safety_markets(
    fixture_name: str,
    league: str,
    odds_1x2: tuple[float, float, float],
    shin_probs: tuple[float, float, float] | None = None,
    nesine_dc: dict[str, float] | None = None,
    nesine_dnb: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate DNB and Double Chance selections for high hit-rate capital protection."""
    candidates: list[dict[str, Any]] = []

    # Use Shin probabilities if provided, otherwise devig 1X2
    if shin_probs and len(shin_probs) == 3:
        p_h, p_x, p_a = shin_probs
    else:
        inv_1 = 1.0 / odds_1x2[0]
        inv_x = 1.0 / odds_1x2[1]
        inv_2 = 1.0 / odds_1x2[2]
        tot = inv_1 + inv_x + inv_2
        p_h, p_x, p_a = inv_1 / tot, inv_x / tot, inv_2 / tot

    # 1. Double Chance Evaluation (High Win Rate >70%)
    dc_data = calculate_double_chance_probabilities(p_h, p_x, p_a)
    for dc_type, (prob, fair_odd) in dc_data.items():
        book_odd = nesine_dc.get(dc_type) if nesine_dc else None
        # Derive synthetic fair bookmaker odds if market not explicitly posted
        if not book_odd:
            # Synthetic 1X odds in Nesine roughly = 1 / (1/h + 1/x)
            if dc_type == "1X":
                book_odd = round(1.0 / ((1.0 / odds_1x2[0]) + (1.0 / odds_1x2[1])), 2)
            elif dc_type == "X2":
                book_odd = round(1.0 / ((1.0 / odds_1x2[1]) + (1.0 / odds_1x2[2])), 2)
            elif dc_type == "12":
                book_odd = round(1.0 / ((1.0 / odds_1x2[0]) + (1.0 / odds_1x2[2])), 2)

        edge_pct = round(((book_odd / fair_odd) - 1.0) * 100, 2) if book_odd else 0.0

        # High probability threshold (>72% win probability)
        if prob >= 0.72 and book_odd and book_odd >= 1.15:
            candidates.append({
                "match": fixture_name,
                "league": league,
                "market": "Çifte Şans",
                "selection": f"ÇŞ {dc_type}",
                "odds": book_odd,
                "fair_odds": fair_odd,
                "prob": prob,
                "edge_pct": edge_pct,
                "safety_tier": "YÜKSEK İSABET (Kasa Koruma)",
                "logic": f"Kazanma olasılığı %{prob*100:.1f}, beraberlik korumalı @ {book_odd:.2f}.",
            })

    # 2. Draw No Bet Evaluation (Void on Draw)
    p_dnb_h, fair_dnb_h, p_dnb_a, fair_dnb_a = calculate_dnb_probabilities(p_h, p_x, p_a)

    book_dnb_h = nesine_dnb[0] if nesine_dnb else round(odds_1x2[0] * (1.0 - (1.0 / odds_1x2[1])), 2)
    book_dnb_a = nesine_dnb[1] if nesine_dnb else round(odds_1x2[2] * (1.0 - (1.0 / odds_1x2[1])), 2)

    if p_dnb_h >= 0.65 and book_dnb_h >= 1.25:
        edge_h = round(((book_dnb_h / fair_dnb_h) - 1.0) * 100, 2)
        candidates.append({
            "match": fixture_name,
            "league": league,
            "market": "Beraberlikte İade",
            "selection": "DNB 1 (Beraberlikte İade 1)",
            "odds": book_dnb_h,
            "fair_odds": fair_dnb_h,
            "prob": p_dnb_h,
            "edge_pct": edge_h,
            "safety_tier": "ORTA-YÜKSEK İSABET (Beraberlik İade)",
            "logic": f"Beraberlikte para iadeli, net galibiyet olasılığı %{p_dnb_h*100:.1f} @ {book_dnb_h:.2f}.",
        })

    if p_dnb_a >= 0.65 and book_dnb_a >= 1.25:
        edge_a = round(((book_dnb_a / fair_dnb_a) - 1.0) * 100, 2)
        candidates.append({
            "match": fixture_name,
            "league": league,
            "market": "Beraberlikte İade",
            "selection": "DNB 2 (Beraberlikte İade 2)",
            "odds": book_dnb_a,
            "fair_odds": fair_dnb_a,
            "prob": p_dnb_a,
            "edge_pct": edge_a,
            "safety_tier": "ORTA-YÜKSEK İSABET (Beraberlik İade)",
            "logic": f"Beraberlikte para iadeli, net galibiyet olasılığı %{p_dnb_a*100:.1f} @ {book_dnb_a:.2f}.",
        })

    return candidates

