"""Unit tests for sports-engine/src/steam_tracker.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from steam_tracker import PinnacleSteamTracker, compute_market_steam  # noqa: E402


def test_compute_market_steam_detects_draw_shortening():
    # Opening Pinnacle 1X2: Draw at 3.50; Current Pinnacle 1X2: Draw steamed down to 3.10
    metrics = compute_market_steam(
        event_id="ev_101",
        market="1X2",
        outcomes=("HOME", "DRAW", "AWAY"),
        open_odds=(2.20, 3.50, 3.40),
        current_odds=(2.35, 3.10, 3.55),
        devig_method="shin",
        min_drift_pp=0.5,
    )
    draw_m = metrics["DRAW"]
    assert draw_m.is_steam_confirmed is True
    assert draw_m.odds_delta == pytest.approx(-0.40, abs=1e-3)
    assert draw_m.odds_drop_pct > 10.0
    assert draw_m.steam_drift_pp > 3.0

    # Home drifted out, so not steam confirmed
    assert metrics["HOME"].is_steam_confirmed is False
    assert metrics["HOME"].odds_delta > 0


def test_pinnacle_steam_tracker_persists_baseline_and_tracks_movement(tmp_path):
    tracker = PinnacleSteamTracker(snapshots_dir=tmp_path)

    # First capture: establishes baseline
    res1 = tracker.record_and_evaluate_fixture(
        event_id="631919",
        league="İtalya Serie B (I2)",
        home="Cremonese",
        away="Benevento",
        kickoff="2026-10-31T14:00:00Z",
        pinnacle_1x2=(2.84, 3.30, 2.68),
        pinnacle_ou25=(2.06, 1.794),
        captured_at_utc="2026-10-29T08:00:00Z",
    )
    assert res1["snapshots_count"] == 1
    assert res1["steam_1x2"]["DRAW"]["is_steam_confirmed"] is False
    tracker.write_snapshot_archive("2026-10-29T08:00:00Z", 1)

    # Reload from disk and record second snapshot where Draw steamed to 3.02
    tracker2 = PinnacleSteamTracker(snapshots_dir=tmp_path)
    res2 = tracker2.record_and_evaluate_fixture(
        event_id="631919",
        league="İtalya Serie B (I2)",
        home="Cremonese",
        away="Benevento",
        kickoff="2026-10-31T14:00:00Z",
        pinnacle_1x2=(2.95, 3.02, 2.75),
        pinnacle_ou25=(2.14, 1.72),
        captured_at_utc="2026-10-29T10:00:00Z",
    )
    assert res2["snapshots_count"] == 2
    assert res2["open_1x2"] == [2.84, 3.3, 2.68]
    assert res2["steam_1x2"]["DRAW"]["is_steam_confirmed"] is True
    assert res2["steam_1x2"]["DRAW"]["steam_drift_pp"] > 2.0
    assert res2["steam_ou25"]["UNDER_2.5"]["is_steam_confirmed"] is True

