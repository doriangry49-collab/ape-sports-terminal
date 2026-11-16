"""Deterministic Offline Integration Test Suite for Milestone 2.

Covers:
1. FastAPI Gateway Live Integration & Security (F4):
   - Authentication (401 Missing, 403 Invalid, 200 Authorized).
   - /api/v1/health (verifies dynamic heartbeat loading from output/daemon_heartbeat.json).
   - /api/v1/signals/active (verifies loading from ui/data/sports_intelligence_snapshot.json and min_edge filtering).
   - /api/v1/signals/ledger (verifies paper trading performance metrics).
   - /api/v1/pricing/devig (Shin, power, multiplicative devigging and Kolmogorov probabilities).
2. Live Monitor Daemon Integration & Replay (F5):
   - Deterministic offline single cycle using replayed signals and feeds.
   - Smooth execution of export_snapshot.generate_ui_snapshot() without ModuleNotFoundError.
   - Atomic persistence of output/daemon_heartbeat.json.
   - Notification dispatch and deduplication lifecycle.
   - Corner signal dispatch queue prioritization.
3. Atomic UI Snapshot Pipeline (F6):
   - Atomic snapshot replacement using NamedTemporaryFile + os.replace.
   - Snapshot schema integrity and downstream consumption by FastAPI Gateway.
4. Constitutional Compliance (GEMINI.md):
   - SPEC-0012: Fail-closed error handling (no synthetic odds on network failure; 422 on invalid odds).
   - SPEC-0013: Kickoff window validation (kickoff > now + 3m; fail-closed on past/invalid dates).
   - SPEC-0014: Maximum 12-hour lead time limit (kickoff <= now + 12h).
   - SPEC-0015: Minimum 50.0 TL stake enforcement.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure src and ui are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
UI_PATH = PROJECT_ROOT / "ui"

for p in (str(SRC_PATH), str(PROJECT_ROOT), str(UI_PATH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from export_snapshot import generate_ui_snapshot  # noqa: E402

from api.main import app  # noqa: E402
from closing_line_freeze import check_fixture_kickoff_window, validate_coupon_stake  # noqa: E402
from live_monitor_daemon import (  # noqa: E402
    TRT_TZ,
    parse_match_kickoff,
    prioritize_dispatch_queue,
    run_single_scan_cycle,
)
from live_stale_line_adapter import (  # noqa: E402
    AdapterError,
    fetch_nesine_live_bulletin,
)

VALID_API_KEY = "ape_test_key_master"
AUTH_HEADERS = {"X-API-Key": VALID_API_KEY}


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def api_client() -> TestClient:
    """FastAPI TestClient instance."""
    return TestClient(app)


@pytest.fixture
def isolated_offline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides isolated filesystem paths for daemon outputs, snapshots, and ledgers."""
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    ui_data_dir = tmp_path / "ui" / "data"
    ui_data_dir.mkdir(parents=True, exist_ok=True)

    heartbeat_file = out_dir / "daemon_heartbeat.json"
    alerts_file = out_dir / "active_alerts.json"
    snapshot_file = ui_data_dir / "sports_intelligence_snapshot.json"
    ledger_file = out_dir / "paper_trading_ledger.csv"

    # Seed heartbeat
    initial_heartbeat = {
        "status": "HEALTHY",
        "last_cycle_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": 1.25,
        "leagues_scanned": 28,
        "fixtures_scanned": 42,
        "nesine_matched": 38,
        "positive_ev_signals": 4,
        "steam_confirmed_signals": 1,
        "new_alerts_in_cycle": 0,
        "total_seen_alerts": 100,
    }
    heartbeat_file.write_text(json.dumps(initial_heartbeat, indent=2), encoding="utf-8")

    # Patch daemon paths
    import live_monitor_daemon
    monkeypatch.setattr(live_monitor_daemon, "HEARTBEAT_JSON", heartbeat_file)
    monkeypatch.setattr(live_monitor_daemon, "ALERTS_JSON", alerts_file)
    monkeypatch.setattr(live_monitor_daemon, "LEDGER_CSV", ledger_file)
    monkeypatch.setattr(live_monitor_daemon, "LOG_FILE", out_dir / "live_monitor.log")

    return {
        "tmp_path": tmp_path,
        "out_dir": out_dir,
        "ui_data_dir": ui_data_dir,
        "heartbeat_file": heartbeat_file,
        "alerts_file": alerts_file,
        "snapshot_file": snapshot_file,
        "ledger_file": ledger_file,
        "initial_heartbeat": initial_heartbeat,
    }


# =====================================================================
# SECTION 1: FASTAPI GATEWAY ENDPOINTS (Requirement F4)
# =====================================================================

class TestFastApiGatewayEndpoints:
    """Comprehensive verification of REST API endpoints."""

    def test_auth_missing_api_key_401(self, api_client: TestClient):
        """Missing X-API-Key header returns 401 Unauthorized."""
        res = api_client.get("/api/v1/signals/active")
        assert res.status_code == 401
        assert "Missing required authentication" in res.json()["detail"]

    def test_auth_invalid_api_key_403(self, api_client: TestClient):
        """Invalid X-API-Key header returns 403 Forbidden."""
        res = api_client.get("/api/v1/signals/active", headers={"X-API-Key": "invalid_untrusted_token"})
        assert res.status_code == 403
        assert "Access denied" in res.json()["detail"]

    def test_health_check_reads_actual_heartbeat(self, api_client: TestClient, isolated_offline_env, monkeypatch):
        """Health check returns ONLINE and reflects real daemon_heartbeat.json data."""
        # Update heartbeat with unique values
        custom_heartbeat = {
            "status": "HEALTHY",
            "last_cycle_utc": "2026-11-04T07:00:00Z",
            "elapsed_seconds": 3.14,
            "leagues_scanned": 32,
            "fixtures_scanned": 88,
            "nesine_matched": 79,
            "positive_ev_signals": 7,
            "steam_confirmed_signals": 2,
            "new_alerts_in_cycle": 1,
            "total_seen_alerts": 1250,
        }
        isolated_offline_env["heartbeat_file"].write_text(json.dumps(custom_heartbeat), encoding="utf-8")

        # Patch main.py SPORTS_ENGINE_ROOT to tmp_path
        import api.main as main_mod
        monkeypatch.setattr(main_mod, "SPORTS_ENGINE_ROOT", isolated_offline_env["tmp_path"])

        res = api_client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ONLINE"
        assert data["engine_name"] == "APE Sports-Engine B2B Gateway"
        assert data["daemon_status"]["fixtures_scanned"] == 88
        assert data["daemon_status"]["nesine_matched"] == 79
        assert data["daemon_status"]["leagues_scanned"] == 32
        assert data["daemon_status"]["total_seen_alerts"] == 1250

    def test_health_check_missing_heartbeat_fallback(self, api_client: TestClient, tmp_path: Path, monkeypatch):
        """When heartbeat file is missing or contains non-dict JSON, health check returns gracefully without 500."""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        import api.main as main_mod
        monkeypatch.setattr(main_mod, "SPORTS_ENGINE_ROOT", empty_dir)
        monkeypatch.setattr(main_mod, "ROOT_DIR", empty_dir)

        # 1. Missing heartbeat file
        res = api_client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ONLINE"
        assert "daemon_status" in data
        assert data["daemon_status"]["status"] == "HEALTHY"

        # 2. Non-dict JSON payloads (string, list, null) degrade gracefully without Pydantic ValidationError
        hb_file = empty_dir / "output" / "daemon_heartbeat.json"
        hb_file.parent.mkdir(parents=True, exist_ok=True)
        for raw_payload in ['"CRASHED"', '[1, 2, 3]', 'null', '42']:
            hb_file.write_text(raw_payload, encoding="utf-8")
            res_bad = api_client.get("/api/v1/health")
            assert res_bad.status_code == 200
            data_bad = res_bad.json()
            assert data_bad["status"] == "ONLINE"
            assert isinstance(data_bad["daemon_status"], dict)

    def test_signals_active_reads_snapshot_and_filters_min_edge(
        self, api_client: TestClient, isolated_offline_env, monkeypatch
    ):
        """Active signals endpoint reads snapshot and filters strictly by min_edge."""
        # Create mock snapshot with 3 distinct opportunities
        snapshot_content = {
            "engine_name": "Sports Intelligence Terminal",
            "fixtures": [
                {
                    "fixture_id": "fix_test_01",
                    "competition": "Premier League",
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "selection_display": "Arsenal (Home)",
                            "entry_odds": 2.10,
                            "market_fair_odds": 1.95,
                            "market_no_vig": 0.5128,
                            "model_prob": 0.5400,
                            "edge_pct": 2.72,
                            "ev_roi": 13.4,  # Passes min_edge=3.0, fails min_edge=15.0
                            "half_kelly": 2.8,
                            "shin_margin": 4.5,
                            "kickoff_trt": "2026-11-04 22:00 TRT",
                        }
                    ],
                },
                {
                    "fixture_id": "fix_test_02",
                    "competition": "Trendyol Süper Lig",
                    "home_team": "Galatasaray",
                    "away_team": "Besiktas",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "selection_display": "Galatasaray (Home)",
                            "entry_odds": 1.85,
                            "market_fair_odds": 1.80,
                            "market_no_vig": 0.5556,
                            "model_prob": 0.5650,
                            "edge_pct": 0.94,
                            "ev_roi": 2.1,  # Fails min_edge=3.0
                            "half_kelly": 0.8,
                            "shin_margin": 5.0,
                            "kickoff_trt": "2026-11-04 20:00 TRT",
                        },
                        {
                            "market": "CORNER_OU_9.5",
                            "selection": "OVER",
                            "selection_display": "Over 9.5 Corners",
                            "entry_odds": 1.95,
                            "market_fair_odds": 1.65,
                            "market_no_vig": 0.6061,
                            "model_prob": 0.6200,
                            "edge_pct": 11.0,
                            "ev_roi": 18.2,  # Passes min_edge=3.0 and min_edge=15.0
                            "half_kelly": 4.5,
                            "shin_margin": 4.0,
                            "kickoff_trt": "2026-11-04 20:00 TRT",
                        },
                    ],
                },
            ],
        }

        snap_file = isolated_offline_env["snapshot_file"]
        snap_file.write_text(json.dumps(snapshot_content), encoding="utf-8")

        import api.routes.signals as sig_mod
        monkeypatch.setattr(sig_mod, "SPORTS_ENGINE_ROOT", isolated_offline_env["tmp_path"])

        # 1. Filter min_edge=3.0: should return 2 signals (ev_roi 13.4 and 18.2)
        res = api_client.get("/api/v1/signals/active?min_edge=3.0", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 2
        assert len(data["signals"]) == 2
        selections = [s["selection"] for s in data["signals"]]
        assert "Arsenal (Home)" in selections
        assert "Over 9.5 Corners" in selections

        # 2. Filter min_edge=15.0: should return only 1 signal (ev_roi 18.2)
        res2 = api_client.get("/api/v1/signals/active?min_edge=15.0", headers=AUTH_HEADERS)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["count"] == 1
        assert data2["signals"][0]["selection"] == "Over 9.5 Corners"

        # 3. Filter min_edge=50.0: should return 0 signals
        res3 = api_client.get("/api/v1/signals/active?min_edge=50.0", headers=AUTH_HEADERS)
        assert res3.status_code == 200
        assert res3.json()["count"] == 0

    def test_signals_active_missing_snapshot_returns_empty_list(
        self, api_client: TestClient, tmp_path: Path, monkeypatch
    ):
        """If snapshot file does not exist, endpoint returns count=0 cleanly; corrupted edge isolated."""
        empty_dir = tmp_path / "no_snapshot_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        import api.routes.signals as sig_mod
        monkeypatch.setattr(sig_mod, "SPORTS_ENGINE_ROOT", empty_dir)
        monkeypatch.setattr(sig_mod, "ROOT_DIR", empty_dir)

        # 1. Missing snapshot returns empty list
        res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 0
        assert data["signals"] == []

        # 2. Corrupted edge in one fixture does not discard valid fixture/edge
        ui_data = empty_dir / "ui" / "data"
        ui_data.mkdir(parents=True, exist_ok=True)
        corrupted_snap = {
            "fixtures": [
                {"fixture_id": "bad", "edges": [None, "invalid_edge"]},
                {
                    "fixture_id": "good",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "selection_display": "Valid Selection",
                            "entry_odds": 2.10,
                            "ev_roi": 10.0,
                            "edge_pct": 10.0,
                        }
                    ],
                },
            ]
        }
        (ui_data / "sports_intelligence_snapshot.json").write_text(json.dumps(corrupted_snap), encoding="utf-8")
        res_iso = api_client.get("/api/v1/signals/active?min_edge=3.0", headers=AUTH_HEADERS)
        assert res_iso.status_code == 200
        data_iso = res_iso.json()
        assert data_iso["count"] == 1
        assert data_iso["signals"][0]["selection"] == "Valid Selection"

    def test_signals_ledger_summary_authenticated(self, api_client: TestClient):
        """Ledger endpoint returns valid paper trading performance summary."""
        res = api_client.get("/api/v1/signals/ledger", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert "total_bets" in data
        assert "win_rate_pct" in data
        assert "net_units" in data
        assert "roi_pct" in data
        assert "avg_clv_ratio" in data
        assert isinstance(data["total_bets"], int)
        assert isinstance(data["win_rate_pct"], float)

    def test_pricing_devig_shin_and_other_methods(self, api_client: TestClient):
        """Devigging endpoint correctly computes fair probabilities and margins."""
        # 1. Shin devigging
        payload = {"odds": [2.00, 3.40, 4.00], "method": "shin"}
        res = api_client.post("/api/v1/pricing/devig", json=payload, headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["method"] == "shin"
        assert len(data["probabilities"]) == 3
        assert pytest.approx(sum(data["probabilities"]), abs=1e-3) == 1.0
        assert data["z_parameter"] is not None
        assert data["margin"] > 0

        # 2. Other methods
        for m in ["power", "multiplicative", "additive", "logarithmic"]:
            p = {"odds": [1.90, 3.50, 4.20], "method": m}
            r = api_client.post("/api/v1/pricing/devig", json=p, headers=AUTH_HEADERS)
            assert r.status_code == 200
            assert pytest.approx(sum(r.json()["probabilities"]), abs=1e-3) == 1.0

    def test_pricing_devig_spec0012_invalid_odds_fails_422(self, api_client: TestClient):
        """SPEC-0012: Devigging fails with 422 if any odd <= 1.0."""
        payload = {"odds": [0.90, 3.40, 4.00], "method": "shin"}
        res = api_client.post("/api/v1/pricing/devig", json=payload, headers=AUTH_HEADERS)
        assert res.status_code == 422


# =====================================================================
# SECTION 2: ATOMIC UI SNAPSHOT PIPELINE (Requirement F6)
# =====================================================================

class TestSnapshotProductionPipeline:
    """Verifies ui/export_snapshot.py atomic writing and schema compliance."""

    def test_generate_ui_snapshot_atomic_creation(self, tmp_path: Path):
        """generate_ui_snapshot writes an atomic and valid snapshot file."""
        target_file = tmp_path / "ui_data" / "sports_intelligence_snapshot.json"
        res_path = generate_ui_snapshot(output_file=target_file)

        assert res_path.exists()
        assert res_path == target_file

        data = json.loads(res_path.read_text(encoding="utf-8"))
        assert data["engine_name"] == "Sports Intelligence Terminal"
        assert data["engine_version"] == "v2.0-quant-shin"
        assert "snapshot_timestamp" in data
        assert "fixtures" in data
        assert "daemon_status" in data
        assert "provider_status" in data
        assert isinstance(data["fixtures"], list)
        assert data["total_fixtures"] == len(data["fixtures"])

        # Check that no leftover temporary files remain in the target directory
        tmp_files = list(target_file.parent.glob("*.tmp*"))
        assert len(tmp_files) == 0, f"Found uncleaned temp files: {tmp_files}"

    def test_generated_snapshot_contains_valid_fixtures_and_edges(self, tmp_path: Path):
        """Generated snapshot has valid fixture objects and calculable edge arrays."""
        target_file = tmp_path / "test_snapshot.json"
        generate_ui_snapshot(output_file=target_file)

        data = json.loads(target_file.read_text(encoding="utf-8"))
        fixtures = data["fixtures"]
        assert len(fixtures) > 0, "Snapshot should contain fixtures from prediction/odds datasets."

        sample_fixture = fixtures[0]
        assert "fixture_id" in sample_fixture
        assert "home_team" in sample_fixture
        assert "away_team" in sample_fixture
        assert "competition" in sample_fixture
        assert "edges" in sample_fixture
        assert isinstance(sample_fixture["edges"], list)

    def test_gateway_consumes_generated_snapshot_seamlessly(
        self, api_client: TestClient, tmp_path: Path, monkeypatch
    ):
        """End-to-end: Generated snapshot is consumed by FastAPI Gateway /signals/active."""
        ui_dir = tmp_path / "ui" / "data"
        ui_dir.mkdir(parents=True, exist_ok=True)
        snap_path = ui_dir / "sports_intelligence_snapshot.json"
        generate_ui_snapshot(output_file=snap_path)

        import api.routes.signals as sig_mod
        monkeypatch.setattr(sig_mod, "SPORTS_ENGINE_ROOT", tmp_path)

        res = api_client.get("/api/v1/signals/active?min_edge=0.0", headers=AUTH_HEADERS)
        assert res.status_code == 200
        body = res.json()
        assert "count" in body
        assert isinstance(body["signals"], list)
        # If there are active edges, each must have valid schema fields
        for sig in body["signals"]:
            assert "fixture_id" in sig
            assert "league" in sig
            assert "selection" in sig
            assert "offered_odds" in sig
            assert sig["offered_odds"] > 0


# =====================================================================
# SECTION 3: LIVE MONITOR DAEMON SCAN CYCLE (Requirement F5)
# =====================================================================

class TestLiveMonitorDaemonScanCycle:
    """Tests the daemon single scan cycle using recorded replay data offline."""

    @patch("live_monitor_daemon.send_telegram_message", return_value=True)
    @patch("live_monitor_daemon.send_windows_toast", return_value=True)
    @patch("live_monitor_daemon.build_html")
    @patch("live_monitor_daemon.fetch_and_scan_live_propline")
    def test_daemon_scan_cycle_end_to_end_offline(
        self,
        mock_fetch,
        mock_build,
        mock_toast,
        mock_tg,
        isolated_offline_env,
    ):
        """Daemon runs single scan cycle offline, produces heartbeat, and calls generate_ui_snapshot."""
        future_ko = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        replayed_signals = [
            {
                "home": "Arsenal",
                "away": "Chelsea",
                "market": "1X2",
                "outcome": "MS 1",
                "soft_book": "nesine",
                "soft_odds": 2.10,
                "fair_odds": 1.90,
                "edge_pct": 10.5,
                "prob": 0.526,
                "mbs": 1,
                "kickoff": future_ko,
                "is_steam_confirmed": True,
            },
            {
                "home": "Liverpool",
                "away": "Man City",
                "market": "CORNER_OU_9.5",
                "outcome": "Ust 9.5 Korner",
                "soft_book": "nesine",
                "soft_odds": 1.95,
                "fair_odds": 1.70,
                "edge_pct": 14.7,
                "prob": 0.588,
                "mbs": 1,
                "kickoff": future_ko,
                "is_steam_confirmed": False,
            },
        ]

        mock_fetch.return_value = {
            "leagues_scanned": 28,
            "fixtures_with_pinnacle": 50,
            "nesine_matched_fixtures": 45,
            "positive_ev_signals_count": 2,
            "steam_confirmed_signals_count": 1,
            "signals": replayed_signals,
        }

        # Run single scan cycle with external network settling disabled
        cycle_result = run_single_scan_cycle(
            settle_espn=False,
            enable_telegram=True,
            scan_quant=False,
        )

        assert cycle_result["fixtures_with_pinnacle"] == 50
        assert cycle_result["nesine_matched_fixtures"] == 45
        mock_build.assert_called_once()

        # Verify that daemon heartbeat was written atomically
        hb_file = isolated_offline_env["heartbeat_file"]
        assert hb_file.exists()
        hb_data = json.loads(hb_file.read_text(encoding="utf-8"))
        assert hb_data["status"] == "HEALTHY"
        assert hb_data["fixtures_scanned"] == 50
        assert hb_data["nesine_matched"] == 45
        assert hb_data["new_alerts_in_cycle"] == 2

        # Verify alerts file updated
        alerts_file = isolated_offline_env["alerts_file"]
        assert alerts_file.exists()
        alerts_data = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert len(alerts_data) == 2

        # Verify notifications dispatched
        assert mock_toast.call_count >= 1
        assert mock_tg.call_count >= 1

    @patch("live_monitor_daemon.send_telegram_message", return_value=True)
    @patch("live_monitor_daemon.send_windows_toast", return_value=True)
    @patch("live_monitor_daemon.build_html")
    @patch("live_monitor_daemon.fetch_and_scan_live_propline")
    def test_daemon_alert_deduplication_across_cycles(
        self,
        mock_fetch,
        mock_build,
        mock_toast,
        mock_tg,
        isolated_offline_env,
    ):
        """Daemon does not re-alert identical signals across consecutive cycles."""
        future_ko = (datetime.now(UTC) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

        signal = {
            "home": "Juventus",
            "away": "Milan",
            "market": "1X2",
            "outcome": "MS 1",
            "soft_book": "nesine",
            "soft_odds": 2.20,
            "fair_odds": 1.95,
            "edge_pct": 12.8,
            "prob": 0.512,
            "mbs": 1,
            "kickoff": future_ko,
            "is_steam_confirmed": True,
        }

        mock_fetch.return_value = {
            "leagues_scanned": 1,
            "fixtures_with_pinnacle": 1,
            "nesine_matched_fixtures": 1,
            "positive_ev_signals_count": 1,
            "steam_confirmed_signals_count": 1,
            "signals": [signal],
        }

        # Cycle 1: Brand new signal -> alerts fired
        run_single_scan_cycle(settle_espn=False, enable_telegram=True, scan_quant=False)
        toast_calls_cycle1 = mock_toast.call_count
        tg_calls_cycle1 = mock_tg.call_count
        assert toast_calls_cycle1 == 1
        assert tg_calls_cycle1 == 1

        # Cycle 2: Exact same signal -> no new alerts fired
        run_single_scan_cycle(settle_espn=False, enable_telegram=True, scan_quant=False)
        assert mock_toast.call_count == toast_calls_cycle1
        assert mock_tg.call_count == tg_calls_cycle1

    def test_prioritize_dispatch_queue_orders_corners_first(self):
        """Corner signals are prioritized first to prevent longshot crowding."""
        # 1. Turkish outcome name with English market name
        signals = [
            {"market": "1X2", "home": "A", "away": "B", "outcome": "MS 1"},
            {"market": "CORNER_OU_9.5", "home": "C", "away": "D", "outcome": "Ust 9.5 Korner"},
            {"market": "OU_2.5", "home": "E", "away": "F", "outcome": "Ust 2.5"},
        ]
        sorted_sigs = prioritize_dispatch_queue(signals)
        assert sorted_sigs[0]["market"] == "CORNER_OU_9.5"

        # 2. Pure English market name without Turkish keyword in outcome
        signals_en = [
            {"market": "1X2", "home": "A", "away": "B", "outcome": "Home Win"},
            {"market": "CORNER_OU_9.5", "home": "C", "away": "D", "outcome": "Over 9.5"},
            {"market": "OU_2.5", "home": "E", "away": "F", "outcome": "Over 2.5 Goals"},
        ]
        sorted_en = prioritize_dispatch_queue(signals_en)
        assert sorted_en[0]["market"] == "CORNER_OU_9.5"

        # 3. Explicit is_corner flag
        signals_flag = [
            {"market": "1X2", "home": "A", "away": "B", "outcome": "Home"},
            {"market": "TOTAL_CORNERS", "home": "C", "away": "D", "outcome": "Over 10", "is_corner": True},
        ]
        sorted_flag = prioritize_dispatch_queue(signals_flag)
        assert sorted_flag[0]["market"] == "TOTAL_CORNERS"


# =====================================================================
# SECTION 4: CONSTITUTIONAL COMPLIANCE (GEMINI.md Rules)
# =====================================================================

class TestConstitutionalCompliance:
    """Verifies SPEC-0012, SPEC-0013, SPEC-0014, and SPEC-0015."""

    def test_spec0012_fail_closed_on_network_adapter_error(self, monkeypatch):
        """SPEC-0012: Network failure raises AdapterError; no synthetic fallback."""
        monkeypatch.setattr("time.sleep", lambda s: None)
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.side_effect = urllib.error.URLError("Connection refused")
            with pytest.raises(AdapterError):
                fetch_nesine_live_bulletin(max_retries=1, raise_on_error=True)
            # In default non-raising mode, returns empty list fail-closed (no synthetic odds)
            res = fetch_nesine_live_bulletin(max_retries=1, raise_on_error=False)
            assert res == []

    def test_spec0013_kickoff_min_lead_time_enforcement(self):
        """SPEC-0013: Match kickoff must be > now + 3 minutes."""
        now_trt = datetime.now(TRT_TZ)

        # 1. Past match: rejected
        past_dt = now_trt - timedelta(minutes=30)
        dt, iso = parse_match_kickoff(past_dt.strftime("%d.%m.%Y"), past_dt.strftime("%H:%M"), now_trt=now_trt)
        assert dt is None and iso is None

        # 2. Starting in 1 minute: rejected (<= now + 3m)
        t_1m = now_trt + timedelta(minutes=1)
        dt, iso = parse_match_kickoff(t_1m.strftime("%d.%m.%Y"), t_1m.strftime("%H:%M"), now_trt=now_trt)
        assert dt is None and iso is None

        # 3. Starting in 2.5 minutes: rejected (<= now + 3m)
        t_2m30s = now_trt + timedelta(seconds=150)
        dt, iso = parse_match_kickoff(t_2m30s.strftime("%d.%m.%Y"), t_2m30s.strftime("%H:%M"), now_trt=now_trt)
        assert dt is None and iso is None

        # 4. Starting in 15 minutes: accepted
        t_15m = now_trt + timedelta(minutes=15)
        dt, iso = parse_match_kickoff(t_15m.strftime("%d.%m.%Y"), t_15m.strftime("%H:%M"), now_trt=now_trt)
        assert dt is not None and iso is not None

        # 5. Missing date/time fails closed
        assert parse_match_kickoff(None, "20:00") == (None, None)
        assert parse_match_kickoff("04.11.2026", None) == (None, None)
        assert parse_match_kickoff("", "") == (None, None)

    def test_spec0014_kickoff_max_12h_window_enforcement(self):
        """SPEC-0014: Match kickoff must be <= now + 12 hours."""
        now_trt = datetime.now(TRT_TZ)

        # 1. Starting in 11 hours: accepted
        t_11h = now_trt + timedelta(hours=11)
        dt, iso = parse_match_kickoff(t_11h.strftime("%d.%m.%Y"), t_11h.strftime("%H:%M"), now_trt=now_trt)
        assert dt is not None and iso is not None

        # 2. Starting in 13 hours: rejected (> now + 12h)
        t_13h = now_trt + timedelta(hours=13)
        dt, iso = parse_match_kickoff(t_13h.strftime("%d.%m.%Y"), t_13h.strftime("%H:%M"), now_trt=now_trt)
        assert dt is None and iso is None

        # 3. Starting in 24 hours: rejected
        t_24h = now_trt + timedelta(hours=24)
        dt, iso = parse_match_kickoff(t_24h.strftime("%d.%m.%Y"), t_24h.strftime("%H:%M"), now_trt=now_trt)
        assert dt is None and iso is None

    def test_spec0013_spec0014_fixture_kickoff_window_validator(self):
        """Constitutional validator check_fixture_kickoff_window enforces both SPEC-0013 & SPEC-0014."""
        now_utc = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

        # 1. Inside valid window (kickoff in 2 hours)
        ko_valid = now_utc + timedelta(hours=2)
        valid, msg = check_fixture_kickoff_window(ko_valid, reference_now_utc=now_utc)
        assert valid is True
        assert msg == "VALID_WINDOW"

        # 2. Starting in 2 minutes (fails SPEC-0013)
        ko_too_soon = now_utc + timedelta(minutes=2)
        valid, msg = check_fixture_kickoff_window(ko_too_soon, reference_now_utc=now_utc)
        assert valid is False
        assert "SPEC-0013" in msg

        # 3. Starting in 14 hours (fails SPEC-0014)
        ko_too_far = now_utc + timedelta(hours=14)
        valid, msg = check_fixture_kickoff_window(ko_too_far, reference_now_utc=now_utc)
        assert valid is False
        assert "SPEC-0014" in msg

    def test_spec0015_minimum_stake_enforcement(self):
        """SPEC-0015: Minimum coupon stake must be at least 50.0 TL."""
        # 1. 50.0 TL is strictly allowed
        assert validate_coupon_stake(50.0) is True

        # 2. Higher stakes are allowed
        assert validate_coupon_stake(150.0) is True

        # 3. Below 50.0 TL raises ValueError fail-closed
        with pytest.raises(ValueError) as excinfo:
            validate_coupon_stake(49.99)
        assert "SPEC-0015 Violation" in str(excinfo.value)

        with pytest.raises(ValueError):
            validate_coupon_stake(10.0)

        with pytest.raises(ValueError):
            validate_coupon_stake(0.0)
