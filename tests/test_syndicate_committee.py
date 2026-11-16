"""Test Suite for APE Syndicate Committee and Priority Agent Roster."""
from syndicate.committee import SyndicateCommittee


def test_syndicate_roster_priority_order():
    committee = SyndicateCommittee()
    roster = committee.roster_summary()
    assert len(roster) == 5

    # Enforce priority sequence
    priorities = [r["priority_level"] for r in roster]
    assert priorities == sorted(priorities)
    assert roster[0]["name"] == "Risk Actuary"
    assert roster[0]["priority_tier"] == "P0_SAFETY_AND_RISK"


def test_risk_actuary_veto_on_negative_ev_trap():
    committee = SyndicateCommittee()
    trap_signal = {
        "home": "Twente",
        "away": "Pafos",
        "market": "İY/MS",
        "outcome": "İY/MS X/X",
        "soft_odds": 11.30,
        "stake": 50.0,
    }
    review = committee.review_signal(trap_signal)
    assert review["approved"] is False
    assert review["final_tier"] == "REJECTED"
    assert "negative-EV variance trap" in review["veto_reason"]


def test_risk_actuary_veto_on_spec0015_stake():
    committee = SyndicateCommittee()
    low_stake_signal = {
        "home": "Derby",
        "away": "Bolton",
        "market": "Çifte Şans",
        "outcome": "1X",
        "soft_odds": 1.50,
        "stake": 25.0,  # Below 50 TL minimum
    }
    review = committee.review_signal(low_stake_signal)
    assert review["approved"] is False
    assert "SPEC-0015 Violation" in review["veto_reason"]


def test_consensus_approval_on_pillar1_corner():
    committee = SyndicateCommittee()
    pillar1_signal = {
        "home": "Palmeiras SP",
        "away": "Clube do Remo",
        "market": "Korner 8.5",
        "selection": "Korner 8.5 ÜST",
        "soft_odds": 1.75,
        "prob": 0.65,
        "shin_fair_prob": 0.65,
        "stake": 50.0,
        "is_steam_confirmed": True,
    }
    review = committee.review_signal(pillar1_signal)
    assert review["approved"] is True
    assert review["final_tier"] == "TIER_1_SHIELD"
    assert review["consensus_score"] >= 0.60


def test_risk_actuary_veto_on_live_momentum_failure():
    """Verify that RiskActuaryAgent vetoes an in-play signal if momentum_eval fails qualification."""
    from sports_engine.models.live_momentum_engine import LiveMomentumEngine

    committee = SyndicateCommittee()
    mom_engine = LiveMomentumEngine()

    # Create a stalled momentum evaluation (6 shots in 65 min)
    stalled_eval = mom_engine.evaluate_momentum(
        elapsed_min=65,
        total_shots=6,
        shots_on_target=1,
        total_corners=2,
    )

    inplay_goal_signal = {
        "home": "Lazio",
        "away": "Roma",
        "market": "CANLI GOL ANOMALİSİ",
        "selection": "3.5 ÜST",
        "soft_odds": 1.95,
        "prob": 0.60,
        "stake": 50.0,
        "momentum_eval": stalled_eval,
    }

    review = committee.review_signal(inplay_goal_signal)
    assert review["approved"] is False
    assert "Live Momentum Veto" in review["veto_reason"]


def test_risk_actuary_veto_on_lineup_rotation():
    committee = SyndicateCommittee()

    class MockLineupImpact:
        is_veto_recommended = True
        veto_reason = "Both teams undergoing heavy squad rotation (High Variance Chaos Trap)."

    fixture = {
        "home": "Man City",
        "away": "Watford",
        "market": "TOPLAM GOL 2.5",
        "selection": "ÜST",
        "stake": 50.0,
        "soft_odds": 1.95,
        "prob": 0.58,
        "lineup_impact": MockLineupImpact(),
    }

    review = committee.review_signal(fixture)
    assert review["approved"] is False
    assert review["final_tier"] == "REJECTED"
    assert "Lineup Rotation Veto" in review["veto_reason"]
