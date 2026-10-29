"""Unit tests for Live Monitor Daemon."""

from unittest.mock import patch

from live_monitor_daemon import run_single_scan_cycle, start_monitor_loop


@patch("live_monitor_daemon.build_html")
@patch("live_monitor_daemon.fetch_and_scan_live_propline")
def test_run_single_scan_cycle(mock_fetch, mock_build):
    mock_fetch.return_value = {
        "leagues_scanned": 28,
        "fixtures_with_pinnacle": 50,
        "nesine_matched_fixtures": 45,
        "positive_ev_signals_count": 2,
        "steam_confirmed_signals_count": 1,
    }

    res = run_single_scan_cycle(settle_espn=False)

    assert res["fixtures_with_pinnacle"] == 50
    assert res["nesine_matched_fixtures"] == 45
    mock_fetch.assert_called_once_with(settle_espn=False)
    mock_build.assert_called_once()


@patch("live_monitor_daemon.time.sleep", return_value=None)
@patch("live_monitor_daemon.run_single_scan_cycle")
def test_start_monitor_loop_max_cycles(mock_run, mock_sleep):
    mock_run.return_value = {}

    start_monitor_loop(interval_sec=10, max_cycles=3)

    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 2
