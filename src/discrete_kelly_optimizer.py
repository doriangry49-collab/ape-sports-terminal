"""Discrete Finite-State Kelly & Ruin-Bound Optimizer (v1.0).

Tailored specifically for micro-bankrolls with fixed minimum ticket costs (e.g. 50 TL
minimum on Nesine). Eliminates unrealistic fractional Kelly bets by solving the exact
discrete allocation maximizing log utility E[ln(W)] while bounding 2-step probability
of ruin under 10%.
"""

from __future__ import annotations

import math
from typing import Any


def calculate_two_step_ruin_prob(p_win_1: float, p_win_2: float) -> float:
    """Exact probability of consecutive losses destroying a 2-ticket reserve."""
    p_loss_1 = max(0.0, min(1.0, 1.0 - p_win_1))
    p_loss_2 = max(0.0, min(1.0, 1.0 - p_win_2))
    return round(p_loss_1 * p_loss_2, 4)


def evaluate_ticket_trajectory(
    current_bankroll: float,
    ticket_cost: float,
    win_prob: float,
    odds: float,
) -> dict[str, Any]:
    """Simulate single discrete ticket outcome on bankroll and safety reserve."""
    if current_bankroll < ticket_cost:
        return {
            "feasible": False,
            "error": f"Insufficient bankroll ({current_bankroll:.2f} TL < {ticket_cost:.2f} TL)",
        }

    p = max(0.0, min(1.0, win_prob))
    ev_tl = (p * ticket_cost * odds) - ticket_cost
    roi_pct = (ev_tl / ticket_cost) * 100.0 if ticket_cost > 0 else 0.0

    bankroll_on_win = round(current_bankroll - ticket_cost + (ticket_cost * odds), 2)
    bankroll_on_loss = round(current_bankroll - ticket_cost, 2)
    reserve_tickets_left = int(bankroll_on_loss // ticket_cost)

    # Expected log utility growth
    growth_rate = (
        (p * math.log(max(0.01, bankroll_on_win)))
        + ((1.0 - p) * math.log(max(0.01, bankroll_on_loss)))
    ) - math.log(current_bankroll)

    return {
        "feasible": True,
        "stake": ticket_cost,
        "odds": odds,
        "win_prob": p,
        "ev_tl": round(ev_tl, 2),
        "roi_pct": round(roi_pct, 2),
        "bankroll_on_win": bankroll_on_win,
        "bankroll_on_loss": bankroll_on_loss,
        "reserve_tickets_left": reserve_tickets_left,
        "expected_log_growth": round(growth_rate, 4),
        "is_bankroll_protected": reserve_tickets_left >= 1,
    }


class DiscreteKellyOptimizer:
    """Discrete Optimizer for constrained bankroll growth and risk control."""

    def __init__(
        self,
        max_ruin_tolerance: float = 0.10,
        default_backup_prob: float = 0.72,
        max_allocation_cap: float = 0.05,
    ) -> None:
        self.max_ruin_tolerance = max_ruin_tolerance
        self.default_backup_prob = default_backup_prob
        self.max_allocation_cap = max_allocation_cap

    def compute_fractional_kelly_stake(
        self,
        current_bankroll: float,
        win_prob: float,
        odds: float,
        min_ticket_cost: float = 50.0,
        kelly_fraction: float = 0.25,
        max_allocation_pct: float | None = None,
        min_ev_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Compute optimal ticket stake enforcing fractional Kelly bounds and ruin controls.

        Rules:
        - If EV% < min_ev_pct or EV <= 0: stake = 0.0 (unviable)
        - Macro regime (bankroll * cap >= min_ticket_cost): stake strictly capped to <= 5% of bankroll
        - Micro regime (bankroll < min_ticket_cost / cap): stake bounded to min_ticket_cost if protected
        """
        cap = max_allocation_pct if max_allocation_pct is not None else self.max_allocation_cap
        p = max(0.0, min(1.0, float(win_prob)))
        o = max(1.0, float(odds))
        b = o - 1.0

        ev = (p * o) - 1.0
        ev_pct = round(ev * 100.0, 2)

        # 1. EV Check
        if ev_pct < min_ev_pct or ev <= 0.0 or b <= 0.0:
            return {
                "stake": 0.0,
                "is_viable": False,
                "reason": f"Expected value ({ev_pct}%) below threshold ({min_ev_pct}%)",
                "ev_pct": ev_pct,
                "full_kelly_f": 0.0,
                "fractional_f": 0.0,
                "regime": "REJECTED",
                "remaining_bankroll": current_bankroll,
            }

        # 2. Continuous Kelly Fraction
        f_star = ev / b
        f_frac = max(0.0, f_star * kelly_fraction)
        f_capped = min(cap, f_frac)

        # 3. Dual-Regime Sizing
        macro_threshold = min_ticket_cost / max(0.001, cap)
        if current_bankroll >= macro_threshold:
            regime = "MACRO"
            raw_target = current_bankroll * f_capped
            max_allowed = current_bankroll * cap
            # Ensure at least min_ticket_cost and strictly <= max_allowed
            stake = max(min_ticket_cost, min(max_allowed, round(raw_target, 0)))
        else:
            regime = "MICRO"
            if current_bankroll < min_ticket_cost:
                return {
                    "stake": 0.0,
                    "is_viable": False,
                    "reason": f"Insufficient bankroll ({current_bankroll} TL < {min_ticket_cost} TL)",
                    "ev_pct": ev_pct,
                    "full_kelly_f": round(f_star, 4),
                    "fractional_f": round(f_frac, 4),
                    "regime": regime,
                    "remaining_bankroll": current_bankroll,
                }
            stake = min_ticket_cost

        remaining = round(current_bankroll - stake, 2)
        ruin_prob = calculate_two_step_ruin_prob(p, self.default_backup_prob)
        is_protected = (remaining // min_ticket_cost) >= 1

        return {
            "stake": round(stake, 2),
            "is_viable": True,
            "ev_pct": ev_pct,
            "full_kelly_f": round(f_star, 4),
            "fractional_f": round(f_frac, 4),
            "capped_f": round(f_capped, 4),
            "regime": regime,
            "remaining_bankroll": remaining,
            "ruin_prob": ruin_prob,
            "is_bankroll_protected": is_protected,
            "potential_return": round(stake * o, 2),
            "net_profit": round((stake * o) - stake, 2),
        }

    def select_optimal_ticket(
        self,
        current_bankroll: float,
        min_ticket_cost: float,
        candidate_tickets: list[dict[str, Any]],
        backup_prob: float | None = None,
    ) -> dict[str, Any]:
        """Rank candidate tickets by log utility subject to strict ruin bounding."""
        feasible_plans = []
        b_prob = backup_prob if backup_prob is not None else self.default_backup_prob

        for cand in candidate_tickets:
            p = float(cand.get("prob", 0.0) or cand.get("combined_prob", 0.0))
            o = float(cand.get("odds", 1.0) or cand.get("combined_odds", 1.0))
            name = cand.get("name", "Unnamed Ticket")

            # 2-step compound ruin if played with a conservative backup
            ruin_prob = calculate_two_step_ruin_prob(p, b_prob)

            traj = evaluate_ticket_trajectory(
                current_bankroll=current_bankroll,
                ticket_cost=min_ticket_cost,
                win_prob=p,
                odds=o,
            )

            if traj.get("feasible"):
                meets_ruin_bound = ruin_prob <= self.max_ruin_tolerance
                feasible_plans.append({
                    "ticket_name": name,
                    "details": cand,
                    "trajectory": traj,
                    "compound_ruin_prob": ruin_prob,
                    "ruin_bound_passed": meets_ruin_bound,
                    "utility_score": round(traj["expected_log_growth"] * 100.0, 3),
                })

        # Sort: first by passing ruin bound, then by expected log utility growth
        feasible_plans.sort(
            key=lambda x: (x["ruin_bound_passed"], x["utility_score"]),
            reverse=True,
        )

        recommended = feasible_plans[0] if feasible_plans else None

        return {
            "current_bankroll": current_bankroll,
            "min_ticket_cost": min_ticket_cost,
            "max_affordable_tickets": int(current_bankroll // min_ticket_cost),
            "recommended_plan": recommended,
            "all_evaluated_plans": feasible_plans,
        }
