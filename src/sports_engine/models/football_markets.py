"""Comprehensive Football Market Derivation Engine based on Bivariate Goal Expectancy.

Derives full market suite (1X2, Double Chance, DNB, Over/Under, BTTS, Correct Score,
1H/2H, HT/FT, and Longshots) from unified team goal distribution (lambda_home, lambda_away).
"""

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketSelection:
    """Individual betting market selection outcome."""

    market_type: str
    selection: str
    probability: float
    fair_odds: float
    market_odds: float | None = None
    raw_implied_probability: float | None = None
    probability_gap: float | None = None
    bookmaker: str | None = None
    is_longshot: bool = False
    longshot_tier: str | None = None
    status: str = "UNADJUSTED"


class FootballMarketEngine:
    """Derives complete football betting market distributions from bivariate Poisson parameters."""

    MAX_GOALS = 8

    def __init__(self, lambda_home: float, lambda_away: float):
        self.lambda_home = max(0.05, float(lambda_home))
        self.lambda_away = max(0.05, float(lambda_away))

        # Full match score matrix (8x8)
        self.score_matrix = self._compute_bivariate_poisson(self.lambda_home, self.lambda_away)

        # First half goal expectancies (empirically ~45% of full-time goals)
        self.lambda_1h_home = self.lambda_home * 0.45
        self.lambda_1h_away = self.lambda_away * 0.45
        self.score_matrix_1h = self._compute_bivariate_poisson(self.lambda_1h_home, self.lambda_1h_away)

        # Second half goal expectancies (~55% of full-time goals)
        self.lambda_2h_home = self.lambda_home * 0.55
        self.lambda_2h_away = self.lambda_away * 0.55
        self.score_matrix_2h = self._compute_bivariate_poisson(self.lambda_2h_home, self.lambda_2h_away)

    def _compute_bivariate_poisson(self, l_h: float, l_a: float) -> dict[tuple[int, int], float]:
        """Generate normalized bivariate Poisson probability grid."""
        grid: dict[tuple[int, int], float] = {}
        total_p = 0.0

        for x in range(self.MAX_GOALS + 1):
            p_x = (math.pow(l_h, x) * math.exp(-l_h)) / math.factorial(x)
            for y in range(self.MAX_GOALS + 1):
                p_y = (math.pow(l_a, y) * math.exp(-l_a)) / math.factorial(y)
                p = p_x * p_y
                grid[(x, y)] = p
                total_p += p

        # Normalize
        if total_p > 0:
            for k in grid:
                grid[k] = grid[k] / total_p

        return grid

    def get_1x2_market(self) -> dict[str, float]:
        """Compute Full-Time 1X2 probabilities."""
        p_home = sum(p for (x, y), p in self.score_matrix.items() if x > y)
        p_draw = sum(p for (x, y), p in self.score_matrix.items() if x == y)
        p_away = sum(p for (x, y), p in self.score_matrix.items() if x < y)
        return {
            "HOME": round(p_home, 4),
            "DRAW": round(p_draw, 4),
            "AWAY": round(p_away, 4),
        }

    def get_double_chance(self) -> dict[str, float]:
        """Compute Double Chance market (1X, 12, X2)."""
        m = self.get_1x2_market()
        return {
            "1X": round(m["HOME"] + m["DRAW"], 4),
            "12": round(m["HOME"] + m["AWAY"], 4),
            "X2": round(m["DRAW"] + m["AWAY"], 4),
        }

    def get_draw_no_bet(self) -> dict[str, float]:
        """Compute Draw No Bet market (void if draw)."""
        m = self.get_1x2_market()
        denom = m["HOME"] + m["AWAY"]
        if denom > 0:
            return {
                "HOME": round(m["HOME"] / denom, 4),
                "AWAY": round(m["AWAY"] / denom, 4),
            }
        return {"HOME": 0.5, "AWAY": 0.5}

    def get_totals_market(self, thresholds: list[float] | None = None) -> dict[str, dict[str, float]]:
        """Compute Over/Under total goals for specified lines."""
        if thresholds is None:
            thresholds = [0.5, 1.5, 2.5, 3.5, 4.5]

        totals: dict[str, dict[str, float]] = {}
        for t in thresholds:
            p_under = sum(p for (x, y), p in self.score_matrix.items() if (x + y) < t)
            p_over = max(0.0, 1.0 - p_under)
            totals[f"OVER_UNDER_{t}"] = {
                "OVER": round(p_over, 4),
                "UNDER": round(p_under, 4),
            }
        return totals

    def get_btts_market(self) -> dict[str, float]:
        """Compute Both Teams To Score (BTTS Yes/No)."""
        p_yes = sum(p for (x, y), p in self.score_matrix.items() if x >= 1 and y >= 1)
        p_no = max(0.0, 1.0 - p_yes)
        return {
            "YES": round(p_yes, 4),
            "NO": round(p_no, 4),
        }

    def get_team_totals(self) -> dict[str, dict[str, float]]:
        """Compute individual team totals (Over/Under 1.5)."""
        home_over_1_5 = sum(p for (x, y), p in self.score_matrix.items() if x > 1.5)
        away_over_1_5 = sum(p for (x, y), p in self.score_matrix.items() if y > 1.5)
        return {
            "HOME_TOTALS_1.5": {"OVER": round(home_over_1_5, 4), "UNDER": round(1.0 - home_over_1_5, 4)},
            "AWAY_TOTALS_1.5": {"OVER": round(away_over_1_5, 4), "UNDER": round(1.0 - away_over_1_5, 4)},
        }

    def get_correct_score_distribution(self, top_n: int = 15) -> list[dict[str, Any]]:
        """Return all realistic score probabilities ordered by likelihood."""
        scores = []
        for (x, y), p in self.score_matrix.items():
            fair = round(1.0 / max(p, 0.0001), 2)
            scores.append({
                "score": f"{x}-{y}",
                "home_goals": x,
                "away_goals": y,
                "probability": round(p, 4),
                "fair_odds": fair,
            })
        scores.sort(key=lambda item: item["probability"], reverse=True)
        return scores[:top_n]

    def get_first_half_market(self) -> dict[str, Any]:
        """Compute First Half outcomes (1X2, Over/Under 0.5 & 1.5, Correct Score)."""
        p_1h_home = sum(p for (x, y), p in self.score_matrix_1h.items() if x > y)
        p_1h_draw = sum(p for (x, y), p in self.score_matrix_1h.items() if x == y)
        p_1h_away = sum(p for (x, y), p in self.score_matrix_1h.items() if x < y)

        p_1h_over_0_5 = sum(p for (x, y), p in self.score_matrix_1h.items() if (x + y) > 0.5)
        p_1h_over_1_5 = sum(p for (x, y), p in self.score_matrix_1h.items() if (x + y) > 1.5)

        # 1H Correct Scores
        scores_1h = [
            {"score": f"{x}-{y}", "probability": round(p, 4), "fair_odds": round(1.0 / max(p, 0.0001), 2)}
            for (x, y), p in self.score_matrix_1h.items() if x <= 3 and y <= 3
        ]
        scores_1h.sort(key=lambda s: s["probability"], reverse=True)

        return {
            "1X2": {
                "HOME": round(p_1h_home, 4),
                "DRAW": round(p_1h_draw, 4),
                "AWAY": round(p_1h_away, 4),
            },
            "TOTALS_0.5": {"OVER": round(p_1h_over_0_5, 4), "UNDER": round(1.0 - p_1h_over_0_5, 4)},
            "TOTALS_1.5": {"OVER": round(p_1h_over_1_5, 4), "UNDER": round(1.0 - p_1h_over_1_5, 4)},
            "TOP_SCORES": scores_1h[:5],
        }

    def get_second_half_market(self) -> dict[str, float]:
        """Compute Second Half independent 1X2 outcomes."""
        p_2h_home = sum(p for (x, y), p in self.score_matrix_2h.items() if x > y)
        p_2h_draw = sum(p for (x, y), p in self.score_matrix_2h.items() if x == y)
        p_2h_away = sum(p for (x, y), p in self.score_matrix_2h.items() if x < y)
        return {
            "HOME": round(p_2h_home, 4),
            "DRAW": round(p_2h_draw, 4),
            "AWAY": round(p_2h_away, 4),
        }

    def get_ht_ft_market(self) -> dict[str, dict[str, float]]:
        """Compute joint Half Time / Full Time distribution (9 outcomes)."""
        # Joint calculation combining 1H and 2H independent goal arrival
        outcomes = {
            "1/1": 0.0, "1/X": 0.0, "1/2": 0.0,
            "X/1": 0.0, "X/X": 0.0, "X/2": 0.0,
            "2/1": 0.0, "2/X": 0.0, "2/2": 0.0,
        }

        for (x1, y1), p1 in self.score_matrix_1h.items():
            if x1 > 3 or y1 > 3:
                continue
            ht_res = "1" if x1 > y1 else ("X" if x1 == y1 else "2")
            for (x2, y2), p2 in self.score_matrix_2h.items():
                if x2 > 4 or y2 > 4:
                    continue
                ft_x = x1 + x2
                ft_y = y1 + y2
                ft_res = "1" if ft_x > ft_y else ("X" if ft_x == ft_y else "2")
                combo = f"{ht_res}/{ft_res}"
                outcomes[combo] += p1 * p2

        # Normalize sum to 1.0
        tot = sum(outcomes.values())
        result = {}
        for combo, val in outcomes.items():
            prob = val / tot if tot > 0 else 0.1111
            result[combo] = {
                "probability": round(prob, 4),
                "fair_odds": round(1.0 / max(prob, 0.0001), 2),
            }
        return result

    def scan_longshots(
        self,
        market_odds_map: dict[str, float] | None = None,
        min_odds: float = 3.0,
    ) -> list[MarketSelection]:
        """Scan across all derived markets to extract high-odds / longshot opportunities.

        Classifies into tiers:
        - TIER_1: Odds in [3.0, 5.0)
        - TIER_2: Odds in [5.0, 10.0)
        - TIER_3: Odds in [10.0, 20.0)
        - TIER_4: Odds >= 20.0
        """
        longshots: list[MarketSelection] = []

        def add_candidate(m_type: str, sel: str, prob: float, fair: float, m_odds: float | None = None):
            odds_to_eval = m_odds if m_odds is not None else fair
            if odds_to_eval < min_odds:
                return

            if odds_to_eval >= 20.0:
                tier = "TIER_4 (>= 20.0)"
            elif odds_to_eval >= 10.0:
                tier = "TIER_3 (>= 10.0)"
            elif odds_to_eval >= 5.0:
                tier = "TIER_2 (>= 5.0)"
            else:
                tier = "TIER_1 (>= 3.0)"

            raw_implied = round(1.0 / odds_to_eval, 4) if odds_to_eval > 0 else 0.0
            gap = round(prob - raw_implied, 4) if m_odds is not None else 0.0

            longshots.append(
                MarketSelection(
                    market_type=m_type,
                    selection=sel,
                    probability=round(prob, 4),
                    fair_odds=round(fair, 2),
                    market_odds=round(m_odds, 2) if m_odds else None,
                    raw_implied_probability=raw_implied,
                    probability_gap=gap,
                    bookmaker="Pinnacle/Ref",
                    is_longshot=True,
                    longshot_tier=tier,
                    status="UNADJUSTED",
                )
            )

        # 1. Check 1X2
        m_1x2 = self.get_1x2_market()
        for sel, p in m_1x2.items():
            fair = 1.0 / max(p, 0.0001)
            add_candidate("1X2", sel, p, fair)

        # 2. Check Correct Scores
        scores = self.get_correct_score_distribution(top_n=20)
        for s in scores:
            add_candidate("CORRECT_SCORE", s["score"], s["probability"], s["fair_odds"])

        # 3. Check HT/FT
        ht_ft = self.get_ht_ft_market()
        for combo, data in ht_ft.items():
            add_candidate("HT_FT", combo, data["probability"], data["fair_odds"])

        # 4. Check Over/Under 3.5 & 4.5
        totals = self.get_totals_market([3.5, 4.5])
        for line, t_data in totals.items():
            for o_u, p in t_data.items():
                fair = 1.0 / max(p, 0.0001)
                add_candidate(line, o_u, p, fair)

        # Sort by fair odds ascending
        longshots.sort(key=lambda s: s.fair_odds)
        return longshots

    def get_full_market_suite(self) -> dict[str, Any]:
        """Aggregate full suite of derived football markets."""
        m_1x2 = self.get_1x2_market()
        dc = self.get_double_chance()
        dnb = self.get_draw_no_bet()
        totals = self.get_totals_market([0.5, 1.5, 2.5, 3.5, 4.5])
        btts = self.get_btts_market()
        tt = self.get_team_totals()
        scores = self.get_correct_score_distribution(top_n=10)
        first_half = self.get_first_half_market()
        second_half = self.get_second_half_market()
        ht_ft = self.get_ht_ft_market()
        longshots = [
            {
                "market": ls.market_type,
                "selection": ls.selection,
                "probability": ls.probability,
                "fair_odds": ls.fair_odds,
                "tier": ls.longshot_tier,
                "status": ls.status,
            }
            for ls in self.scan_longshots(min_odds=3.0)[:10]
        ]

        return {
            "expected_goals": {"home": self.lambda_home, "away": self.lambda_away},
            "1x2": m_1x2,
            "double_chance": dc,
            "draw_no_bet": dnb,
            "totals": totals,
            "btts": btts,
            "team_totals": tt,
            "top_correct_scores": scores,
            "first_half": first_half,
            "second_half": second_half,
            "ht_ft": ht_ft,
            "top_longshots": longshots,
        }
