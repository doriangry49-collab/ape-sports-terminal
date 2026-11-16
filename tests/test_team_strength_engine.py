"""Unit tests for Empirical Bayes Poisson & Dixon-Coles Team Strength Engine."""

from team_strength_engine import (
    TeamStrengthEngine,
    _dixon_coles_tau,
    _neg_bin_pmf,
    _poisson_pmf,
)


def test_distribution_helpers():
    # Poisson properties
    p0 = _poisson_pmf(0, 1.5)
    p1 = _poisson_pmf(1, 1.5)
    assert 0.0 < p0 < 1.0
    assert 0.0 < p1 < 1.0

    # Dixon-Coles tau adjustment
    tau_00 = _dixon_coles_tau(0, 0, 1.2, 1.0, rho=-0.06)
    assert tau_00 > 1.0  # low scoring under-representation correction
    tau_22 = _dixon_coles_tau(2, 2, 1.2, 1.0, rho=-0.06)
    assert tau_22 == 1.0  # unaffected for scores > 1

    # Negative Binomial corner PMF
    p_corn_sum = sum(_neg_bin_pmf(k, 9.5, kappa=0.14) for k in range(35))
    assert 0.99 <= p_corn_sum <= 1.001


def test_team_strength_engine_initialization_and_mock():
    engine = TeamStrengthEngine()
    # Inject mock ratings
    engine.team_ratings = {
        "Arsenal": {
            "team": "Arsenal",
            "league": "Premier League",
            "matches": 38,
            "alpha": 0.35,
            "beta": -0.40,
            "corner_alpha": 0.20,
            "corner_beta": -0.15,
            "net_rating": 0.75,
        },
        "Bournemouth": {
            "team": "Bournemouth",
            "league": "Premier League",
            "matches": 38,
            "alpha": -0.10,
            "beta": 0.20,
            "corner_alpha": -0.10,
            "corner_beta": 0.10,
            "net_rating": -0.30,
        },
    }

    # Test rating retrieval
    ars = engine.get_team_rating("Arsenal")
    assert ars["alpha"] == 0.35
    assert ars["beta"] == -0.40

    unk = engine.get_team_rating("NonExistentClub")
    assert unk["alpha"] == 0.0
    assert unk["beta"] == 0.0


def test_match_prediction_probabilities():
    engine = TeamStrengthEngine()
    engine.team_ratings = {
        "HomeGiant": {
            "team": "HomeGiant",
            "league": "Test",
            "matches": 30,
            "alpha": 0.40,
            "beta": -0.35,
            "corner_alpha": 0.25,
            "corner_beta": -0.20,
            "net_rating": 0.75,
        },
        "AwayUnderdog": {
            "team": "AwayUnderdog",
            "league": "Test",
            "matches": 30,
            "alpha": -0.20,
            "beta": 0.30,
            "corner_alpha": -0.15,
            "corner_beta": 0.15,
            "net_rating": -0.50,
        },
    }

    res = engine.predict_match("HomeGiant", "AwayUnderdog")

    # Expect home lambda > away lambda
    assert res["lambdas"]["goal_home"] > res["lambdas"]["goal_away"]
    assert res["lambdas"]["corner_home"] > res["lambdas"]["corner_away"]

    # Probability axioms
    p_1x2 = res["p_1x2"]
    assert abs((p_1x2["1"] + p_1x2["X"] + p_1x2["2"]) - 1.0) < 1e-3
    assert p_1x2["1"] > p_1x2["2"]  # Heavy home favorite

    # Double chance
    dc = res["double_chance"]
    assert abs(dc["1X"]["prob"] - (p_1x2["1"] + p_1x2["X"])) < 1e-3

    # DNB
    dnb = res["dnb"]
    assert abs(dnb["DNB_1"]["prob"] + dnb["DNB_2"]["prob"] - 1.0) < 1e-3

    # Totals
    totals = res["totals"]
    assert abs(totals["over_25"]["prob"] + totals["under_25"]["prob"] - 1.0) < 1e-3

    # Corners
    c_95 = res["corners"]["9.5"]
    assert abs(c_95["p_over"] + c_95["p_under"] - 1.0) < 1e-3

    # HTFT 9 transitions sum to 1.0
    htft_sum = sum(v["prob"] for v in res["htft"].values())
    assert abs(htft_sum - 1.0) < 1e-3


def test_evaluate_live_fixture_detects_value():
    engine = TeamStrengthEngine()
    engine.team_ratings = {
        "StrongTeam": {
            "team": "StrongTeam",
            "league": "Test",
            "matches": 20,
            "alpha": 0.30,
            "beta": -0.30,
            "corner_alpha": 0.20,
            "corner_beta": -0.10,
            "net_rating": 0.60,
        },
        "WeakTeam": {
            "team": "WeakTeam",
            "league": "Test",
            "matches": 20,
            "alpha": -0.20,
            "beta": 0.25,
            "corner_alpha": -0.15,
            "corner_beta": 0.20,
            "net_rating": -0.45,
        },
    }

    # Bookmaker offers inflated odds on StrongTeam (e.g. 2.10 when fair is ~1.50)
    fixture = {
        "home": "StrongTeam",
        "away": "WeakTeam",
        "time_str": "20:00",
        "mbs": 1,
        "nesine_1x2": (2.10, 3.40, 3.50),
        "nesine_ou25": (1.80, 1.90),  # (over, under)
        "nesine_corners": {"9.5": {"under": 1.70, "over": 2.05}},
        "nesine_htft": {"1/1": 3.80, "X/1": 5.50},
        "nesine_tg6": 12.0,
    }

    signals = engine.evaluate_live_fixture(fixture, min_edge_pct=5.0)
    assert len(signals) > 0

    # Ensure edge calculation math is correct and extreme EV (> 35%) anomalies are vetoed
    for s in signals:
        expected_edge = (s["prob"] * s["book_odd"] - 1.0) * 100
        assert abs(s["edge_pct"] - expected_edge) < 0.2
        assert s["edge_pct"] <= 35.0


def test_low_sample_country_mismatch_and_extreme_ev_vetoes():
    """Verify SPEC-0012 protection against low-sample teams, cross-continent mis-matches, and >35% EV spikes."""
    engine = TeamStrengthEngine()
    engine.team_ratings = {
        "Southampton": {
            "team": "Southampton",
            "league": "Premier League",
            "matches": 100,
            "alpha": 0.15,
            "beta": -0.10,
            "corner_alpha": 0.05,
            "corner_beta": -0.05,
            "net_rating": 0.25,
        },
        "Wolves": {
            "team": "Wolves",
            "league": "Premier League",
            "matches": 100,
            "alpha": -0.15,
            "beta": 0.15,
            "corner_alpha": -0.05,
            "corner_beta": 0.05,
            "net_rating": -0.30,
        },
        "ThinClub": {
            "team": "ThinClub",
            "league": "Super Lig",
            "matches": 3,
            "alpha": 0.20,
            "beta": -0.20,
            "corner_alpha": 0.0,
            "corner_beta": 0.0,
            "net_rating": 0.40,
        },
        "FullClub": {
            "team": "FullClub",
            "league": "Super Lig",
            "matches": 30,
            "alpha": -0.10,
            "beta": 0.10,
            "corner_alpha": 0.0,
            "corner_beta": 0.0,
            "net_rating": -0.20,
        },
    }

    # 1. Cross-country mismatch ('Au' Australia vs England Premier League) vetoed
    au_fixture = {
        "home": "South Hobart",
        "away": "Woll. Wolves",
        "country": "Au",
        "nesine_1x2": (4.27, 3.50, 1.65),
    }
    assert engine.evaluate_live_fixture(au_fixture, min_edge_pct=4.0) == []

    # 2. Low-sample (< 6 historical matches) vetoed
    thin_fixture = {
        "home": "ThinClub",
        "away": "FullClub",
        "country": "Turkey",
        "nesine_1x2": (2.50, 3.20, 2.80),
    }
    assert engine.evaluate_live_fixture(thin_fixture, min_edge_pct=4.0) == []

    # 3. Same country & ample sample but > 35% extreme EV outlier on individual market is vetoed
    extreme_fixture = {
        "home": "Southampton",
        "away": "Wolves",
        "country": "England",
        "nesine_1x2": (4.27, 3.40, 1.70),
    }
    sigs = engine.evaluate_live_fixture(extreme_fixture, min_edge_pct=4.0, max_edge_pct=35.0)
    assert all(s["edge_pct"] <= 35.0 for s in sigs)
    assert not any(s["selection"] == "MS 1" for s in sigs)


def test_fit_from_data_ingests_supplemental_bra_and_usa_csvs(tmp_path):
    """Verify fit_from_data loads supplemental BRA.csv and USA.csv next to gold parquet."""
    import pandas as pd

    gold_dir = tmp_path / "gold"
    raw_dir = tmp_path / "raw_odds"
    gold_dir.mkdir()
    raw_dir.mkdir()
    parquet_path = gold_dir / "ground_truth.parquet"
    cache_path = tmp_path / "silver" / "ratings.json"

    base_df = pd.DataFrame([
        {
            "date": "2026-05-01",
            "league": "Premier League",
            "div_code": "E0",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "fthg": 2,
            "ftag": 1,
            "home_corners": 6,
            "away_corners": 4,
            "home_shots": 14,
            "away_shots": 9,
            "home_shots_target": 6,
            "away_shots_target": 3,
        }
    ])
    base_df.to_parquet(parquet_path, index=False)

    pd.DataFrame([
        {"Date": "25/10/2026", "Home": "Flamengo RJ", "Away": "Palmeiras", "HG": 2, "AG": 0},
        {"Date": "26/10/2026", "Home": "Botafogo RJ", "Away": "Palmeiras", "HG": None, "AG": 1},
    ]).to_csv(raw_dir / "BRA.csv", index=False)

    pd.DataFrame([
        {"Date": "26/10/2026", "Home": "Inter Miami", "Away": "LAFC", "HG": 3, "AG": 1},
    ]).to_csv(raw_dir / "USA.csv", index=False)

    engine = TeamStrengthEngine(parquet_path=parquet_path, cache_path=cache_path)
    engine.fit_from_data()

    # 1 gold match + 1 valid BRA match (null HG row dropped) + 1 USA match = 3 total
    assert engine.total_matches_trained == 3
    assert any("Flamengo" in t for t in engine.team_ratings)
    assert any("Inter Miami" in t for t in engine.team_ratings)


def test_no_synthetic_double_chance_without_real_nesine_dc():
    """Verify synthetic Çifte Şans signals are disabled unless real nesine_dc odds exist."""
    engine = TeamStrengthEngine()
    engine.team_ratings = {
        "SolidHome": {
            "team": "SolidHome",
            "league": "La Liga",
            "matches": 30,
            "alpha": 0.12,
            "beta": -0.08,
            "corner_alpha": 0.0,
            "corner_beta": 0.0,
            "net_rating": 0.20,
        },
        "WeakAway": {
            "team": "WeakAway",
            "league": "La Liga",
            "matches": 30,
            "alpha": -0.10,
            "beta": 0.10,
            "corner_alpha": 0.0,
            "corner_beta": 0.0,
            "net_rating": -0.20,
        },
    }

    # Without nesine_dc, even playable 1X2 odds that would produce synthetic DC must emit zero Çifte Şans
    no_dc_fixture = {
        "home": "SolidHome",
        "away": "WeakAway",
        "country": "Spain",
        "time_str": "21:00",
        "mbs": 1,
        "nesine_1x2": (2.10, 3.30, 3.30),
    }
    sigs_without_dc = engine.evaluate_live_fixture(no_dc_fixture, min_edge_pct=4.0)
    assert not any(s["market"] == "Çifte Şans" for s in sigs_without_dc)

    # Now supply real posted nesine_dc odds -> evaluated within 1.45..6.50 odds and <=35% EV cap
    with_real_dc = dict(no_dc_fixture)
    with_real_dc["nesine_dc"] = {"1X": 1.60, "X2": 1.15}
    sigs_with_dc = engine.evaluate_live_fixture(with_real_dc, min_edge_pct=4.0)
    dc_sigs = [s for s in sigs_with_dc if s["market"] == "Çifte Şans"]
    assert len(dc_sigs) == 1
    assert dc_sigs[0]["selection"] == "1X (Ev & Beraberlik)"
    assert dc_sigs[0]["book_odd"] == 1.60
    assert dc_sigs[0]["is_synthetic"] is False

