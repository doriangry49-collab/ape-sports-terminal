"""Unit tests for Bankroll Builder & Recovery Engine."""

from bankroll_builder import build_recovery_portfolio


def test_build_recovery_portfolio():
    candidates = [
        {"match": "Match A", "market": "ÇŞ 1X", "odds": 1.35, "prob": 0.78, "edge_pct": 3.0},
        {"match": "Match B", "market": "DNB 1", "odds": 1.45, "prob": 0.72, "edge_pct": 6.5},
        {"match": "Match C", "market": "Korner 9.5 Üst", "odds": 1.90, "prob": 0.58, "edge_pct": 8.0},
    ]

    port = build_recovery_portfolio(
        candidates=candidates,
        current_bankroll=127.0,
        min_ticket_cost=50.0,
    )

    assert port["current_bankroll"] == 127.0
    assert port["max_tickets_affordable"] == 2
    assert port["tier1_capital_shield"] is not None

    t1 = port["tier1_capital_shield"]
    assert len(t1["picks"]) == 2
    assert t1["combined_prob"] > 0.50
    assert t1["stake"] >= 50.0
    assert t1["potential_return"] > t1["stake"]
    assert t1["remaining_bankroll"] >= 50.0  # Leaves at least 1 backup ticket

