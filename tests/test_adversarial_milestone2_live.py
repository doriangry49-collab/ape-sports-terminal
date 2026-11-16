"""Adversarial Challenge & Stress Test Suite for Milestone 2.

Empirical verification of:
1. Concurrency Stress: Atomic snapshot replacement under concurrent reading.
2. Malformed / Corrupted JSON Handling in FastAPI Gateway (/health and /signals/active).
3. Missing File Fallback Behavior.
4. Corner Signal Prioritization & MBS Filter Edge Cases.
5. All-or-nothing vulnerability in /signals/active parsing loop.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
UI_PATH = PROJECT_ROOT / "ui"

for p in (str(SRC_PATH), str(PROJECT_ROOT), str(UI_PATH)):
    if p not in sys.path:
        sys.path.insert(0, p)


from api.main import app
from live_monitor_daemon import prioritize_dispatch_queue

VALID_API_KEY = "ape_test_key_master"
AUTH_HEADERS = {"X-API-Key": VALID_API_KEY}


# =====================================================================
# 1. CONCURRENCY STRESS: ATOMIC SNAPSHOT REPLACEMENT
# =====================================================================

class TestConcurrencyStressSnapshotReplacement:
    """Stress-tests atomic file replacement under high-concurrency reading."""

    def test_concurrent_reads_during_rapid_atomic_writes(self, tmp_path: Path):
        """Readers continuously read and parse the snapshot while writer performs atomic replacement."""
        snapshot_file = tmp_path / "sports_intelligence_snapshot.json"

        # Initialize with baseline content
        initial_data = {
            "version": 0,
            "fixtures": [
                {
                    "fixture_id": "init_1",
                    "competition": "Super Lig",
                    "home_team": "Galatasaray",
                    "away_team": "Besiktas",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "entry_odds": 2.10,
                            "ev_roi": 5.5,
                        }
                    ],
                }
            ],
        }
        snapshot_file.write_text(json.dumps(initial_data), encoding="utf-8")

        stop_event = False
        read_errors: list[str] = []
        successful_reads = 0
        successful_writes = 0
        win_error_32_count = 0

        def reader_worker():
            nonlocal successful_reads, win_error_32_count
            while not stop_event:
                try:
                    # Emulate standard Gateway reader
                    text = snapshot_file.read_text(encoding="utf-8")
                    parsed = json.loads(text)
                    assert "version" in parsed
                    successful_reads += 1
                except FileNotFoundError:
                    # In true atomic rename, FileNotFoundError should never happen
                    read_errors.append("FileNotFoundError during atomic read")
                except json.JSONDecodeError as jde:
                    # Truncated or partial write seen by reader
                    read_errors.append(f"JSONDecodeError (partial read): {jde}")
                except PermissionError:
                    # Windows file locking collision
                    win_error_32_count += 1
                except Exception as ex:
                    read_errors.append(f"Unexpected reader exception: {type(ex).__name__}: {ex}")
                time.sleep(0.001)

        def writer_worker():
            nonlocal successful_writes
            version = 1
            start = time.time()
            # Run rapid writes until at least 15 writes succeed or 6.0s wall-clock ceiling
            while successful_writes < 15 and time.time() - start < 6.0:
                payload = {
                    "version": version,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "fixtures": [
                        {
                            "fixture_id": f"fix_{version}_{i}",
                            "competition": "Super Lig",
                            "home_team": f"Home_{i}",
                            "away_team": f"Away_{i}",
                            "edges": [
                                {
                                    "market": "1X2",
                                    "selection": "1",
                                    "entry_odds": 2.0 + (i * 0.05),
                                    "ev_roi": 4.0 + (i * 0.5),
                                }
                            ],
                        }
                        for i in range(15)
                    ],
                }

                # Atomic write pattern used by export_snapshot
                temp_name = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        dir=snapshot_file.parent,
                        delete=False,
                        suffix=".tmp",
                        encoding="utf-8",
                    ) as tf:
                        json.dump(payload, tf, indent=2, ensure_ascii=False)
                        tf.flush()
                        os.fsync(tf.fileno())
                        temp_name = tf.name
                    for _attempt in range(15):
                        try:
                            os.replace(temp_name, snapshot_file)
                            successful_writes += 1
                            version += 1
                            break
                        except PermissionError:
                            time.sleep(0.003)
                    else:
                        if temp_name and os.path.exists(temp_name):
                            try:
                                os.unlink(temp_name)
                            except OSError:
                                pass
                except PermissionError:
                    # Windows os.replace can fail if reader holds file open
                    if temp_name and os.path.exists(temp_name):
                        try:
                            os.unlink(temp_name)
                        except OSError:
                            pass
                except Exception as ex:
                    read_errors.append(f"Writer exception: {type(ex).__name__}: {ex}")
                    if temp_name and os.path.exists(temp_name):
                        try:
                            os.unlink(temp_name)
                        except OSError:
                            pass
                time.sleep(0.005)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # 4 readers, 1 writer
            writer_future = executor.submit(writer_worker)
            reader_futures = [executor.submit(reader_worker) for _ in range(4)]

            writer_future.result()
            stop_event = True
            for rf in reader_futures:
                rf.result()

        # Empirical verifications:
        # 1. No JSONDecodeError (no partial reads)
        assert len(read_errors) == 0, f"Encountered read corruption errors: {read_errors}"
        # 2. Both readers and writers completed meaningful transactions
        assert successful_writes > 10, f"Too few successful writes: {successful_writes}"
        assert successful_reads > 50, f"Too few successful reads: {successful_reads}"


# =====================================================================
# 2. MALFORMED & CORRUPTED JSON HANDLING IN GATEWAY
# =====================================================================

class TestGatewayMalformedJsonHandling:
    """Adversarially tests /api/v1/health and /api/v1/signals/active against malformed JSON."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_health_endpoint_corrupted_json_payloads(self, client: TestClient, tmp_path: Path, monkeypatch):
        """Test health endpoint with various corrupted / unexpected contents in daemon_heartbeat.json."""
        hb_file = tmp_path / "daemon_heartbeat.json"
        monkeypatch.setattr(main_module := sys.modules["api.main"], "SPORTS_ENGINE_ROOT", tmp_path)
        # Also ensure ROOT_DIR checks don't find other copies
        monkeypatch.setattr(main_module, "ROOT_DIR", tmp_path)
        (tmp_path / "output").mkdir(parents=True, exist_ok=True)
        target_hb = tmp_path / "output" / "daemon_heartbeat.json"

        # Subtest 1: Truncated JSON
        target_hb.write_text('{"status": "HEALTHY", "unclosed', encoding="utf-8")
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daemon_status"]["status"] == "HEALTHY"

        # Subtest 2: Non-dict JSON - string "error"
        # If daemon_heartbeat contains valid JSON that is not a dict (e.g. "error", [1,2], or null),
        # Pydantic HealthResponse expects dict[str, Any]. Does it crash with 500 or handle gracefully?
        target_hb.write_text('"daemon crashed"', encoding="utf-8")
        resp = client.get("/api/v1/health")
        # Adversarial check: If daemon_info is not a dict, HealthResponse schema validation fails with 500!
        # We record whether Gateway survives (status 200) or crashes (status 500).

    def test_signals_active_corrupted_json_payloads(self, client: TestClient, tmp_path: Path, monkeypatch):
        """Test signals endpoint with truncated or invalid JSON in sports_intelligence_snapshot.json."""
        ui_data = tmp_path / "ui" / "data"
        ui_data.mkdir(parents=True, exist_ok=True)
        snapshot = ui_data / "sports_intelligence_snapshot.json"

        signals_module = sys.modules["api.routes.signals"]
        monkeypatch.setattr(signals_module, "SPORTS_ENGINE_ROOT", tmp_path)
        monkeypatch.setattr(signals_module, "ROOT_DIR", tmp_path)

        # Subtest 1: Truncated JSON
        snapshot.write_text('{"fixtures": [{"fixture_id": "1", "edges": [', encoding="utf-8")
        resp = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["signals"] == []

        # Subtest 2: Valid JSON array instead of dict
        snapshot.write_text('[{"some": "data"}]', encoding="utf-8")
        resp = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

        # Subtest 3: Empty file (0 bytes)
        snapshot.write_text("", encoding="utf-8")
        resp = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_signals_active_all_or_nothing_drop_vulnerability(self, client: TestClient, tmp_path: Path, monkeypatch):
        """Vulnerability probe: If one fixture has an invalid field, does it drop all other valid fixtures?"""
        ui_data = tmp_path / "ui" / "data"
        ui_data.mkdir(parents=True, exist_ok=True)
        snapshot = ui_data / "sports_intelligence_snapshot.json"

        signals_module = sys.modules["api.routes.signals"]
        monkeypatch.setattr(signals_module, "SPORTS_ENGINE_ROOT", tmp_path)
        monkeypatch.setattr(signals_module, "ROOT_DIR", tmp_path)

        # Snapshot with 3 fixtures: Fixture 1 is valid, Fixture 2 has an invalid edge that raises, Fixture 3 is valid
        # For instance, an edge that is None instead of a dict
        malformed_snapshot = {
            "fixtures": [
                {
                    "fixture_id": "valid_1",
                    "competition": "Premier League",
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "entry_odds": 2.10,
                            "ev_roi": 6.5,
                            "edge_pct": 6.5,
                        }
                    ],
                },
                {
                    "fixture_id": "bad_fixture_2",
                    "competition": "La Liga",
                    "edges": [None],  # None will raise AttributeError on e.get()
                },
                {
                    "fixture_id": "valid_3",
                    "competition": "Bundesliga",
                    "home_team": "Bayern",
                    "away_team": "Dortmund",
                    "edges": [
                        {
                            "market": "1X2",
                            "selection": "1",
                            "entry_odds": 1.85,
                            "ev_roi": 7.0,
                            "edge_pct": 7.0,
                        }
                    ],
                },
            ]
        }
        snapshot.write_text(json.dumps(malformed_snapshot), encoding="utf-8")
        resp = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        # If the outer loop catches Exception and aborts entirely, count is 0 instead of 2.
        # This tests resilience vs complete loss of signals under dirty feed conditions.
        data = resp.json()
        print(f"\n[All-or-nothing probe] Returned signal count: {data['count']}")


# =====================================================================
# 3. MISSING FILE FALLBACK
# =====================================================================

class TestMissingFileFallback:
    """Verifies Gateway endpoints behave safely when files are completely absent."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_health_missing_file_fallback(self, client: TestClient, tmp_path: Path, monkeypatch):
        empty_dir = tmp_path / "empty_root"
        empty_dir.mkdir()
        main_mod = sys.modules["api.main"]
        monkeypatch.setattr(main_mod, "SPORTS_ENGINE_ROOT", empty_dir)
        monkeypatch.setattr(main_mod, "ROOT_DIR", empty_dir)

        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ONLINE"
        assert body["daemon_status"]["status"] == "HEALTHY"
        assert body["daemon_status"]["leagues_scanned"] == 28

    def test_signals_active_missing_file_fallback(self, client: TestClient, tmp_path: Path, monkeypatch):
        empty_dir = tmp_path / "empty_root"
        empty_dir.mkdir()
        sig_mod = sys.modules["api.routes.signals"]
        monkeypatch.setattr(sig_mod, "SPORTS_ENGINE_ROOT", empty_dir)
        monkeypatch.setattr(sig_mod, "ROOT_DIR", empty_dir)

        resp = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["signals"] == []


# =====================================================================
# 4. CORNER SIGNAL PRIORITIZATION & MARKET PARSING EDGE CASES
# =====================================================================

class TestCornerPrioritizationAndMarketParsing:
    """Empirical investigation into prioritize_dispatch_queue failure."""

    def test_reproduce_worker_suite_failure(self):
        """Reproduce the exact failure in test_prioritize_dispatch_queue_orders_corners_first."""
        signals = [
            {"market": "1X2", "home": "A", "away": "B", "outcome": "MS 1"},
            {"market": "CORNER_OU_9.5", "home": "C", "away": "D", "outcome": "Ust 9.5 Korner"},
            {"market": "OU_2.5", "home": "E", "away": "F", "outcome": "Ust 2.5"},
        ]
        sorted_sigs = prioritize_dispatch_queue(signals)

        # Check why it fails:
        # In live_monitor_daemon.py line 161:
        # corner_alerts = [s for s in alerts if s.get("is_corner") or "korner" in str(s.get("market", "")).lower()]
        # The market name has 'CORNER_OU_9.5' (English 'corner'), but code checks for 'korner' (Turkish)
        # without checking 'corner' or looking at s.get('outcome')!
        is_corner_recognized = (sorted_sigs[0]["market"] == "CORNER_OU_9.5")
        assert is_corner_recognized, "Corner market 'CORNER_OU_9.5' must be prioritized first in dispatch queue"

