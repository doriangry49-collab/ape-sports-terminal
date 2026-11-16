"""Comprehensive Regression Test Suite for Phases 1 (P0), 2 (P1), and 3 (P2) Quant & Engineering Upgrades."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from advanced_corner_engine import (
    AdvancedCornerEngine,
    devig_two_way_shin_power,
)
from live_monitor_daemon import (
    scan_quant_engine_signals,
    update_and_compute_nesine_steam,
)
from live_settlement_engine import (
    fetch_espn_event_stats,
    run_settlement_cycle,
    validate_coupon_constraints,
)
from odds_pattern_miner import OddsPatternMiner, benjamini_hochberg_fdr
from paper_trader import (
    PaperTradingEngine,
    validate_coupon_stake_and_exposure,
)
from team_normalizer import TeamNormalizer
from team_strength_engine import TeamStrengthEngine
from telegram_notifier import process_user_command
from universal_market_matrix import UniversalMarketMatrix

TRT_TZ = timezone(timedelta(hours=3))


def test_r1_fail_closed_espn_stats_and_settlement(tmp_path, monkeypatch):
    """Verify missing ESPN corner/card stats return None and keep Under bets PENDING (SPEC-0012)."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("ESPN Timeout")),
    )
    stats = fetch_espn_event_stats("999999", "uefa.champions")
    assert stats["corners"] is None
    assert stats["cards"] is None

    # Verify settlement cycle keeps coupon PENDING when corners are None
    test_coupons = tmp_path / "active_coupons.json"
    test_bankroll = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll)

    coupons = [
        {
            "id": "c_under_corner",
            "name": "Corner Shield",
            "type": "SINGLE",
            "stake": 50.0,
            "potential_return": 101.5,
            "status": "PENDING",
            "picks": [
                {
                    "match": "Slavia Prag vs Arsenal",
                    "home": "Slavia Prag",
                    "away": "Arsenal",
                    "league_key": "ucl",
                    "market": "CORNERS",
                    "selection": "Korner 8.5 ALT",
                    "odds": 2.03,
                    "status": "PENDING",
                }
            ],
        }
    ]
    test_coupons.write_text(json.dumps(coupons), encoding="utf-8")
    test_bankroll.write_text(json.dumps({"initial_bankroll": 150.0, "cash_balance": 50.0}), encoding="utf-8")

    # Match finished 0-2, but event stats return None corners
    monkeypatch.setattr(
        "live_settlement_engine.fetch_espn_scores",
        lambda *args, **kwargs: [
            {
                "event_id": "999999",
                "name": "Arsenal at Slavia Prague",
                "league": "uefa.champions",
                "home": "Slavia Prague",
                "away": "Arsenal",
                "hg": 0,
                "ag": 2,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }
        ],
    )

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 0
    saved = json.loads(test_coupons.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "PENDING"
    assert saved[0]["picks"][0]["status"] == "PENDING"


def test_r1_dual_similarity_rejects_single_sided_match(tmp_path, monkeypatch):
    """Verify settlement rejects pairings where min(sim_h, sim_a) < 0.65 even if one team matches 1.0."""
    test_coupons = tmp_path / "active_coupons.json"
    test_bankroll = tmp_path / "active_bankroll.json"
    monkeypatch.setattr("live_settlement_engine.COUPONS_FILE", test_coupons)
    monkeypatch.setattr("live_settlement_engine.BANKROLL_FILE", test_bankroll)

    coupons = [
        {
            "id": "c_dual_sim",
            "name": "Dual Sim Test",
            "type": "SINGLE",
            "stake": 50.0,
            "potential_return": 100.0,
            "status": "PENDING",
            "picks": [
                {
                    "match": "Slavia Prag vs Arsenal",
                    "home": "Slavia Prag",
                    "away": "Arsenal",
                    "league_key": "ucl",
                    "market": "1X2",
                    "selection": "MS 2",
                    "odds": 2.00,
                    "status": "PENDING",
                }
            ],
        }
    ]
    test_coupons.write_text(json.dumps(coupons), encoding="utf-8")
    test_bankroll.write_text(json.dumps({"initial_bankroll": 150.0, "cash_balance": 50.0}), encoding="utf-8")

    # Different home team ("Sporting CP" vs "Arsenal") -> sim_a = 1.0, sim_h < 0.30 (avg > 0.50, min < 0.65)
    monkeypatch.setattr(
        "live_settlement_engine.fetch_espn_scores",
        lambda *args, **kwargs: [
            {
                "event_id": "111",
                "name": "Arsenal at Sporting CP",
                "league": "uefa.champions",
                "home": "Sporting CP",
                "away": "Arsenal",
                "hg": 1,
                "ag": 2,
                "status": "Full Time",
                "is_completed": True,
                "is_in_progress": False,
            }
        ],
    )

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 0
    saved = json.loads(test_coupons.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "PENDING"


def test_r1_paper_trader_composite_keys_and_spec0015(tmp_path):
    """Verify composite signal keys prevent cross-match collisions and SPEC-0015 stake/exposure rules hold."""
    ledger_file = tmp_path / "ledger.csv"
    engine = PaperTradingEngine(ledger_path=ledger_file)

    # Two different matches without fixture_id on the same market/outcome
    alerts = [
        {
            "home": "Marsilya",
            "away": "Toulouse",
            "kickoff": "2026-11-05T20:00:00Z",
            "market": "1X2",
            "outcome": "MS 1",
            "soft_book": "nesine",
            "soft_odds": 1.67,
            "fair_odds": 1.52,
            "prob": 0.658,
            "edge_pct": 9.8,
        },
        {
            "home": "Athletic Club",
            "away": "Real Sociedad",
            "kickoff": "2026-11-05T21:00:00Z",
            "market": "1X2",
            "outcome": "MS 1",
            "soft_book": "nesine",
            "soft_odds": 1.76,
            "fair_odds": 1.60,
            "prob": 0.625,
            "edge_pct": 10.0,
        },
    ]
    res = engine.record_value_signals(alerts)
    assert res["inserted"] == 2
    rows = engine.load_rows()
    assert len(rows) == 2
    assert rows[0]["signal_id"] != rows[1]["signal_id"]
    assert "2026-11-05_marsilya_toulouse|1X2|MS 1" == rows[0]["signal_id"]

    # SPEC-0015: Stake < 50 TL must raise ValueError
    with pytest.raises(ValueError, match="SPEC-0015"):
        validate_coupon_stake_and_exposure({"id": "c1", "stake": 44.0, "picks": []})
    with pytest.raises(ValueError, match="SPEC-0015"):
        validate_coupon_constraints({"id": "c1", "stake": 47.0, "picks": []})

    # Single-match exposure cap: max 1 active coupon per match per night
    existing = [
        {
            "id": "c_existing",
            "stake": 50.0,
            "status": "PENDING",
            "picks": [{"home": "Marsilya", "away": "Toulouse", "market": "1X2", "selection": "MS 1"}],
        }
    ]
    with pytest.raises(ValueError, match="Exposure cap"):
        validate_coupon_stake_and_exposure(
            {
                "id": "c_dup",
                "stake": 50.0,
                "status": "PENDING",
                "picks": [{"home": "Marsilya", "away": "Toulouse", "market": "TG_6+", "selection": "TG 6+"}],
            },
            existing_coupons=existing,
        )


def test_r1_team_normalizer_protected_squad_isolation():
    """Verify women's, reserve, and youth teams never match senior A-teams."""
    norm = TeamNormalizer()
    assert norm.compute_similarity("Real Sociedad", "Real Sociedad B") == 0.0
    assert norm.compute_similarity("Levante", "Levante (K)") == 0.0
    assert norm.compute_similarity("Chelsea", "Chelsea W") == 0.0
    assert norm.compute_similarity("Ajax", "Ajax U19") == 0.0
    assert norm.compute_similarity("Sporting", "Sporting U21") == 0.0
    assert norm.compute_similarity("Bayern Munich", "Bayern Munich II") == 0.0
    assert norm.compute_similarity("Arsenal", "Arsenal Reserves") == 0.0

    # Same squad category still matches cleanly
    assert norm.compute_similarity("Real Sociedad B", "Sociedad B") == 1.0
    assert norm.compute_similarity("Levante (K)", "UD Levante (K)") == 1.0


def test_r1_markov_htft_and_lru_cache():
    """Verify TeamStrengthEngine uses Markov transition matrix for HT/FT and caches get_team_rating."""
    eng = TeamStrengthEngine()
    eng.load_or_train()

    preds = eng.predict_match("Arsenal", "Chelsea")
    htft = preds["htft"]
    assert set(htft.keys()) == {"1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"}
    tot_prob = sum(v["prob"] for v in htft.values())
    assert pytest.approx(tot_prob, abs=1e-2) == 1.0

    # Verify @lru_cache is active on get_team_rating
    eng.get_team_rating("Arsenal")
    eng.get_team_rating("Arsenal")
    info = eng.get_team_rating.cache_info()
    assert info.hits >= 1


def test_r1_signal_leakage_prevention(tmp_path, monkeypatch):
    """Verify raw TeamStrengthEngine 1X2 and corner signals do not leak when Value/Corner engines reject."""
    import live_monitor_daemon
    monkeypatch.setattr(live_monitor_daemon, "NESINE_TIMESERIES_DB", tmp_path / "nesine_odds_timeseries.db")
    future_dt = datetime.now(TRT_TZ) + timedelta(hours=3)
    bulletin = [
        {
            "home": "Arsenal",
            "away": "Chelsea",
            "date_str": future_dt.strftime("%d.%m.%Y"),
            "time_str": future_dt.strftime("%H:%M"),
            "nesine_1x2": (1.05, 8.00, 15.00),  # Outside ValueScanner [1.35, 3.50] band -> rejected by ValueScanner
            "nesine_corners": {"9.5": {"under": 1.10, "over": 1.10}},  # Negative EV -> rejected by CornerEngine
            "mbs": 1,
        }
    ]
    sigs = scan_quant_engine_signals(min_edge_pct=3.0, bulletin=bulletin)
    # Neither raw 1X2 nor raw corner signals should leak through
    assert not any(s.get("market") == "1X2" for s in sigs)
    assert not any(s.get("is_corner") for s in sigs)


def test_r1_r3_corner_engine_normalizer_devig_and_negbin():
    """Verify AdvancedCornerEngine resolves team names via TeamNormalizer, applies de-vig, and uses Negative Binomial."""
    c_eng = AdvancedCornerEngine()
    c_eng.team_lookup = {
        "manchester city": {
            "corners_for": 7.5,
            "corners_against": 3.2,
            "matches": 38,
        }
    }
    c_eng.team_stats = c_eng.team_lookup
    c_eng.resolve_team_profile.cache_clear()

    # Alias "Man. City" should resolve to "manchester city" via TeamNormalizer
    prof = c_eng.resolve_team_profile("Man. City")
    assert prof is not None
    assert prof["corners_for"] == 7.5

    # Shin/Power two-way de-vig
    dv = devig_two_way_shin_power(1.72, 1.78)
    assert dv["margin_pct"] > 10.0
    assert pytest.approx(dv["p_under_fair"] + dv["p_over_fair"], abs=1e-3) == 1.0
    assert dv["fair_under"] > 1.72
    assert dv["fair_over"] > 1.78

    # Overdispersed Negative Binomial pricing (variance > mu) for 8.5 ALT and 9.5 ALT/ÜST
    priced = c_eng.price_lines(
        mu=9.6,
        nesine_corners={
            "8.5": {"under": 2.05, "over": 1.52},
            "9.5": {"under": 1.72, "over": 1.78},
        },
    )
    assert priced["distribution"] == "NegativeBinomial"
    assert priced["variance"] > priced["mu"]
    assert "8.5" in priced["lines"]
    assert "9.5" in priced["lines"]
    assert priced["lines"]["9.5"]["devig_fair_under"] > 1.72


def test_r1_telegram_parmakizi_kickoff_window():
    """Verify /parmakizi enforces SPEC-0013 (started match rejection) and SPEC-0014 (>12h rejection)."""
    past_dt = datetime.now(TRT_TZ) - timedelta(hours=1)
    far_future_dt = datetime.now(TRT_TZ) + timedelta(hours=16)

    mock_bulletin = [
        {
            "home": "StartedTeam",
            "away": "OpponentA",
            "nesine_1x2": (1.80, 3.20, 3.50),
            "nesine_ou25": (1.75, 1.85),
            "date_str": past_dt.strftime("%d.%m.%Y"),
            "time_str": past_dt.strftime("%H:%M"),
            "mbs": 1,
        },
        {
            "home": "FarFutureTeam",
            "away": "OpponentB",
            "nesine_1x2": (1.80, 3.20, 3.50),
            "nesine_ou25": (1.75, 1.85),
            "date_str": far_future_dt.strftime("%d.%m.%Y"),
            "time_str": far_future_dt.strftime("%H:%M"),
            "mbs": 1,
        },
    ]

    with patch("telegram_notifier.fetch_nesine_live_bulletin", return_value=mock_bulletin):
        resp_past = process_user_command("/parmakizi StartedTeam")
        assert "SPEC-0013/0014" in resp_past or "bulunamadı" in resp_past

        resp_far = process_user_command("/parmakizi FarFutureTeam")
        assert "SPEC-0013/0014" in resp_far or "bulunamadı" in resp_far


def test_r2_nesine_live_steam_tracker(tmp_path):
    """Verify Nesine live steam tracker records opening odds in SQLite and computes real-time steam %."""
    db_file = tmp_path / "nesine_odds_timeseries.db"

    # 1st poll: opening odds recorded -> steam = 0.0%
    b1 = [
        {
            "date_str": "05.11.2026",
            "home": "Arsenal",
            "away": "Chelsea",
            "nesine_1x2": (2.00, 3.30, 3.40),
            "nesine_ou25": (1.80, 1.80),
        }
    ]
    update_and_compute_nesine_steam(b1, db_path=db_file)
    assert b1[0]["steam_1_pct"] == 0.0
    assert b1[0]["steam_o25_pct"] == 0.0

    # 2nd poll: MS 1 dropped from 2.00 to 1.80 (-10.0%), O2.5 dropped from 1.80 to 1.62 (-10.0%)
    b2 = [
        {
            "date_str": "05.11.2026",
            "home": "Arsenal",
            "away": "Chelsea",
            "nesine_1x2": (1.80, 3.40, 3.80),
            "nesine_ou25": (1.62, 2.00),
        }
    ]
    update_and_compute_nesine_steam(b2, db_path=db_file)
    assert b2[0]["steam_1_pct"] == -10.0
    assert b2[0]["steam_o25_pct"] == -10.0


def test_r2_r3_devig_matrix_and_walk_forward_fdr():
    """Verify margin removal on UniversalMarketMatrix / FingerprintEngine and Walk-Forward + BH-FDR on OddsPatternMiner."""
    umm = UniversalMarketMatrix()
    f1, fx, f2 = umm.devig_1x2(1.30, 4.50, 7.00)
    assert pytest.approx((1.0 / f1) + (1.0 / fx) + (1.0 / f2), abs=1e-2) == 1.0

    # High-margin Nesine fixture (O2.5 = 1.34, U2.5 = 2.45 -> overround ~1.154 -> de-vigged fair O2.5 ~ 1.55)
    prof = umm.profile_fixture(o1=1.30, ox=4.50, o2=7.00, o_o25=1.34, o_u25=2.45, devig=True)
    assert prof is not None

    # Benjamini-Hochberg FDR control
    q_vals, flags = benjamini_hochberg_fdr([0.001, 0.01, 0.20, 0.80], alpha=0.05)
    assert flags == [True, True, False, False]
    assert q_vals[0] <= q_vals[1] <= q_vals[2] <= q_vals[3]

    # Walk-Forward pattern discovery
    miner = OddsPatternMiner()
    patterns = miner.discover_golden_patterns(min_sample=100, min_edge=5.0, enforce_walk_forward=True)
    assert len(patterns) >= 3
    for p in patterns:
        assert p.get("fdr_significant") is True
        assert p["walk_forward"]["oos_consistent"] is True

