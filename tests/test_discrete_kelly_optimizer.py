"""Unit tests for Discrete Finite-State Kelly & Ruin-Bound Optimizer."""

from discrete_kelly_optimizer import (
    DiscreteKellyOptimizer,
    calculate_two_step_ruin_prob,
    evaluate_ticket_trajectory,
)


def test_calculate_two_step_ruin_prob():
    # If both bets have 70% win probability, ruin = 0.3 * 0.3 = 0.09 (9%)
    ruin = calculate_two_step_ruin_prob(0.70, 0.70)
    assert abs(ruin - 0.09) < 1e-4

    # If first bet has 20% win probability, ruin = 0.8 * 0.3 = 0.24 (24%)
    ruin_lottery = calculate_two_step_ruin_prob(0.20, 0.70)
    assert abs(ruin_lottery - 0.24) < 1e-4


def test_evaluate_ticket_trajectory():
    res = evaluate_ticket_trajectory(
        current_bankroll=127.19,
        ticket_cost=50.0,
        win_prob=0.75,
        odds=2.0,
    )

    assert res["feasible"] is True
    assert res["bankroll_on_win"] == 177.19
    assert res["bankroll_on_loss"] == 77.19
    assert res["reserve_tickets_left"] == 1
    assert res["is_bankroll_protected"] is True
    assert res["ev_tl"] == 25.0  # (0.75 * 50 * 2.0) - 50 = 25 TL
    assert res["roi_pct"] == 50.0


def test_evaluate_insufficient_bankroll():
    res = evaluate_ticket_trajectory(
        current_bankroll=45.0,
        ticket_cost=50.0,
        win_prob=0.80,
        odds=1.5,
    )
    assert res["feasible"] is False


def test_discrete_kelly_optimizer_selects_shield_over_ruin():
    opt = DiscreteKellyOptimizer(max_ruin_tolerance=0.10)
    bankroll = 127.19
    ticket_cost = 50.0

    candidates = [
        {
            "name": "High-Variance Longshot",
            "prob": 0.25,
            "odds": 6.0,
        },
        {
            "name": "Tier 1 Capital Shield",
            "prob": 0.76,
            "odds": 1.95,
        },
    ]

    res = opt.select_optimal_ticket(bankroll, ticket_cost, candidates)
    assert res["max_affordable_tickets"] == 2
    rec = res["recommended_plan"]
    assert rec is not None
    # High-variance longshot should fail ruin bound (0.75 * 0.28 = 0.21 > 0.10)
    # Tier 1 should pass and be chosen
    assert rec["ticket_name"] == "Tier 1 Capital Shield"
    assert rec["ruin_bound_passed"] is True

