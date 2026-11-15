"""Unit tests for scripts/run_daily_prototype.py enforcing SPEC-0012..0015."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from discrete_kelly_optimizer import DiscreteKellyOptimizer
from live_stale_line_adapter import AdapterError
from scripts.run_daily_prototype import build_uncorrelated_coupon, run_daily_pipeline
from time_utils import TRT_TZ


def test_build_uncorrelated_coupon_distinct_matches_and_min_stake():
    optimizer = DiscreteKellyOptimizer()
    signals = [
        {
            "match": "TeamA vs TeamB",
            "kickoff_trt": "13.11 20:00",
            "mbs": 1,
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 2.10,
            "fair_odd": 1.80,
            "prob": 0.555,
            "edge_pct": 16.7,
            "tier": "TIER_2_VALUE",
        },
        {
            "match": "TeamA vs TeamB",
            "kickoff_trt": "13.11 20:00",
            "mbs": 1,
            "market": "2.5 Gol",
            "selection": "2.5 ÜST",
            "book_odd": 1.90,
            "fair_odd": 1.65,
            "prob": 0.606,
            "edge_pct": 15.1,
            "tier": "TIER_2_VALUE",
        },
        {
            "match": "TeamC vs TeamD",
            "kickoff_trt": "13.11 21:00",
            "mbs": 1,
            "market": "Çifte Şans",
            "selection": "1X",
            "book_odd": 1.40,
            "fair_odd": 1.25,
            "prob": 0.80,
            "edge_pct": 12.0,
            "tier": "TIER_1_SHIELD",
        },
        {
            "match": "TeamE vs TeamF",
            "kickoff_trt": "13.11 21:30",
            "mbs": 1,
            "market": "2.5 Gol",
            "selection": "2.5 ALT",
            "book_odd": 1.85,
            "fair_odd": 1.65,
            "prob": 0.606,
            "edge_pct": 12.1,
            "tier": "TIER_2_VALUE",
        },
    ]

    coupon = build_uncorrelated_coupon(signals, optimizer, bankroll=1000.0, min_stake=50.0, max_legs=3)
    assert coupon is not None
    assert coupon["leg_count"] == 2
    assert [leg["match"] for leg in coupon["legs"]] == ["TeamA vs TeamB", "TeamE vs TeamF"]
    assert coupon["recommended_stake_tl"] >= 50.0


def test_run_daily_pipeline_fail_closed_on_adapter_error(tmp_path: Path):
    with patch(
        "scripts.run_daily_prototype.fetch_nesine_live_bulletin",
        side_effect=AdapterError("Nesine CDN unreachable"),
    ):
        with pytest.raises(AdapterError, match="Nesine CDN unreachable"):
            run_daily_pipeline(output_json=tmp_path / "report.json")


def test_run_daily_pipeline_enforces_temporal_and_stake_guardrails(tmp_path: Path):
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=3)
    too_soon_dt = now_trt + timedelta(minutes=1)
    too_late_dt = now_trt + timedelta(hours=15)

    bulletin = [
        {
            "nesine_code": "101",
            "home": "Galatasaray",
            "away": "Fenerbahce",
            "league": "Super Lig",
            "country": "Turkey",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.50, 3.30, 2.80),
        },
        {
            "nesine_code": "102",
            "home": "Galatasaray",
            "away": "Besiktas",
            "league": "Super Lig",
            "country": "Turkey",
            "date_str": too_soon_dt.strftime("%d.%m.%Y"),
            "time_str": too_soon_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.50, 3.30, 2.80),
        },
        {
            "nesine_code": "103",
            "home": "Arsenal",
            "away": "Chelsea",
            "league": "Premier League",
            "country": "England",
            "date_str": too_late_dt.strftime("%d.%m.%Y"),
            "time_str": too_late_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.50, 3.30, 2.80),
        },
    ]

    mock_signal = [
        {
            "match": "Galatasaray vs Fenerbahce",
            "time": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 2.50,
            "fair_odd": 1.90,
            "prob": 0.526,
            "edge_pct": 31.5,
            "tier": "TIER_2_VALUE",
        }
    ]

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch(
            "scripts.run_daily_prototype.fetch_and_scan_live_propline",
            return_value={"fixtures": [], "nesine_matched_fixtures": 0, "signals": []},
        ),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=mock_signal),
    ):
        report = run_daily_pipeline(
            bankroll=1000.0,
            min_ev_pct=4.0,
            min_stake_tl=10.0,  # Attempt below SPEC-0015 floor
            max_hours=24,       # Attempt above SPEC-0014 cap
            output_json=tmp_path / "report.json",
        )

    assert report["config"]["min_stake_tl"] == 50.0
    assert report["config"]["max_hours"] == 12
    assert report["summary"]["bulletin_total_matches"] == 3
    assert report["summary"]["window_valid_matches"] == 1
    assert report["summary"]["signals_count"] == 1
    assert report["signals"][0]["stake"] >= 50.0
    assert (tmp_path / "report.json").exists()


def test_engine2_sharp_market_covers_unknown_international_teams(tmp_path):
    """Engine 2 (PropLine/ESPN Shin) prices national teams skipped by Engine 1 while honoring SPEC-0013/14/15."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=3)
    soon_dt = now_trt + timedelta(minutes=1)
    far_dt = now_trt + timedelta(hours=15)

    bulletin = [
        {
            "nesine_code": "201",
            "home": "Moldova",
            "away": "Kazakistan",
            "league": "UEFA Uluslar Ligi",
            "country": "International",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.60, 3.10, 2.80),
        }
    ]
    sharp_payload = {
        "fixtures": [{"home": "Moldova", "away": "Kazakhstan"}],
        "nesine_matched_fixtures": 1,
        "signals": [
            {
                "event_id": "ev_valid",
                "league": "UEFA Uluslar Ligi [ESPN/NESİNE]",
                "home": "Moldova",
                "away": "Kazakhstan",
                "market": "1X2",
                "outcome": "HOME",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sharp_odds": 2.35,
                "soft_odds": 2.60,
                "fair_prob": 0.425,
                "fair_odds": 2.35,
                "edge_pct": 10.5,
                "nesine_code": "201",
                "mbs": 1,
                "soft_book": "nesine",
                "sharp_provider": "DraftKings",
            },
            {
                "event_id": "ev_too_soon",
                "league": "UEFA Uluslar Ligi",
                "home": "Serbia",
                "away": "Germany",
                "market": "1X2",
                "outcome": "AWAY",
                "kickoff": (soon_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sharp_odds": 1.40,
                "soft_odds": 1.60,
                "fair_prob": 0.70,
                "fair_odds": 1.43,
                "edge_pct": 12.0,
            },
            {
                "event_id": "ev_too_far",
                "league": "UEFA Uluslar Ligi",
                "home": "Spain",
                "away": "Italy",
                "market": "OU_2.5",
                "outcome": "OVER_2.5",
                "kickoff": (far_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sharp_odds": 1.85,
                "soft_odds": 2.15,
                "fair_prob": 0.52,
                "fair_odds": 1.92,
                "edge_pct": 11.8,
            },
        ],
    }

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", return_value=sharp_payload),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=[]),
    ):
        report = run_daily_pipeline(
            bankroll=1000.0,
            min_ev_pct=4.0,
            min_stake_tl=50.0,
            output_json=tmp_path / "intl_report.json",
        )

    assert report["summary"]["skipped_unknown_matches"] == 1
    assert report["summary"]["engine1_signals_count"] == 0
    assert report["summary"]["engine2_signals_count"] == 1
    assert report["summary"]["signals_count"] == 1
    sig = report["signals"][0]
    assert sig["source_engine"] == "sharp_market"
    assert sig["selection"] == "MS 1"
    assert sig["stake"] >= 50.0
    assert sig["sharp_provider"] == "DraftKings"


def test_engine1_and_engine2_merge_and_degraded_safety(tmp_path):
    """Identical selections across Engine 1 & 2 deduplicate as dual_confirmed; Engine 2 error stays isolated."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=2)

    bulletin = [
        {
            "nesine_code": "301",
            "home": "Galatasaray",
            "away": "Fenerbahce",
            "league": "Super Lig",
            "country": "Turkey",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.30, 3.30, 3.00),
        }
    ]
    e1_sig = [
        {
            "match": "Galatasaray vs Fenerbahce",
            "time": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 2.30,
            "fair_odd": 1.95,
            "prob": 0.51,
            "edge_pct": 17.3,
            "tier": "TIER_2_VALUE",
        }
    ]
    e2_payload = {
        "fixtures": [{"home": "Galatasaray", "away": "Fenerbahce"}],
        "nesine_matched_fixtures": 1,
        "signals": [
            {
                "home": "Galatasaray",
                "away": "Fenerbahce",
                "league": "Super Lig [NESİNE]",
                "market": "1X2",
                "outcome": "HOME",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sharp_odds": 1.92,
                "soft_odds": 2.30,
                "fair_prob": 0.52,
                "fair_odds": 1.92,
                "edge_pct": 19.6,
                "nesine_code": "301",
                "soft_book": "nesine",
            }
        ],
    }

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", return_value=e2_payload),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=e1_sig),
    ):
        report_dual = run_daily_pipeline(output_json=tmp_path / "dual.json")

    assert report_dual["summary"]["signals_count"] == 1
    assert report_dual["signals"][0]["dual_confirmed"] is True
    assert report_dual["signals"][0]["edge_pct"] == 19.6

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", side_effect=RuntimeError("offline")),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=e1_sig),
    ):
        report_deg = run_daily_pipeline(output_json=tmp_path / "deg.json")

    assert report_deg["summary"]["sharp_scanner_status"].startswith("degraded:")
    assert report_deg["summary"]["signals_count"] == 1


def test_run_daily_pipeline_syncs_ui_snapshot(tmp_path):
    """Verify sync_ui_snapshot=True triggers export_snapshot.generate_ui_snapshot into target path."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=2)
    bulletin = [
        {
            "nesine_code": "401",
            "home": "Leganes",
            "away": "Burgos",
            "league": "La Liga 2",
            "country": "Spain",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.20, 3.00, 3.30),
        }
    ]
    ui_snap_target = tmp_path / "ui_snapshot.json"

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch(
            "scripts.run_daily_prototype.fetch_and_scan_live_propline",
            return_value={"fixtures": [], "nesine_matched_fixtures": 0, "signals": []},
        ),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=[]),
        patch("export_snapshot.generate_ui_snapshot", return_value=ui_snap_target) as mock_gen,
    ):
        report = run_daily_pipeline(
            output_json=tmp_path / "proto.json",
            sync_ui_snapshot=True,
            ui_snapshot_path=ui_snap_target,
        )

    mock_gen.assert_called_once_with(output_file=ui_snap_target)
    assert report["summary"]["ui_snapshot_path"] == str(ui_snap_target)


def test_run_daily_pipeline_vetoes_sub_145_heavy_favorite_dust(tmp_path: Path):
    """Low-odds heavy favorite signals (<1.45) and extreme >6.50 outliers are rejected."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=2)
    bulletin = [
        {
            "nesine_code": "501",
            "home": "HeavyFav",
            "away": "Underdog",
            "league": "UEFA",
            "country": "International",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (1.18, 6.20, 12.0),
        }
    ]
    sharp_payload = {
        "fixtures": [{"home": "HeavyFav", "away": "Underdog"}],
        "nesine_matched_fixtures": 1,
        "signals": [
            {
                "event_id": "ev_dust",
                "league": "UEFA",
                "home": "HeavyFav",
                "away": "Underdog",
                "market": "1X2",
                "outcome": "HOME",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sharp_odds": 1.12,
                "soft_odds": 1.18,
                "fair_prob": 0.89,
                "fair_odds": 1.12,
                "edge_pct": 5.0,
                "nesine_code": "501",
                "mbs": 1,
            }
        ],
    }
    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", return_value=sharp_payload),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=[]),
    ):
        report = run_daily_pipeline(output_json=tmp_path / "dust.json")

    assert report["summary"]["signals_count"] == 0


def test_run_daily_pipeline_builds_honest_fair_odds_comparison_even_without_positive_ev(tmp_path: Path):
    """When Nesine margin makes EV negative, report transparent fair-odds rows with honest labels."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=3)
    bulletin = [
        {
            "nesine_code": "601",
            "home": "Arjantin",
            "away": "Uruguay",
            "league": "Hazırlık",
            "country": "International",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 2,
            "nesine_1x2": (1.36, 3.40, 4.84),
            "nesine_ou25": (1.80, 1.72),
        }
    ]
    sharp_payload = {
        "fixtures": [
            {
                "nesine_code": "601",
                "home": "Argentina",
                "away": "Uruguay",
                "league": "FIFA Friendlies",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "nesine_1x2": [1.36, 3.40, 4.84],
                "nesine_ou25": [1.80, 1.72],
                "shin_probs_1x2": [0.619, 0.232, 0.149],
                "shin_fair_1x2": [1.62, 4.31, 6.71],
                "shin_probs_ou25": [0.49, 0.51],
                "shin_fair_ou25": [2.04, 1.96],
            }
        ],
        "nesine_matched_fixtures": 1,
        "signals": [],
    }

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", return_value=sharp_payload),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", return_value=[]),
    ):
        report = run_daily_pipeline(output_json=tmp_path / "fair_board.json")

    assert report["summary"]["signals_count"] == 0
    assert report["summary"]["fair_comparison_count"] == 5
    rows = report["fair_odds_comparison"]
    assert all(r["honest_tag"] == "NEGATİF EV (YÜKSEK NESİNE MARJI)" for r in rows)
    assert rows[0]["nesine_overround_pct"] > 110.0


def test_engine1_vetoed_when_sharp_consensus_negative_ev_and_kept_when_positive(tmp_path: Path):
    """Engine 1 signals contradicted by sharp fair odds (<0% EV) are vetoed; confirmed ones stay."""
    now_trt = datetime.now(TRT_TZ)
    valid_dt = now_trt + timedelta(hours=3)
    bulletin = [
        {
            "nesine_code": "701",
            "home": "Almeria",
            "away": "Andorra",
            "league": "La Liga 2",
            "country": "Spain",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (1.56, 3.40, 3.95),
        },
        {
            "nesine_code": "702",
            "home": "Leganes",
            "away": "Burgos",
            "league": "La Liga 2",
            "country": "Spain",
            "date_str": valid_dt.strftime("%d.%m.%Y"),
            "time_str": valid_dt.strftime("%H:%M"),
            "mbs": 1,
            "nesine_1x2": (2.15, 3.10, 3.10),
        },
    ]

    def _fake_eval(match, min_edge_pct=4.0):
        if match["nesine_code"] == "701":
            return [
                {
                    "match": "Almeria vs Andorra",
                    "time": valid_dt.strftime("%H:%M"),
                    "mbs": 1,
                    "market": "1X2",
                    "selection": "MS 2",
                    "book_odd": 3.95,
                    "fair_odd": 3.31,
                    "prob": 0.3024,
                    "edge_pct": 19.4,
                    "tier": "TIER_2_VALUE",
                },
                {
                    "match": "Almeria vs Andorra",
                    "time": valid_dt.strftime("%H:%M"),
                    "mbs": 1,
                    "market": "Çifte Şans",
                    "selection": "X2 (Beraberlik & Deplasman)",
                    "book_odd": 2.31,
                    "fair_odd": 1.87,
                    "prob": 0.5341,
                    "edge_pct": 23.4,
                    "tier": "TIER_2_VALUE",
                },
            ]
        return [
            {
                "match": "Leganes vs Burgos",
                "time": valid_dt.strftime("%H:%M"),
                "mbs": 1,
                "market": "1X2",
                "selection": "MS 1",
                "book_odd": 2.15,
                "fair_odd": 1.85,
                "prob": 0.54,
                "edge_pct": 16.1,
                "tier": "TIER_2_VALUE",
            }
        ]

    sharp_payload = {
        "fixtures": [
            {
                "nesine_code": "701",
                "home": "UD Almeria",
                "away": "FC Andorra",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Sharp strongly favors Almeria (59.6%), so MS 2 (0.18*3.95-1=-28.9%) and X2 (0.404*2.31-1=-6.7%) are -EV
                "shin_probs_1x2": [0.596, 0.224, 0.180],
            },
            {
                "nesine_code": "702",
                "home": "Leganes",
                "away": "Burgos",
                "kickoff": (valid_dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Sharp estimates P(MS 1)=0.48 -> 0.48 * 2.15 - 1 = +3.2% EV (survives!)
                "shin_probs_1x2": [0.480, 0.280, 0.240],
            },
        ],
        "nesine_matched_fixtures": 2,
        "signals": [],
    }

    with (
        patch("scripts.run_daily_prototype.fetch_nesine_live_bulletin", return_value=bulletin),
        patch("scripts.run_daily_prototype.fetch_and_scan_live_propline", return_value=sharp_payload),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.load_or_train"),
        patch("scripts.run_daily_prototype.TeamStrengthEngine.evaluate_live_fixture", side_effect=_fake_eval),
    ):
        report = run_daily_pipeline(output_json=tmp_path / "sharp_veto.json")

    assert report["summary"]["engine1_raw_signals_count"] == 3
    assert report["summary"]["engine1_vetoed_by_sharp_count"] == 2
    assert report["summary"]["engine1_signals_count"] == 1
    assert report["summary"]["signals_count"] == 1
    surviving = report["signals"][0]
    assert surviving["match"] == "Leganes vs Burgos"
    assert surviving["sharp_edge_pct"] == 3.2
    assert surviving["sharp_fair_odd"] == 2.08
    assert report["recommended_coupon"] is not None
    assert [leg["match"] for leg in report["recommended_coupon"]["legs"]] == ["Leganes vs Burgos"]


def test_merge_engine_signals_limits_corners_to_highest_ev_per_match():
    from scripts.run_daily_prototype import _merge_engine_signals

    raw_signals = [
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "market": "Korner 9.5",
            "selection": "Korner 9.5 ÜST",
            "book_odd": 1.80,
            "prob": 0.589,
            "edge_pct": 6.07,
            "source_engine": "team_strength",
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "market": "Korner 10.5",
            "selection": "Korner 10.5 ÜST",
            "book_odd": 2.32,
            "prob": 0.478,
            "edge_pct": 10.92,
            "source_engine": "team_strength",
        },
        {
            "home": "Hollanda",
            "away": "Yunanistan",
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 1.65,
            "prob": 0.65,
            "edge_pct": 7.25,
            "source_engine": "team_strength",
        },
        {
            "home": "Belçika",
            "away": "İtalya",
            "market": "Korner 8.5",
            "selection": "Korner 8.5 ÜST",
            "book_odd": 1.72,
            "prob": 0.62,
            "edge_pct": 6.64,
            "source_engine": "team_strength",
        },
    ]

    merged = _merge_engine_signals(raw_signals)
    hol_corners = [s for s in merged if s["home"] == "Hollanda" and "Korner" in s["market"]]
    assert len(hol_corners) == 1
    assert hol_corners[0]["market"] == "Korner 10.5"
    assert any(s["home"] == "Hollanda" and s["market"] == "1X2" for s in merged)
    assert any(s["home"] == "Belçika" and s["market"] == "Korner 8.5" for s in merged)


def test_build_uncorrelated_coupon_rejects_negative_ev_instead_of_forcing_stake():
    optimizer = DiscreteKellyOptimizer()
    neg_ev_signals = [
        {
            "match": "TeamX vs TeamY",
            "kickoff_trt": "15.11 20:00",
            "mbs": 1,
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 1.90,
            "fair_odd": 2.10,
            "prob": 0.45,
            "edge_pct": -14.5,
            "tier": "TIER_2_VALUE",
        }
    ]
    assert build_uncorrelated_coupon(neg_ev_signals, optimizer, bankroll=1000.0, min_stake=50.0) is None



