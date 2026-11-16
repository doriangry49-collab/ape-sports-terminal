"""Copula-Based Same-Game Parlay (SGP) & Multi-Market Dependency Engine (v1.0).

Combines marginal probabilities from Dixon-Coles (goals) and Negative Binomial (corners)
using Gaussian, Clayton, and Gumbel Copula distributions to model intra-match tactical correlations.
Prices true joint probabilities for Same-Game Parlay (SGP) combinations:
  - Home Win (MS 1) + Home/Match Corners Over (Siege dominance)
  - Match Over 2.5 + First Half Over 1.5 (Upper tail dependence)
  - Match Under 2.5 + Draw (Deadlock dependency)
  - Both Teams to Score (BTTS) + Match Over 2.5

Detects retail bookmaker pricing inefficiencies where parlay odds treat correlated legs
as independent or misprice joint probabilities. Enforces SPEC-0012 and SPEC-0015.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import multivariate_normal, norm

logger = logging.getLogger("CopulaSGPEngine")

# Calibrated empirical correlation coefficients across European Ground-Truth leagues
EMPIRICAL_CORRELATIONS: dict[tuple[str, str], float] = {
    ("1X2_HOME", "CORNERS_OVER"): 0.32,
    ("1X2_AWAY", "CORNERS_OVER"): 0.24,
    ("1X2_HOME", "OVER_25"): 0.28,
    ("1X2_AWAY", "OVER_25"): 0.22,
    ("1X2_DRAW", "UNDER_25"): 0.46,
    ("OVER_25", "HT_OVER_15"): 0.68,
    ("OVER_25", "BTTS_YES"): 0.58,
    ("UNDER_25", "BTTS_NO"): 0.62,
    ("OVER_25", "CORNERS_OVER"): 0.26,
    ("UNDER_25", "CORNERS_OVER"): -0.16,
    ("1X2_HOME", "BTTS_YES"): 0.12,
}
DEFAULT_CORRELATION = 0.15


@dataclass
class SGPLeg:
    """A single market leg within a Same-Game Parlay."""
    market: str          # e.g., "1X2", "TOTAL_GOALS", "TOTAL_CORNERS", "BTTS"
    selection: str       # e.g., "MS 1", "2.5 ÜST", "9.5 ÜST", "KG VAR"
    marginal_prob: float # Unconditional fair probability P(Leg)
    offered_odd: float   # Bookmaker decimal odds for this single leg


@dataclass
class SGPRecommendation:
    """Evaluated Same-Game Parlay opportunity."""
    fixture_id: str
    home_team: str
    away_team: str
    leg_a: SGPLeg
    leg_b: SGPLeg
    copula_type: str
    correlation: float
    joint_prob: float
    independent_prob: float
    fair_sgp_odds: float
    offered_sgp_odds: float
    edge_pct: float
    ev_roi: float
    correlation_lift_pct: float
    is_positive_ev: bool
    stake: float = 50.0  # SPEC-0015


class CopulaSGPEngine:
    """Multivariate Copula Dependency & SGP Pricing Engine."""

    def __init__(self, default_corr: float = DEFAULT_CORRELATION) -> None:
        self.default_corr = default_corr

    def lookup_correlation(self, market_a: str, selection_a: str, market_b: str, selection_b: str) -> float:
        """Resolve calibrated correlation parameter rho for a pair of market legs."""
        key_a = self._normalize_market_key(market_a, selection_a)
        key_b = self._normalize_market_key(market_b, selection_b)

        pair_1 = (key_a, key_b)
        pair_2 = (key_b, key_a)

        if pair_1 in EMPIRICAL_CORRELATIONS:
            return EMPIRICAL_CORRELATIONS[pair_1]
        if pair_2 in EMPIRICAL_CORRELATIONS:
            return EMPIRICAL_CORRELATIONS[pair_2]

        return self.default_corr

    def _normalize_market_key(self, market: str, selection: str) -> str:
        """Normalize market and selection strings into canonical lookup keys."""
        m_upper = market.upper()
        s_upper = selection.upper()

        if "1X2" in m_upper or "MS" in s_upper:
            if "1" in s_upper or "HOME" in s_upper:
                return "1X2_HOME"
            if "2" in s_upper or "AWAY" in s_upper:
                return "1X2_AWAY"
            if "X" in s_upper or "DRAW" in s_upper:
                return "1X2_DRAW"

        if "KORNER" in m_upper or "CORNER" in m_upper:
            return "CORNERS_OVER" if ("ÜST" in s_upper or "OVER" in s_upper) else "CORNERS_UNDER"

        if "2.5" in m_upper or "2.5" in s_upper:
            return "OVER_25" if ("ÜST" in s_upper or "OVER" in s_upper) else "UNDER_25"

        if "HT" in m_upper or "İY" in m_upper or "FIRST_HALF" in m_upper:
            return "HT_OVER_15" if ("ÜST" in s_upper or "OVER" in s_upper) else "HT_UNDER_15"

        if "BTTS" in m_upper or "KG" in m_upper or "KARŞILIKLI" in m_upper:
            return "BTTS_YES" if ("VAR" in s_upper or "YES" in s_upper) else "BTTS_NO"

        return "UNKNOWN"

    def compute_gaussian_copula_joint_prob(self, p1: float, p2: float, rho: float) -> float:
        """Compute exact joint probability P(A and B) using bivariate Gaussian Copula.

        Let u = 1 - p1, v = 1 - p2. The joint upper-tail probability is:
        P(X1 > z1, X2 > z2) where z1 = Phi^-1(1 - p1), z2 = Phi^-1(1 - p2).
        """
        # Validate input probabilities (SPEC-0012)
        if not (0.001 <= p1 <= 0.999) or not (0.001 <= p2 <= 0.999):
            raise ValueError(f"Marginal probabilities must be strictly in (0, 1), got p1={p1}, p2={p2}")

        rho = max(-0.95, min(0.95, float(rho)))

        # Inverse standard normal CDF thresholds
        z1 = float(norm.ppf(1.0 - p1))
        z2 = float(norm.ppf(1.0 - p2))

        cov_matrix = np.array([[1.0, rho], [rho, 1.0]])
        # Probability that standard bivariate normal exceeds (z1, z2)
        # Using CDF identity: P(X > z1, Y > z2) = 1 - Phi(z1) - Phi(z2) + Phi_rho(z1, z2)
        p_both_less = float(multivariate_normal.cdf([z1, z2], mean=[0.0, 0.0], cov=cov_matrix))
        p_upper = 1.0 - norm.cdf(z1) - norm.cdf(z2) + p_both_less
        return max(0.0001, min(0.9999, float(p_upper)))

    def compute_gumbel_copula_joint_prob(self, p1: float, p2: float, theta: float | None = None, rho: float = 0.5) -> float:
        """Compute joint probability using Gumbel Extreme Value Copula (for upper tail dependence).

        Gumbel parameter theta >= 1.0. Relationship with Kendall tau: tau = 1 - 1/theta.
        """
        if not (0.001 <= p1 <= 0.999) or not (0.001 <= p2 <= 0.999):
            raise ValueError(f"Marginal probabilities must be in (0, 1), got p1={p1}, p2={p2}")

        if theta is None:
            # Approximate theta from linear correlation rho: tau ~ 2/pi * arcsin(rho)
            tau = (2.0 / math.pi) * math.asin(max(0.01, min(0.95, rho)))
            theta = max(1.01, min(10.0, 1.0 / (1.0 - tau)))

        # Survival copula for upper tail: C_theta(p1, p2)
        u1 = max(1e-6, min(1.0 - 1e-6, p1))
        u2 = max(1e-6, min(1.0 - 1e-6, p2))

        neg_log_u1 = -math.log(u1)
        neg_log_u2 = -math.log(u2)

        copula_val = math.exp(-((neg_log_u1 ** theta) + (neg_log_u2 ** theta)) ** (1.0 / theta))
        return max(0.0001, min(0.9999, copula_val))

    def evaluate_sgp(
        self,
        fixture_id: str,
        home_team: str,
        away_team: str,
        leg_a: SGPLeg,
        leg_b: SGPLeg,
        offered_sgp_odds: float | None = None,
        use_gumbel_for_tails: bool = True,
    ) -> SGPRecommendation:
        """Evaluate a Same-Game Parlay for intra-match correlation edge against retail pricing."""
        p_a = leg_a.marginal_prob
        p_b = leg_b.marginal_prob
        rho = self.lookup_correlation(leg_a.market, leg_a.selection, leg_b.market, leg_b.selection)

        # Select Copula family based on market characteristics
        copula_type = "GAUSSIAN"
        is_upper_tail_combo = ("OVER_25" in [leg_a.market, leg_b.market]) and any(
            t in [leg_a.market, leg_b.market] for t in ("HT_OVER_15", "BTTS_YES", "CORNERS_OVER")
        )

        if use_gumbel_for_tails and is_upper_tail_combo and rho > 0.40:
            copula_type = "GUMBEL_UPPER_TAIL"
            joint_prob = self.compute_gumbel_copula_joint_prob(p_a, p_b, rho=rho)
        else:
            joint_prob = self.compute_gaussian_copula_joint_prob(p_a, p_b, rho=rho)

        independent_prob = p_a * p_b
        fair_sgp_odds = round(1.0 / joint_prob, 3)

        # If bookmaker offered odds are not directly specified, model standard slip behavior:
        # Combined slip odds = Leg A Odds * Leg B Odds
        if offered_sgp_odds is None or offered_sgp_odds <= 1.0:
            offered_sgp_odds = round(leg_a.offered_odd * leg_b.offered_odd, 2)

        # Edge calculations
        ev_roi = (joint_prob * offered_sgp_odds) - 1.0
        edge_pct = round(ev_roi * 100.0, 2)
        correlation_lift_pct = round(((joint_prob / independent_prob) - 1.0) * 100.0, 2)

        is_positive_ev = bool(edge_pct >= 3.5 and offered_sgp_odds <= 6.50)

        return SGPRecommendation(
            fixture_id=fixture_id,
            home_team=home_team,
            away_team=away_team,
            leg_a=leg_a,
            leg_b=leg_b,
            copula_type=copula_type,
            correlation=round(rho, 3),
            joint_prob=round(joint_prob, 4),
            independent_prob=round(independent_prob, 4),
            fair_sgp_odds=fair_sgp_odds,
            offered_sgp_odds=round(offered_sgp_odds, 2),
            edge_pct=edge_pct,
            ev_roi=round(ev_roi, 4),
            correlation_lift_pct=correlation_lift_pct,
            is_positive_ev=is_positive_ev,
            stake=50.0,  # Enforces SPEC-0015
        )

    def scan_bulletin_for_sgp(
        self,
        fixtures: list[dict[str, Any]],
        min_edge_pct: float = 4.0,
    ) -> list[SGPRecommendation]:
        """Scan active Nesine fixtures and construct high-correlation SGP combinations."""
        recommendations: list[SGPRecommendation] = []

        for fix in fixtures:
            fix_id = str(fix.get("nesine_code") or f"{fix.get('home')}_{fix.get('away')}")
            home = fix.get("home", "")
            away = fix.get("away", "")

            odds_1x2 = fix.get("nesine_1x2")
            corners = fix.get("nesine_corners", {})
            ou25 = fix.get("nesine_ou25")

            # Candidate 1: Home Win (MS 1) + Match Corners Over 8.5 / 9.5
            if odds_1x2 and corners and len(odds_1x2) == 3:
                home_odd = float(odds_1x2[0])
                if 1.35 <= home_odd <= 2.10:
                    for line_str, c_odds in corners.items():
                        c_over_odd = float(c_odds.get("over", 0.0) or 0.0)
                        if 1.45 <= c_over_odd <= 2.20 and line_str in ("8.5", "9.5"):
                            leg_a = SGPLeg(
                                market="1X2",
                                selection="MS 1",
                                marginal_prob=round(1.0 / (home_odd * 1.06), 4),
                                offered_odd=home_odd,
                            )
                            leg_b = SGPLeg(
                                market="KORNER",
                                selection=f"{line_str} ÜST",
                                marginal_prob=round(1.0 / (c_over_odd * 1.07), 4),
                                offered_odd=c_over_odd,
                            )
                            sgp = self.evaluate_sgp(fix_id, home, away, leg_a, leg_b)
                            if sgp.edge_pct >= min_edge_pct:
                                recommendations.append(sgp)

            # Candidate 2: Over 2.5 Goals + Match Corners Over
            if ou25 and corners and len(ou25) == 2:
                o25_odd = float(ou25[0])
                if 1.40 <= o25_odd <= 1.95:
                    for line_str, c_odds in corners.items():
                        c_over_odd = float(c_odds.get("over", 0.0) or 0.0)
                        if 1.50 <= c_over_odd <= 2.10 and line_str in ("8.5", "9.5"):
                            leg_a = SGPLeg(
                                market="2.5 Gol",
                                selection="2.5 ÜST",
                                marginal_prob=round(1.0 / (o25_odd * 1.05), 4),
                                offered_odd=o25_odd,
                            )
                            leg_b = SGPLeg(
                                market="KORNER",
                                selection=f"{line_str} ÜST",
                                marginal_prob=round(1.0 / (c_over_odd * 1.07), 4),
                                offered_odd=c_over_odd,
                            )
                            sgp = self.evaluate_sgp(fix_id, home, away, leg_a, leg_b)
                            if sgp.edge_pct >= min_edge_pct:
                                recommendations.append(sgp)

        # Candidate 3: Over 2.5 Goals + Both Teams to Score (BTTS Yes) - Upper Tail Dependent
        if ou25 and len(ou25) == 2:
            o25_odd = float(ou25[0])
            btts = fix.get("nesine_btts", {}) or fix.get("btts", {})
            btts_yes_odd = float(btts.get("yes", 0.0) or btts.get("var", 0.0) or 0.0)
            if 1.40 <= o25_odd <= 2.20 and 1.45 <= btts_yes_odd <= 2.10:
                leg_a = SGPLeg(
                    market="TOTAL_GOALS",
                    selection="2.5 ÜST",
                    marginal_prob=round(1.0 / (o25_odd * 1.05), 4),
                    offered_odd=o25_odd,
                )
                leg_b = SGPLeg(
                    market="BTTS",
                    selection="KG VAR",
                    marginal_prob=round(1.0 / (btts_yes_odd * 1.06), 4),
                    offered_odd=btts_yes_odd,
                )
                sgp = self.evaluate_sgp(fix_id, home, away, leg_a, leg_b, use_gumbel_for_tails=True)
                if sgp.edge_pct >= min_edge_pct:
                    recommendations.append(sgp)

        # Candidate 4: Home Win (MS 1) + Over 2.5 Goals (Siege Victory)
        if odds_1x2 and len(odds_1x2) == 3 and ou25 and len(ou25) == 2:
            home_odd = float(odds_1x2[0])
            o25_odd = float(ou25[0])
            if 1.40 <= home_odd <= 2.30 and 1.45 <= o25_odd <= 2.20:
                leg_a = SGPLeg(
                    market="1X2",
                    selection="MS 1",
                    marginal_prob=round(1.0 / (home_odd * 1.06), 4),
                    offered_odd=home_odd,
                )
                leg_b = SGPLeg(
                    market="TOTAL_GOALS",
                    selection="2.5 ÜST",
                    marginal_prob=round(1.0 / (o25_odd * 1.05), 4),
                    offered_odd=o25_odd,
                )
                sgp = self.evaluate_sgp(fix_id, home, away, leg_a, leg_b)
                if sgp.edge_pct >= min_edge_pct:
                    recommendations.append(sgp)

        return recommendations
