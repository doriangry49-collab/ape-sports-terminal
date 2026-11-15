"""Unit tests for Live Monitor Daemon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from live_monitor_daemon import run_single_scan_cycle, send_windows_toast, start_monitor_loop


@patch("live_monitor_daemon.build_html")
@patch("live_monitor_daemon.fetch_and_scan_live_propline")
def test_run_single_scan_cycle(mock_fetch, mock_build, tmp_path, monkeypatch):
    monkeypatch.setattr("live_monitor_daemon.ALERTS_JSON", tmp_path / "active_alerts.json")
    monkeypatch.setattr("live_monitor_daemon.HEARTBEAT_JSON", tmp_path / "daemon_heartbeat.json")
    monkeypatch.setattr("live_monitor_daemon.LEDGER_CSV", tmp_path / "paper_trading_ledger.csv")
    mock_fetch.return_value = {
        "leagues_scanned": 28,
        "fixtures_with_pinnacle": 50,
        "nesine_matched_fixtures": 45,
        "positive_ev_signals_count": 2,
        "steam_confirmed_signals_count": 1,
        "signals": [],
    }

    res = run_single_scan_cycle(settle_espn=False, scan_quant=False)

    assert res["fixtures_with_pinnacle"] == 50
    assert res["nesine_matched_fixtures"] == 45
    mock_fetch.assert_called_once_with(settle_espn=False)
    mock_build.assert_called_once()


@patch("live_monitor_daemon.time.sleep", return_value=None)
@patch("live_monitor_daemon.run_single_scan_cycle")
def test_start_monitor_loop_max_cycles(mock_run, mock_sleep):
    mock_run.return_value = {}

    start_monitor_loop(interval_sec=10, max_cycles=3, enable_telegram=False)

    assert mock_run.call_count == 3
    assert mock_sleep.call_count >= 2


@patch("live_monitor_daemon.send_windows_toast")
@patch("live_monitor_daemon.build_html")
@patch("live_monitor_daemon.fetch_and_scan_live_propline")
def test_alert_deduplication_and_toast(mock_fetch, mock_build, mock_toast, tmp_path, monkeypatch):
    test_alerts_file = tmp_path / "active_alerts.json"
    test_heartbeat = tmp_path / "daemon_heartbeat.json"
    test_ledger = tmp_path / "paper_trading_ledger.csv"
    monkeypatch.setattr("live_monitor_daemon.ALERTS_JSON", test_alerts_file)
    monkeypatch.setattr("live_monitor_daemon.HEARTBEAT_JSON", test_heartbeat)
    monkeypatch.setattr("live_monitor_daemon.LEDGER_CSV", test_ledger)

    signal_sample = {
        "home": "Arsenal",
        "away": "Chelsea",
        "market": "1X2",
        "outcome": "MS 1",
        "soft_book": "nesine",
        "soft_odds": 2.10,
        "edge_pct": 3.45,
        "is_steam_confirmed": True,
        "kickoff": (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    mock_fetch.return_value = {
        "leagues_scanned": 1,
        "fixtures_with_pinnacle": 1,
        "nesine_matched_fixtures": 1,
        "positive_ev_signals_count": 1,
        "steam_confirmed_signals_count": 1,
        "signals": [signal_sample],
    }

    # First cycle: new signal -> toast called
    run_single_scan_cycle(settle_espn=False, scan_quant=False)
    assert mock_toast.call_count == 1
    assert test_alerts_file.exists()
    assert test_heartbeat.exists()

    # Second cycle with exact same signal: duplicate -> toast NOT called again
    run_single_scan_cycle(settle_espn=False, scan_quant=False)
    assert mock_toast.call_count == 1


@patch("subprocess.run")
def test_send_windows_toast_fallback(mock_subproc):
    mock_subproc.return_value = MagicMock(returncode=0)
    assert send_windows_toast("Test", "Message") is True

    mock_subproc.side_effect = Exception("OS Error")
    assert send_windows_toast("Test", "Message") is False


def test_format_signal_telegram():
    from live_monitor_daemon import format_signal_telegram

    sig = {
        "home": "Marsilya",
        "away": "Toulouse",
        "market": "1X2",
        "outcome": "MS 1",
        "soft_odds": 1.67,
        "fair_odds": 1.13,
        "edge_pct": 49.0,
        "prob": 0.887,
        "mbs": 1,
        "time": "22:45",
        "tier": "TIER_1_SHIELD",
        "is_steam_confirmed": True,
    }
    text = format_signal_telegram(sig)
    assert "STEAM ONAYLI" in text
    assert "Marsilya vs Toulouse" in text
    assert "1.67" in text
    assert "TIER 1 KASA KALKANI" in text


def test_is_kickoff_in_future_filters_past_matches():
    from datetime import UTC, datetime, timedelta

    from live_stale_line_adapter import is_kickoff_in_future

    past_time = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_time = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert is_kickoff_in_future(past_time) is False
    assert is_kickoff_in_future(future_time) is True
    assert is_kickoff_in_future(None) is False
    assert is_kickoff_in_future("") is False


@patch("live_monitor_daemon.send_telegram_message")
@patch("live_monitor_daemon.send_windows_toast")
@patch("live_monitor_daemon.build_html")
@patch("live_monitor_daemon.fetch_and_scan_live_propline")
def test_telegram_alert_dispatch(mock_fetch, mock_build, mock_toast, mock_tg, tmp_path, monkeypatch):
    test_alerts_file = tmp_path / "active_alerts.json"
    test_heartbeat = tmp_path / "daemon_heartbeat.json"
    test_ledger = tmp_path / "paper_trading_ledger.csv"
    monkeypatch.setattr("live_monitor_daemon.ALERTS_JSON", test_alerts_file)
    monkeypatch.setattr("live_monitor_daemon.HEARTBEAT_JSON", test_heartbeat)
    monkeypatch.setattr("live_monitor_daemon.LEDGER_CSV", test_ledger)

    signals = [
        {
            "home": f"Team{i}",
            "away": f"Opp{i}",
            "market": "1X2",
            "outcome": "MS 1",
            "soft_book": "nesine",
            "soft_odds": 2.0,
            "fair_odds": 1.5,
            "edge_pct": 33.3,
            "prob": 0.66,
            "mbs": 1,
            "time": "21:00",
            "kickoff": (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_steam_confirmed": False,
        }
        for i in range(5)
    ]
    mock_fetch.return_value = {
        "leagues_scanned": 1,
        "fixtures_with_pinnacle": 5,
        "nesine_matched_fixtures": 5,
        "positive_ev_signals_count": 5,
        "steam_confirmed_signals_count": 0,
        "signals": signals,
    }

    run_single_scan_cycle(settle_espn=False, enable_telegram=True, scan_quant=False)
    # 3 individual messages + 1 digest message for the remaining 2 = 4 total calls
    assert mock_tg.call_count == 4


def test_format_vip_value_signal_telegram():
    from live_monitor_daemon import format_signal_telegram
    from value_engine import ValueSignal

    sig = ValueSignal(
        fixture_id="fix_999",
        league="Premier League",
        home_team="Arsenal",
        away_team="Chelsea",
        kickoff_utc="2026-11-03T18:00:00Z",
        kickoff_trt="2026-11-03 21:00 TRT",
        market="1X2",
        selection="1 (Home)",
        bookmaker="NESINE",
        offered_odds=2.10,
        fair_odds_shin=1.92,
        fair_prob_shin=0.5208,
        model_prob=0.5500,
        edge_pct=2.92,
        ev_roi=15.5,
        half_kelly=3.2,
        shin_margin=4.5,
        shin_z=0.08,
    )
    msg = format_signal_telegram(sig)
    assert "APE QUANT +EV DEĞER SİNYALİ" in msg
    assert "Arsenal* vs *Chelsea*" in msg
    assert "2.10" in msg
    assert "Half-Kelly" in msg
    assert "15.5%" in msg

    # Also test dict format
    sig_dict = sig.to_dict()
    sig_dict["is_value_signal"] = True
    msg_dict = format_signal_telegram(sig_dict)
    assert "APE QUANT +EV DEĞER SİNYALİ" in msg_dict
    assert "Arsenal* vs *Chelsea*" in msg_dict


@patch("live_monitor_daemon.send_telegram_message")
def test_send_telegram_startup_ping(mock_send):
    from live_monitor_daemon import send_telegram_startup_ping

    mock_send.return_value = True
    assert send_telegram_startup_ping() is True
    mock_send.assert_called_once()
    sent_text = mock_send.call_args[0][0]
    assert "APE QUANT VIP SİNYAL MOTORU AKTİF" in sent_text
    assert "Half-Kelly" in sent_text


@patch("live_monitor_daemon.start_telegram_listener_thread")
@patch("live_monitor_daemon.send_telegram_startup_ping")
@patch("live_monitor_daemon.run_single_scan_cycle")
def test_start_monitor_loop_sends_startup_ping(mock_run, mock_ping, mock_thread):
    start_monitor_loop(interval_sec=120, max_cycles=1, enable_telegram=True)
    mock_ping.assert_called_once()
    mock_thread.assert_called_once()
    mock_run.assert_called_once()


def test_prioritize_dispatch_queue_priced_1x2_ahead_of_corners():
    from live_monitor_daemon import prioritize_dispatch_queue

    signals = [
        {"id": "corner_1", "market": "Korner 9.5", "outcome": "Korner 9.5 ÜST", "soft_odds": 1.85, "edge_pct": 12.0, "is_corner": True},
        {"id": "1x2_val", "market": "1X2", "outcome": "MS 1", "soft_odds": 2.40, "edge_pct": 8.5, "is_corner": False},
        {"id": "ou_val", "market": "2.5 Alt/Üst", "outcome": "2.5 Üst", "soft_odds": 1.90, "edge_pct": 15.0, "is_corner": False},
    ]
    ordered = prioritize_dispatch_queue(signals)
    assert [s["id"] for s in ordered] == ["1x2_val", "corner_1", "ou_val"]


def test_pid_lock_prevents_concurrent_instance(tmp_path):
    import os

    from live_monitor_daemon import acquire_daemon_pid_lock, release_daemon_pid_lock

    lock_file = tmp_path / "daemon.pid"
    # First acquisition by current process succeeds
    assert acquire_daemon_pid_lock(lock_file) is True
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    # Re-entrant acquisition by same PID succeeds
    assert acquire_daemon_pid_lock(lock_file) is True

    # Simulate another alive PID holding the lock
    with patch("live_monitor_daemon._is_pid_alive", return_value=True):
        lock_file.write_text("999999", encoding="utf-8")
        assert acquire_daemon_pid_lock(lock_file) is False

    # Simulate stale dead PID -> overwritten by current PID
    with patch("live_monitor_daemon._is_pid_alive", return_value=False):
        lock_file.write_text("999999", encoding="utf-8")
        assert acquire_daemon_pid_lock(lock_file) is True
        assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())

    release_daemon_pid_lock(lock_file)
    assert not lock_file.exists()


def test_is_pid_alive_rejects_recycled_non_python_pid(monkeypatch):
    import os
    import sys

    from live_monitor_daemon import _is_pid_alive

    assert _is_pid_alive(os.getpid()) is True
    assert _is_pid_alive(-1) is False
    assert _is_pid_alive(0) is False

    if sys.platform == "win32":
        # Simulate a PID recycled by Windows to explorer.exe / svchost.exe (still active 259, but non-python image)
        class FakeKernel32:
            def OpenProcess(self, access, inherit, pid):  # noqa: N802
                return 42

            def GetExitCodeProcess(self, handle, exit_code_ptr):  # noqa: N802
                exit_code_ptr._obj.value = 259
                return 1

            def QueryFullProcessImageNameW(self, handle, flags, buf, size_ptr):  # noqa: N802
                buf.value = r"C:\Windows\System32\svchost.exe"
                return 1

            def CloseHandle(self, handle):  # noqa: N802
                return 1

        monkeypatch.setattr("live_monitor_daemon.ctypes.windll.kernel32", FakeKernel32())
        assert _is_pid_alive(12345) is False


def test_clv_alpha_attribution_reads_csv_ledger(tmp_path):
    from clv_alpha_attribution import CLVAlphaAttributionEngine
    from paper_trader import PaperTradingEngine

    csv_path = tmp_path / "paper_trading_ledger.csv"
    out_json = tmp_path / "clv_report.json"
    pt = PaperTradingEngine(ledger_path=csv_path)
    pt.save_rows([
        {
            "signal_id": "2026-11-10_team_a_team_b|1X2|MS 1",
            "event_id": "ev1",
            "captured_at_utc": "2026-11-10T12:00:00Z",
            "kickoff": "2026-11-10T18:00:00Z",
            "league": "Premier League",
            "tier": "TIER_1_SHIELD",
            "home": "Team A",
            "away": "Team B",
            "market": "1X2",
            "outcome": "MS 1",
            "soft_book": "nesine",
            "soft_odds": "2.10",
            "pinnacle_odds_at_bet": "1.95",
            "shin_fair_prob": "0.5128",
            "shin_fair_odds": "1.95",
            "edge_pct": "7.69",
            "kelly_pct": "2.0",
            "steam_drift_pp": "0.0",
            "is_steam_confirmed": "False",
            "latest_pinnacle_fair_odds": "1.88",
            "clv_ratio": "1.117",
            "result_score": "2-1",
            "status": "WON",
            "pnl_units": "1.10",
            "brier_sharp": "0.23",
            "brier_soft": "0.27",
        }
    ])
    clv_eng = CLVAlphaAttributionEngine()
    report = clv_eng.generate_and_export_report(ledger_path=csv_path, output_path=out_json)
    assert report.total_analyzed_trades == 1
    assert report.beat_closing_rate_pct == 100.0
    assert out_json.exists()


def test_parse_match_kickoff_rejects_date_only_without_2000_fallback():
    from live_monitor_daemon import TRT_TZ, parse_match_kickoff

    now_trt = datetime(2026, 11, 15, 11, 0, tzinfo=TRT_TZ)
    assert parse_match_kickoff("15.11.2026", "TBD", now_trt=now_trt) == (None, None)
    assert parse_match_kickoff("15.11.2026", "", now_trt=now_trt) == (None, None)


def test_retired_side_engines_return_empty():
    from live_monitor_daemon import scan_goal_anomalies, scan_odds_patterns

    assert scan_goal_anomalies(bulletin=[{"home": "A", "away": "B"}]) == []
    assert scan_odds_patterns(bulletin=[{"home": "A", "away": "B"}]) == []



