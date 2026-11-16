"""Unit tests for Universal Market Matrix & Archetype Lookup Engine."""

from __future__ import annotations

from universal_market_matrix import UniversalMarketMatrix, UniversalOddsProfile


def test_universal_market_matrix_lookup():
    umm = UniversalMarketMatrix()

    # 1. Heavy Home Fav + High Tempo match (e.g. Man City vs Southampton)
    profile = umm.profile_fixture(
        o1=1.25,
        ox=6.50,
        o2=11.0,
        o_o25=1.35,
        o_u25=3.10,
        steam_o25=-6.0,
        steam_1=-8.0,
    )

    assert isinstance(profile, UniversalOddsProfile)
    assert "Ağır Favori" in profile.home_band
    assert "Aşırı Yüksek Tempo" in profile.tempo_band
    assert profile.p_1 > 70.0
    assert profile.p_o25 > 65.0
    assert profile.avg_corners > 10.0
    assert profile.p_c85 > 65.0
    assert profile.p_c95 > 55.0


def test_universal_market_matrix_defensive_clash():
    umm = UniversalMarketMatrix()

    # 2. Balanced Defensive Match (e.g. Getafe vs Osasuna)
    profile = umm.profile_fixture(
        o1=2.60,
        ox=2.90,
        o2=2.85,
        o_o25=2.40,
        o_u25=1.55,
        steam_o25=7.0,
    )

    assert "Dengeli Maç" in profile.home_band
    assert "Aşırı Kısır" in profile.tempo_band
    assert profile.p_o25 < 45.0
    assert profile.avg_corners < 9.70
    assert profile.avg_cards > 4.60  # high cards in defensive low-scoring slog

