"""Unit tests for full football market derivation, correct score, period, and longshot logic."""

import pytest

from sports_engine.collectors.turkey_football import classify_fixture_competition
from sports_engine.models.football_markets import FootballMarketEngine


def test_football_market_engine_normalization():
    """Verify all derived market probabilities adhere to probability axioms (sum to 1.0)."""
    engine = FootballMarketEngine(lambda_home=1.65, lambda_away=1.15)
    markets = engine.get_full_market_suite()

    # 1. 1X2
    m1x2 = markets["1x2"]
    assert pytest.approx(m1x2["HOME"] + m1x2["DRAW"] + m1x2["AWAY"], abs=1e-3) == 1.0

    # 2. Over / Under 2.5
    ou25 = markets["totals"]["OVER_UNDER_2.5"]
    assert pytest.approx(ou25["OVER"] + ou25["UNDER"], abs=1e-3) == 1.0

    # 3. Both Teams To Score (BTTS)
    btts = markets["btts"]
    assert pytest.approx(btts["YES"] + btts["NO"], abs=1e-3) == 1.0

    # 4. Double Chance consistency
    dc = markets["double_chance"]
    assert pytest.approx(dc["1X"], abs=1e-3) == m1x2["HOME"] + m1x2["DRAW"]
    assert pytest.approx(dc["X2"], abs=1e-3) == m1x2["DRAW"] + m1x2["AWAY"]
    assert pytest.approx(dc["12"], abs=1e-3) == m1x2["HOME"] + m1x2["AWAY"]

    # 5. First Half 1X2
    fh_1x2 = markets["first_half"]["1X2"]
    assert pytest.approx(fh_1x2["HOME"] + fh_1x2["DRAW"] + fh_1x2["AWAY"], abs=1e-3) == 1.0

    # 6. HT / FT 9-outcome sum
    ht_ft = markets["ht_ft"]
    assert len(ht_ft) == 9
    tot_htft = sum(item["probability"] for item in ht_ft.values())
    assert pytest.approx(tot_htft, abs=1e-2) == 1.0


def test_correct_score_and_longshots():
    """Verify correct score probabilities and longshot tier scanning."""
    engine = FootballMarketEngine(lambda_home=1.2, lambda_away=1.8)
    scores = engine.get_correct_score_distribution(top_n=20)
    assert len(scores) == 20
    assert all(s["probability"] >= 0.0 for s in scores)
    assert all(s["fair_odds"] > 1.0 for s in scores)

    longshots = engine.scan_longshots(min_odds=3.0)
    assert len(longshots) > 0
    for ls in longshots:
        assert ls.fair_odds >= 3.0
        assert ls.is_longshot is True
        assert ls.status == "UNADJUSTED"
        assert ls.longshot_tier is not None


def test_turkish_competition_classifier():
    """Verify classification of Süper Lig vs 1. Lig competitions."""
    assert classify_fixture_competition("Galatasaray", "Fenerbahçe") == "Trendyol Süper Lig"
    assert classify_fixture_competition("Gençlerbirliği", "Amedspor") == "Trendyol 1. Lig"
    assert classify_fixture_competition("Alanyaspor", "Erzurumspor") == "Trendyol 1. Lig"
    assert classify_fixture_competition("Kocaelispor", "Sakaryaspor") == "Trendyol 1. Lig"
