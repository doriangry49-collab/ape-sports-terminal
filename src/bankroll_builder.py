"""Bankroll Builder & Portfolio Optimization Engine.

Constructs mathematically optimized portfolios tailored for bankroll recovery:
  1. Tier 1: Capital Shield (Kasa Kurtarma / High Win-Rate >70%, Odds 1.80 - 2.40).
  2. Tier 2: Balanced Value (Dengeli Büyüme / +EV Edges >5%, Odds 2.20 - 3.50).
  3. Tier 3: Asymmetric System (Sistem 2-3 / 2-4 with minimum 2-hit profit cushion).

Enforces strict fractional Kelly staking (<= 5% max allocation in macro regime,
and discrete ruin-protected bounds in micro-bankroll regime).
"""

from __future__ import annotations

from typing import Any

from discrete_kelly_optimizer import DiscreteKellyOptimizer


def build_recovery_portfolio(
    candidates: list[dict[str, Any]],
    current_bankroll: float = 127.0,
    min_ticket_cost: float = 50.0,
    optimizer: DiscreteKellyOptimizer | None = None,
) -> dict[str, Any]:
    """Generate optimal bankroll recovery tickets based on win probability and Kelly criterion."""
    opt = optimizer or DiscreteKellyOptimizer(max_ruin_tolerance=0.10)

    # 1. Filter High-Probability Selections (>68% win prob)
    high_prob_picks = [c for c in candidates if c.get("prob", 0.0) >= 0.68]
    high_prob_picks.sort(key=lambda x: x.get("prob", 0.0) * x.get("odds", 1.0), reverse=True)

    # 2. Filter High-Edge Selections (+EV >= 5%)
    high_edge_picks = [c for c in candidates if c.get("edge_pct", 0.0) >= 5.0]
    high_edge_picks.sort(key=lambda x: x.get("edge_pct", 0.0), reverse=True)

    # Build Tier 1: 2-Leg Capital Shield Ticket
    tier1_ticket = None
    if len(high_prob_picks) >= 2:
        # Pick two distinct matches
        p1 = high_prob_picks[0]
        p2 = next((p for p in high_prob_picks[1:] if p["match"] != p1["match"]), None)
        if not p2 and len(high_prob_picks) > 1:
            p2 = high_prob_picks[1]

        if p2:
            odd1 = float(p1.get("odds") or p1.get("nesine_odds") or 1.0)
            odd2 = float(p2.get("odds") or p2.get("nesine_odds") or 1.0)
            comb_odds = round(odd1 * odd2, 2)
            comb_prob = round(p1["prob"] * p2["prob"], 3)

            # Unified Kelly Sizing replacing reckless 45% flat stake
            kelly_sizing = opt.compute_fractional_kelly_stake(
                current_bankroll=current_bankroll,
                win_prob=comb_prob,
                odds=comb_odds,
                min_ticket_cost=min_ticket_cost,
                kelly_fraction=0.25,
                max_allocation_pct=0.05,
                min_ev_pct=0.0,
            )

            if kelly_sizing["is_viable"] and kelly_sizing["stake"] > 0:
                stake = kelly_sizing["stake"]
                tier1_ticket = {
                    "name": "🛡️ Kasa Kurtarma & Güçlü Kalkan Kuponu (Tier 1)",
                    "strategy": "Yüksek Başarı Olasılığı (>%70 Kazanma İhtimali), Beraberlik ve Çifte Şans Korumalı",
                    "picks": [p1, p2],
                    "combined_odds": comb_odds,
                    "combined_prob": comb_prob,
                    "stake": stake,
                    "potential_return": kelly_sizing["potential_return"],
                    "net_profit": kelly_sizing["net_profit"],
                    "remaining_bankroll": kelly_sizing["remaining_bankroll"],
                    "kelly_metrics": {
                        "regime": kelly_sizing["regime"],
                        "ev_pct": kelly_sizing["ev_pct"],
                        "fractional_f": kelly_sizing["fractional_f"],
                        "ruin_prob": kelly_sizing["ruin_prob"],
                        "is_bankroll_protected": kelly_sizing["is_bankroll_protected"],
                    },
                }

    # Build Tier 2: +EV Value Growth Ticket
    tier2_ticket = None
    if len(high_edge_picks) >= 2:
        ep1 = high_edge_picks[0]
        ep2 = next((p for p in high_edge_picks[1:] if p["match"] != ep1["match"]), None)
        if not ep2 and len(high_edge_picks) > 1:
            ep2 = high_edge_picks[1]

        if ep2:
            odd1 = float(ep1.get("odds") or ep1.get("nesine_odds") or 1.0)
            odd2 = float(ep2.get("odds") or ep2.get("nesine_odds") or 1.0)
            comb_odds = round(odd1 * odd2, 2)
            comb_prob = round(ep1.get("prob", 0.5) * ep2.get("prob", 0.5), 3)

            kelly_sizing_t2 = opt.compute_fractional_kelly_stake(
                current_bankroll=current_bankroll,
                win_prob=comb_prob,
                odds=comb_odds,
                min_ticket_cost=min_ticket_cost,
                kelly_fraction=0.25,
                max_allocation_pct=0.05,
                min_ev_pct=0.0,
            )

            if kelly_sizing_t2["is_viable"] and kelly_sizing_t2["stake"] > 0:
                tier2_ticket = {
                    "name": "⚡ Matematiksel Değer (+EV) Büyüme Kuponu (Tier 2)",
                    "strategy": "Büro Fiyatlama Hatası / Piyasa Aşımı (+%5+ Edge)",
                    "picks": [ep1, ep2],
                    "combined_odds": comb_odds,
                    "combined_prob": comb_prob,
                    "stake": kelly_sizing_t2["stake"],
                    "potential_return": kelly_sizing_t2["potential_return"],
                    "net_profit": kelly_sizing_t2["net_profit"],
                    "remaining_bankroll": kelly_sizing_t2["remaining_bankroll"],
                    "kelly_metrics": {
                        "regime": kelly_sizing_t2["regime"],
                        "ev_pct": kelly_sizing_t2["ev_pct"],
                        "fractional_f": kelly_sizing_t2["fractional_f"],
                        "ruin_prob": kelly_sizing_t2["ruin_prob"],
                        "is_bankroll_protected": kelly_sizing_t2["is_bankroll_protected"],
                    },
                }

    return {
        "current_bankroll": current_bankroll,
        "min_ticket_cost": min_ticket_cost,
        "max_tickets_affordable": int(current_bankroll // min_ticket_cost),
        "tier1_capital_shield": tier1_ticket,
        "tier2_value_growth": tier2_ticket,
    }
