"""Unit tests for Multivariate Portfolio Kelly Optimizer."""
from portfolio_kelly_optimizer import MultivariatePortfolioKelly


def test_portfolio_kelly_allocations_and_drawdown_bounds():
    opt = MultivariatePortfolioKelly(
        default_fraction=0.25,
        max_portfolio_risk_cap=0.35,
        max_drawdown_limit=0.15,
    )
    bankroll = 1000.0

    bets = [
        {"id": "b1", "match": "Torino vs Lecce", "market": "1X2", "selection": "1", "prob": 0.65, "odds": 1.70},
        {"id": "b2", "match": "Bochum vs Karlsruhe", "market": "1X2", "selection": "1", "prob": 0.62, "odds": 1.75},
        {"id": "b3", "match": "Chelsea vs Arsenal", "market": "2.5 Gol", "selection": "ÜST", "prob": 0.58, "odds": 1.90},
    ]

    res = opt.optimize_portfolio_stakes(bankroll, bets, min_stake=50.0)
    assert res["total_staked_tl"] > 0
    assert res["total_staked_tl"] <= bankroll * 0.35
    assert res["remaining_cash_tl"] == bankroll - res["total_staked_tl"]
    assert res["drawdown_bound_passed"] is True
    assert len(res["allocations"]) == 3
    for a in res["allocations"]:
        if a["recommended_stake_tl"] > 0:
            assert a["recommended_stake_tl"] >= 50.0


def test_correlated_bets_intra_match_damping():
    opt = MultivariatePortfolioKelly(default_fraction=0.25)
    bankroll = 1000.0

    # Two bets on the SAME match (correlated): 1X2 and 2.5 Over
    same_match_bets = [
        {"id": "c1", "home": "Stuttgart", "away": "Bremen", "market": "1X2", "prob": 0.65, "odds": 1.65},
        {"id": "c2", "home": "Stuttgart", "away": "Bremen", "market": "2.5 Gol", "prob": 0.65, "odds": 1.65},
    ]
    cov_mat = opt.build_covariance_matrix(same_match_bets)
    assert cov_mat.shape == (2, 2)
    assert cov_mat[0, 1] > 0.0  # Covariance is positive, not zero

    res = opt.optimize_portfolio_stakes(bankroll, same_match_bets, min_stake=50.0)
    assert res["drawdown_bound_passed"] is True

