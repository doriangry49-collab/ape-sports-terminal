"""
Unit tests for GoalAnomalyEngine and GoalAnomalyAgent.
Validates:
1. Pre-match GASI scoring and archetype classification
2. League defense-grind veto (La Liga 2, Ligue 2, Serie B)
3. Under drift veto
4. In-play 88.8% HT Over 1.5 Gold Rule
5. Negative Binomial fat-tail pricing calculations
6. Syndicate GoalAnomalyAgent verdict generation
"""

import pytest
import sys
from pathlib import Path

# Ensure paths
_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from sports_engine.models.goal_anomaly_engine import (
    AnomalyArchetype,
    AnomalySignalTier,
    GoalAnomalyEngine,
    GoalAnomalyResult,
)
from syndicate.agents import GoalAnomalyAgent


@pytest.fixture
def engine():
    return GoalAnomalyEngine()


@pytest.fixture
def agent():
    return GoalAnomalyAgent()


# 1. Hyper Over Magnet (Bundesliga / Open O25 <= 1.32)
def test_hyper_over_magnet(engine):
    fixture = {
        "event_id": "test_bayern_dortmund",
        "home_team": "Bayern Munich",
        "away_team": "Borussia Dortmund",
        "league": "Bundesliga",
        "div_code": "D1",
        "open_1": 1.75,
        "open_2": 3.80,
        "open_o25": 1.28,
        "steam_o25_pct": -2.0,
    }
    res = engine.evaluate_fixture(fixture)
    assert res.tier == AnomalySignalTier.GOLD_TIER
    assert res.archetype == AnomalyArchetype.HYPER_OVER_MAGNET
    assert res.gasi_score >= 80.0
    assert "OVER_3.5" in res.recommended_markets
    assert res.fair_odds_6plus > 1.0
    assert res.p_6plus_negbin > 0.15


# 2. Pure Shootout Archetype (Even Odds, Suppressed Over line)
def test_pure_shootout_archetype(engine):
    fixture = {
        "event_id": "test_shootout",
        "home_team": "Eintracht Frankfurt",
        "away_team": "Bayer Leverkusen",
        "league": "D1",
        "open_1": 2.10,
        "open_2": 2.90,
        "open_o25": 1.44,
        "steam_o25_pct": -1.5,
    }
    res = engine.evaluate_fixture(fixture)
    assert res.archetype == AnomalyArchetype.PURE_SHOOTOUT
    assert res.tier in (AnomalySignalTier.GOLD_TIER, AnomalySignalTier.SILVER_TIER)
    assert res.gasi_score >= 65.0
    assert "BTTS_AND_OVER_2.5" in res.recommended_markets or "OVER_3.5" in res.recommended_markets


# 3. Mismatch Hyper Tempo (Heavy Favorite Blowout)
def test_mismatch_hyper_tempo(engine):
    fixture = {
        "event_id": "test_mismatch",
        "home_team": "Manchester City",
        "away_team": "Luton Town",
        "league": "Premier League",
        "open_1": 1.18,
        "open_2": 15.0,
        "open_o25": 1.38,
        "steam_o25_pct": -1.0,
    }
    res = engine.evaluate_fixture(fixture)
    assert res.archetype == AnomalyArchetype.MISMATCH_HYPER_TEMPO
    assert res.tier in (AnomalySignalTier.GOLD_TIER, AnomalySignalTier.SILVER_TIER)
    assert res.gasi_score >= 75.0


# 4. Steam Shock Archetype (Sharp Money Drops Over Line)
def test_steam_shock_archetype(engine):
    fixture = {
        "event_id": "test_steam_shock",
        "home_team": "Feyenoord",
        "away_team": "Utrecht",
        "league": "Eredivisie",
        "open_1": 1.40,
        "open_2": 6.50,
        "open_o25": 1.62,
        "close_o25": 1.48,  # Dropped > 8%
        "steam_o25_pct": -8.6,
    }
    res = engine.evaluate_fixture(fixture)
    assert res.archetype == AnomalyArchetype.STEAM_SHOCK
    assert res.gasi_score >= 65.0


# 5. Defensive Grind League VETO (La Liga 2, Ligue 2, Serie B)
def test_defensive_grind_league_veto(engine):
    fixture = {
        "event_id": "test_sp2_grind",
        "home_team": "Alcorcon",
        "away_team": "Mirandes",
        "league": "La Liga 2",
        "open_1": 2.30,
        "open_2": 3.10,
        "open_o25": 1.40,  # Even with weird low over, league is vetoed
    }
    res = engine.evaluate_fixture(fixture)
    assert res.tier == AnomalySignalTier.PASS
    assert res.gasi_score == 0.0
    assert res.veto_reason is not None
    assert "La Liga 2" in res.veto_reason or "historical 6+ rate" in res.veto_reason


# 6. Heavy Under Drift VETO
def test_heavy_under_drift_veto(engine):
    fixture = {
        "event_id": "test_under_drift",
        "home_team": "Wolves",
        "away_team": "Crystal Palace",
        "league": "Premier League",
        "open_1": 2.40,
        "open_2": 2.90,
        "open_o25": 1.85,
        "steam_o25_pct": 8.0,  # Odds drifted up 8%, money on Under
    }
    res = engine.evaluate_fixture(fixture)
    assert res.tier == AnomalySignalTier.PASS
    assert res.veto_reason == "Heavy Under drift"


# 7. Live In-Play Filter: HT Goals < 2 Crashes 6+ Probability
def test_live_inplay_ht_goals_crash(engine):
    fixture = {
        "event_id": "test_bayern_live",
        "home_team": "Bayern Munich",
        "away_team": "Bochum",
        "league": "Bundesliga",
        "open_1": 1.15,
        "open_2": 16.0,
        "open_o25": 1.25,
    }
    # Halftime whistle, but score is only 1-0 (1 goal)
    live_res = engine.evaluate_live_fixture(fixture, minute=46, ht_goals=1)
    assert live_res.tier == AnomalySignalTier.PASS
    assert live_res.is_live_qualified is False
    assert live_res.veto_reason is not None
    assert "Insufficient HT tempo" in live_res.veto_reason


# 8. Live In-Play Filter: HT Goals >= 2 Confirms Eruption
def test_live_inplay_ht_goals_confirm(engine):
    fixture = {
        "event_id": "test_bayern_live_hot",
        "home_team": "Bayern Munich",
        "away_team": "Bochum",
        "league": "Bundesliga",
        "open_1": 1.15,
        "open_2": 16.0,
        "open_o25": 1.25,
    }
    # Halftime whistle, score is 2-1 (3 goals)
    live_res = engine.evaluate_live_fixture(fixture, minute=46, ht_goals=3)
    assert live_res.tier == AnomalySignalTier.GOLD_TIER
    assert live_res.is_live_qualified is True
    assert live_res.gasi_score >= 95.0
    assert "IN_PLAY_OVER_5.5" in live_res.recommended_markets


# 9. Syndicate GoalAnomalyAgent Integration Verdict
def test_syndicate_agent_evaluation(agent):
    fixture = {
        "event_id": "test_syndicate_fixture",
        "home_team": "PSV Eindhoven",
        "away_team": "Ajax",
        "league": "Eredivisie",
        "open_1": 1.95,
        "open_2": 3.40,
        "open_o25": 1.35,
        "steam_o25_pct": -4.0,
    }
    verdict = agent.evaluate(fixture)
    assert verdict.approved is True
    assert verdict.agent_name == "Goal Anomaly Specialist"
    assert verdict.tier in ("TIER_1_SHIELD", "TIER_2_VALUE")
    assert verdict.metadata["gasi_score"] >= 80.0
    assert verdict.metadata["primary_market"] == "OVER_3.5"
    assert verdict.metadata["archetype"] in (AnomalyArchetype.HYPER_OVER_MAGNET.value, AnomalyArchetype.STEAM_SHOCK.value, AnomalyArchetype.PURE_SHOOTOUT.value)


# 10. Option A: Primary Market OVER_3.5 Priority & Under Veto Tests
def test_primary_market_is_over_35_for_gold_and_silver(engine):
    fixture_gold = {
        "event_id": "test_gold",
        "home_team": "Bayern Munich",
        "away_team": "Dortmund",
        "league": "D1",
        "open_1": 1.70,
        "open_2": 4.00,
        "open_o25": 1.30,
    }
    res_gold = engine.evaluate_fixture(fixture_gold)
    assert res_gold.tier == AnomalySignalTier.GOLD_TIER
    assert res_gold.primary_market == "OVER_3.5"

    fixture_silver = {
        "event_id": "test_silver",
        "home_team": "Frankfurt",
        "away_team": "Wolfsburg",
        "league": "D1",
        "open_1": 2.10,
        "open_2": 3.10,
        "open_o25": 1.55,
        "steam_o25_pct": -2.0,
    }
    res_silver = engine.evaluate_fixture(fixture_silver)
    assert res_silver.tier == AnomalySignalTier.SILVER_TIER
    assert res_silver.primary_market == "OVER_3.5"


def test_goal_anomaly_agent_vetoes_under_market_on_eruption(agent):
    fixture_under = {
        "event_id": "test_under_bet",
        "home_team": "Bayern Munich",
        "away_team": "Dortmund",
        "league": "D1",
        "market": "TOPLAM GOL",
        "selection": "2.5 ALT",
        "open_1": 1.70,
        "open_2": 4.00,
        "open_o25": 1.30,
    }
    verdict = agent.evaluate(fixture_under)
    assert verdict.approved is False
    assert verdict.tier == "PASS"
    assert "strongly conflicts with Under market" in verdict.veto_reason


def test_goal_anomaly_agent_advisory_on_over_25(agent):
    fixture_over25 = {
        "event_id": "test_over25_bet",
        "home_team": "Bayern Munich",
        "away_team": "Dortmund",
        "league": "D1",
        "market": "TOPLAM GOL 2.5 ÜST",
        "selection": "2.5 ÜST",
        "open_1": 1.70,
        "open_2": 4.00,
        "open_o25": 1.30,
    }
    verdict = agent.evaluate(fixture_over25)
    assert verdict.approved is True
    assert "market_upgrade_advisory" in verdict.metadata
    assert "Over 3.5 pazarının" in verdict.metadata["market_upgrade_advisory"]
