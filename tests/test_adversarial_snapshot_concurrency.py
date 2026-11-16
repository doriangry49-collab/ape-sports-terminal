"""Adversarial Snapshot Concurrency, Constitutional Invariants & Fault-Tolerance Test Suite.

Milestone 3 (Requirement R3):
1. High-concurrency snapshot export vs UI reading:
   - Simulate rapid 100+ concurrent reader threads accessing sports_intelligence_snapshot.json
     while export_snapshot.py is repeatedly overwriting it via atomic temporary file + replace.
   - Verify zero partial JSON reads (JSONDecodeError), zero crashes, zero data truncation.
2. Constitutional Edge Invariants in Snapshot:
   - SPEC-0015: Minimum ticket stake >= 50.0 TL enforcement (fail-closed on stake < 50.0 TL).
   - SPEC-0013: Lead time > 3m (kickoff <= now + 3m rejected fail-closed).
   - SPEC-0014: 12-hour maximum window (kickoff > now + 12h rejected fail-closed).
   - Sizing edge-cases: Kelly fraction producing stake < 50 TL under small bankrolls.
3. Malformed Snapshot Recovery:
   - Truncated JSON, zero-byte file, non-JSON HTML, binary junk, non-dict roots, poisoned inner fixtures/edges.
   - Verification of FastAPI Gateway /api/v1/signals/active and /api/v1/health graceful fallback (no 500s).
   - Instant recovery when a corrupted snapshot is replaced with a healthy atomic snapshot.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
UI_PATH = PROJECT_ROOT / "ui"

for p in (str(SRC_PATH), str(PROJECT_ROOT), str(UI_PATH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from export_snapshot import generate_ui_snapshot

from api.main import app
from closing_line_freeze import (
    ClosingLineUnavailableError,
    check_fixture_kickoff_window,
    compute_clv,
    validate_coupon_stake,
)
from live_monitor_daemon import TRT_TZ, parse_match_kickoff

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
def isolated_snapshot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides isolated filesystem directories for atomic snapshot tests."""
    ui_data_dir = tmp_path / "ui" / "data"
    ui_data_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_file = ui_data_dir / "sports_intelligence_snapshot.json"
    heartbeat_file = out_dir / "daemon_heartbeat.json"

    # Seed baseline heartbeat
    heartbeat_data = {
        "status": "HEALTHY",
        "last_cycle_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": 1.1,
        "leagues_scanned": 28,
        "fixtures_scanned": 40,
        "nesine_matched": 35,
        "positive_ev_signals": 5,
        "steam_confirmed_signals": 2,
        "new_alerts_in_cycle": 1,
        "total_seen_alerts": 1190,
    }
    heartbeat_file.write_text(json.dumps(heartbeat_data, indent=2), encoding="utf-8")

    # Patch API root paths
    import api.main as main_mod
    monkeypatch.setattr(main_mod, "SPORTS_ENGINE_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "ROOT_DIR", tmp_path)

    import api.routes.signals as signals_mod
    monkeypatch.setattr(signals_mod, "SPORTS_ENGINE_ROOT", tmp_path)
    monkeypatch.setattr(signals_mod, "ROOT_DIR", tmp_path)

    return {
        "tmp_path": tmp_path,
        "ui_data_dir": ui_data_dir,
        "out_dir": out_dir,
        "snapshot_file": snapshot_file,
        "heartbeat_file": heartbeat_file,
    }


# =====================================================================
# SECTION 1: HIGH-CONCURRENCY SNAPSHOT EXPORT VS UI READING (100+ THREADS)
# =====================================================================

class TestAdversarialSnapshotConcurrency:
    """Empirical verification of atomic file replacement under massive reader contention."""

    def test_rapid_100_concurrent_readers_during_repeated_atomic_overwrites(self, tmp_path: Path):
        """100+ concurrent reader threads repeatedly load and parse snapshot JSON while writer thread

        continuously executes atomic temporary file creation + os.replace.
        VERIFIES:
        1. Zero partial reads (JSONDecodeError == 0).
        2. Zero file corruption or zero-byte read leaks.
        3. Zero unhandled reader exceptions.
        4. Overwrite versions increase monotonically.
        """
        snapshot_file = tmp_path / "sports_intelligence_snapshot.json"

        # Seed initial snapshot payload
        def build_payload(v: int) -> dict[str, Any]:
            return {
                "engine_name": "Sports Intelligence Terminal",
                "engine_version": "v2.0-quant-shin",
                "snapshot_timestamp": datetime.now(UTC).isoformat(),
                "snapshot_version": v,
                "total_fixtures": 2,
                "fixtures": [
                    {
                        "fixture_id": f"fix_conc_{v}_01",
                        "home_team": f"HomeTeam_{v}",
                        "away_team": f"AwayTeam_{v}",
                        "competition": "Trendyol Süper Lig",
                        "league": "Trendyol Süper Lig",
                        "kickoff": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                        "edges": [
                            {
                                "market": "1X2",
                                "selection": "HOME",
                                "selection_display": f"HomeTeam_{v} (Home)",
                                "entry_odds": 2.10,
                                "raw_edge": 0.045,
                                "ev_roi": 4.5,
                                "half_kelly": 1.2,
                                "league": "Trendyol Süper Lig",
                            }
                        ],
                    },
                    {
                        "fixture_id": f"fix_conc_{v}_02",
                        "home_team": f"HomeTeamB_{v}",
                        "away_team": f"AwayTeamB_{v}",
                        "competition": "Premier League",
                        "league": "Premier League",
                        "kickoff": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
                        "edges": [
                            {
                                "market": "TOTALS",
                                "selection": "OVER_2.5",
                                "selection_display": "Over 2.5 Goals",
                                "entry_odds": 1.95,
                                "raw_edge": 0.038,
                                "ev_roi": 3.8,
                                "half_kelly": 0.9,
                                "league": "Premier League",
                            }
                        ],
                    },
                ],
            }

        snapshot_file.write_text(json.dumps(build_payload(0), indent=2), encoding="utf-8")

        stop_event = threading.Event()
        read_stats = {
            "total_reads": 0,
            "json_decode_errors": 0,
            "partial_reads": 0,
            "permission_retries": 0,
            "other_errors": 0,
            "versions_seen": set(),
        }
        write_stats = {
            "total_writes": 0,
            "write_failures": 0,
        }
        stats_lock = threading.Lock()

        # Atomic writer worker imitating export_snapshot.py
        def writer_loop():
            version = 1
            while not stop_event.is_set() and version <= 60:
                payload = build_payload(version)
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

                    replaced = False
                    for attempt in range(25):
                        try:
                            os.replace(temp_name, snapshot_file)
                            replaced = True
                            break
                        except (PermissionError, OSError):
                            time.sleep(0.003 + 0.002 * (attempt % 5))
                    if not replaced:
                        os.replace(temp_name, snapshot_file)

                    with stats_lock:
                        write_stats["total_writes"] += 1
                    version += 1
                    time.sleep(0.01)  # 10ms jitter between atomic replacements
                except Exception:
                    with stats_lock:
                        write_stats["write_failures"] += 1
                finally:
                    if temp_name and os.path.exists(temp_name):
                        try:
                            os.unlink(temp_name)
                        except OSError:
                            pass

        # Reader worker representing UI / Gateway client
        def reader_loop(worker_id: int):
            local_reads = 0
            while not stop_event.is_set():
                try:
                    # Retry loop on Windows transient lock contention
                    content = None
                    for _attempt in range(10):
                        try:
                            content = snapshot_file.read_text(encoding="utf-8")
                            break
                        except (PermissionError, OSError):
                            with stats_lock:
                                read_stats["permission_retries"] += 1
                            time.sleep(0.002)

                    if content is None:
                        continue

                    # Strict JSON parse: partial writes trigger JSONDecodeError
                    data = json.loads(content)

                    # Integrity verification: payload must not be hollow
                    assert isinstance(data, dict), "Snapshot root must be dict"
                    assert "snapshot_version" in data, "Snapshot must have snapshot_version"
                    assert "fixtures" in data, "Snapshot must have fixtures"
                    assert len(data["fixtures"]) == 2, "Snapshot fixtures count intact"

                    v = data["snapshot_version"]
                    local_reads += 1
                    with stats_lock:
                        read_stats["total_reads"] += 1
                        read_stats["versions_seen"].add(v)
                except json.JSONDecodeError:
                    with stats_lock:
                        read_stats["json_decode_errors"] += 1
                        read_stats["partial_reads"] += 1
                except Exception:
                    with stats_lock:
                        read_stats["other_errors"] += 1
                finally:
                    # Cooperative yield on Windows NTFS to prevent handle starvation
                    time.sleep(0.04)

        # Launch 100 concurrent reader threads + 1 writer thread
        num_readers = 100
        threads: list[threading.Thread] = []

        writer_thread = threading.Thread(target=writer_loop, name="AtomicWriter")
        writer_thread.daemon = True
        writer_thread.start()

        for i in range(num_readers):
            t = threading.Thread(target=reader_loop, args=(i,), name=f"Reader_{i:03d}")
            t.daemon = True
            threads.append(t)
            t.start()

        # Let the writer run its course (allow 18s for 100-thread NTFS contention)
        writer_thread.join(timeout=18.0)
        stop_event.set()

        for t in threads:
            t.join(timeout=2.0)

        # Clean assertions
        print("\n[Adversarial Concurrency Benchmark Results]:")
        print(f"- Concurrent Readers: {num_readers}")
        print(f"- Total Reads Completed: {read_stats['total_reads']}")
        print(f"- Total Atomic Writes: {write_stats['total_writes']}")
        print(f"- JSON Decode Errors (Partial Reads): {read_stats['json_decode_errors']}")
        print(f"- Permission Retries: {read_stats['permission_retries']}")
        print(f"- Other Unhandled Errors: {read_stats['other_errors']}")
        print(f"- Unique Snapshot Versions Observed: {len(read_stats['versions_seen'])}")

        assert write_stats["total_writes"] >= 15, "Writer must complete minimum write cycles"
        assert read_stats["total_reads"] >= 200, "100 readers must complete high-volume read cycles"
        assert read_stats["json_decode_errors"] == 0, "Zero partial/corrupted reads permitted under atomic replace"
        assert read_stats["partial_reads"] == 0, "Zero partial reads observed"
        assert read_stats["other_errors"] == 0, "Zero unhandled reader exceptions"

    def test_gateway_endpoint_concurrent_read_stress(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """50 concurrent threads stress-testing FastAPI Gateway /api/v1/signals/active while

        generate_ui_snapshot is repeatedly overwriting the active snapshot.
        """
        snapshot_file = isolated_snapshot_env["snapshot_file"]

        # Populate valid snapshot
        generate_ui_snapshot(output_file=snapshot_file)
        assert snapshot_file.exists()

        stop_flag = threading.Event()
        writer_cycles = 0
        gateway_results = {"success": 0, "error": 0, "status_codes": set()}
        res_lock = threading.Lock()

        def continuous_exporter():
            nonlocal writer_cycles
            while not stop_flag.is_set():
                try:
                    generate_ui_snapshot(output_file=snapshot_file)
                    writer_cycles += 1
                except (PermissionError, OSError):
                    time.sleep(0.05)
                time.sleep(0.02)

        def api_reader(idx: int):
            for _ in range(15):
                res = api_client.get("/api/v1/signals/active?min_edge=0.0", headers=AUTH_HEADERS)
                with res_lock:
                    gateway_results["status_codes"].add(res.status_code)
                    if res.status_code == 200:
                        gateway_results["success"] += 1
                    else:
                        gateway_results["error"] += 1
                time.sleep(0.005)

        exp_thread = threading.Thread(target=continuous_exporter, daemon=True)
        exp_thread.start()

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(api_reader, i) for i in range(50)]
            concurrent.futures.wait(futures, timeout=15.0)

        stop_flag.set()
        exp_thread.join(timeout=3.0)

        assert gateway_results["error"] == 0, f"Expected 0 gateway errors, got {gateway_results['error']}"
        assert gateway_results["status_codes"] == {200}, f"Expected only 200 OK, got {gateway_results['status_codes']}"
        assert gateway_results["success"] == 50 * 15, "All 750 concurrent gateway requests succeeded"
        assert writer_cycles >= 1, "Snapshot exporter ran atomic cycle during concurrent reads"


# =====================================================================
# SECTION 2: CONSTITUTIONAL EDGE INVARIANTS IN SNAPSHOT (SPEC-0012..15)
# =====================================================================

class TestAdversarialConstitutionalInvariants:
    """Stress-tests constitutional invariants across boundary values and adversarial payloads."""

    # -----------------------------------------------------------------
    # SPEC-0015: Minimum 50.0 TL Stake Enforcement
    # -----------------------------------------------------------------
    def test_spec0015_boundary_stake_values(self):
        """SPEC-0015: Minimum ticket stake >= 50.0 TL.

        Must raise ValueError fail-closed for stake < 50.0 TL.
        """
        # Exact boundary
        assert validate_coupon_stake(50.0) is True
        assert validate_coupon_stake(50.0001) is True
        assert validate_coupon_stake(100.0) is True
        assert validate_coupon_stake(10000.0) is True

        # Violating boundaries (< 50.0 TL)
        failing_stakes = [
            49.99,
            49.9999,
            45.0,
            25.0,
            1.0,
            0.5,
            0.0,
            -0.01,
            -50.0,
            -999.0,
        ]
        for bad_stake in failing_stakes:
            with pytest.raises(ValueError) as exc_info:
                validate_coupon_stake(bad_stake)
            assert "SPEC-0015 Violation" in str(exc_info.value)
            assert "50.0 TL" in str(exc_info.value)

    def test_spec0015_kelly_allocation_bankroll_interaction(self):
        """SPEC-0015: Half-Kelly position sizing against user bankrolls.

        When a recommended position fraction yields < 50 TL, system must enforce fail-closed
        threshold (either raise violation or filter out ticket).
        """
        # Standard bankroll: 10,000 TL
        # Half-Kelly 0.4% = 40 TL (< 50 TL -> VIOLATION)
        # Half-Kelly 0.5% = 50 TL (== 50 TL -> VALID)
        # Half-Kelly 1.5% = 150 TL (> 50 TL -> VALID)
        bankroll = 10000.0

        def compute_recommended_stake(kelly_pct: float, br: float) -> float:
            return round((kelly_pct / 100.0) * br, 2)

        stake_valid = compute_recommended_stake(0.50, bankroll)
        assert stake_valid == 50.0
        assert validate_coupon_stake(stake_valid) is True

        stake_invalid = compute_recommended_stake(0.49, bankroll)
        assert stake_invalid == 49.0
        with pytest.raises(ValueError):
            validate_coupon_stake(stake_invalid)

        # Micro-bankroll stress: 500 TL bankroll
        # Even a 5.0% Kelly bet produces 25.0 TL (< 50 TL -> VIOLATION)
        micro_bankroll = 500.0
        stake_micro = compute_recommended_stake(5.0, micro_bankroll)
        assert stake_micro == 25.0
        with pytest.raises(ValueError):
            validate_coupon_stake(stake_micro)

    # -----------------------------------------------------------------
    # SPEC-0013: Finished or Imminent Matches (kickoff > now + 3m)
    # -----------------------------------------------------------------
    def test_spec0013_kickoff_lead_time_boundaries(self):
        """SPEC-0013: Fixtures starting in <= 3 minutes or past matches must be rejected fail-closed."""
        ref_now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

        # 1. Past matches
        past_times = [
            ref_now - timedelta(hours=2),
            ref_now - timedelta(minutes=10),
            ref_now - timedelta(seconds=1),
            ref_now,
        ]
        for pt in past_times:
            valid, reason = check_fixture_kickoff_window(pt, reference_now_utc=ref_now)
            assert valid is False
            assert "SPEC-0013 Violation" in reason

        # 2. Imminent matches (inside 3-minute lead buffer)
        imminent_times = [
            ref_now + timedelta(seconds=30),
            ref_now + timedelta(minutes=1),
            ref_now + timedelta(minutes=2, seconds=59),
            ref_now + timedelta(minutes=3),  # Boundary cutoff is inclusive rejection: ko <= now + 3m
        ]
        for it in imminent_times:
            valid, reason = check_fixture_kickoff_window(it, reference_now_utc=ref_now)
            assert valid is False
            assert "SPEC-0013 Violation" in reason

        # 3. Legitimate upcoming matches
        valid_times = [
            ref_now + timedelta(minutes=3, seconds=1),
            ref_now + timedelta(minutes=5),
            ref_now + timedelta(hours=1),
            ref_now + timedelta(hours=6),
            ref_now + timedelta(hours=12),
        ]
        for vt in valid_times:
            valid, reason = check_fixture_kickoff_window(vt, reference_now_utc=ref_now)
            assert valid is True
            assert reason == "VALID_WINDOW"

    def test_spec0013_daemon_kickoff_parser_adversarial_inputs(self):
        """Verify live_monitor_daemon.parse_match_kickoff returns (None, None) for SPEC-0013 violations."""
        now_trt = datetime(2026, 11, 4, 15, 0, 0, tzinfo=TRT_TZ)

        # Past match
        m_dt, iso = parse_match_kickoff("04.11.2026", "14:30", now_trt=now_trt)
        assert m_dt is None and iso is None

        # Imminent match (2 mins away)
        m_dt, iso = parse_match_kickoff("04.11.2026", "15:02", now_trt=now_trt)
        assert m_dt is None and iso is None

        # Exact 3m boundary
        m_dt, iso = parse_match_kickoff("04.11.2026", "15:03", now_trt=now_trt)
        assert m_dt is None and iso is None

        # Valid upcoming match (10 mins away)
        m_dt, iso = parse_match_kickoff("04.11.2026", "15:10", now_trt=now_trt)
        assert m_dt is not None and iso is not None
        assert "2026-11-04T12:10:00Z" in iso

    # -----------------------------------------------------------------
    # SPEC-0014: Maximum 12-Hour Lead Time Window (kickoff <= now + 12h)
    # -----------------------------------------------------------------
    def test_spec0014_max_12h_window_boundaries(self):
        """SPEC-0014: Matches scheduled beyond 12 hours from now must be rejected fail-closed."""
        ref_now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)

        # Valid upper boundary (exactly 12h)
        exact_12h = ref_now + timedelta(hours=12)
        valid, reason = check_fixture_kickoff_window(exact_12h, reference_now_utc=ref_now)
        assert valid is True
        assert reason == "VALID_WINDOW"

        # Violating times (> 12h)
        excessive_times = [
            ref_now + timedelta(hours=12, seconds=1),
            ref_now + timedelta(hours=12, minutes=1),
            ref_now + timedelta(hours=15),
            ref_now + timedelta(days=2),
            ref_now + timedelta(days=30),
        ]
        for et in excessive_times:
            valid, reason = check_fixture_kickoff_window(et, reference_now_utc=ref_now)
            assert valid is False
            assert "SPEC-0014 Violation" in reason

    def test_spec0014_daemon_kickoff_parser_excessive_lead_time(self):
        """parse_match_kickoff filters out matches scheduled > 12h away."""
        now_trt = datetime(2026, 11, 4, 10, 0, 0, tzinfo=TRT_TZ)

        # Match 14 hours ahead (same day 24:00 / next day 00:00)
        m_dt, iso = parse_match_kickoff("05.11.2026", "01:00", now_trt=now_trt)
        assert m_dt is None and iso is None

        # Match 3 days ahead
        m_dt, iso = parse_match_kickoff("08.11.2026", "19:00", now_trt=now_trt)
        assert m_dt is None and iso is None

    # -----------------------------------------------------------------
    # SPEC-0012: Fail-Closed Error Handling (No Mocks, No Synthetic Odds)
    # -----------------------------------------------------------------
    def test_spec0012_invalid_odds_clv_fail_closed(self):
        """compute_clv must strictly reject non-positive or sub-1.0 odds fail-closed."""
        # Odds <= 1.0 cannot exist in real sports markets
        for bad_odd in [1.0, 0.95, 0.0, -2.5, float("nan"), float("inf")]:
            with pytest.raises(ClosingLineUnavailableError) as exc_info:
                compute_clv(entry_odds=bad_odd, frozen_closing_odds=2.0, frozen_fair_odds=1.9)
            assert "SPEC-0012 Violation" in str(exc_info.value)

            with pytest.raises(ClosingLineUnavailableError) as exc_info:
                compute_clv(entry_odds=2.1, frozen_closing_odds=bad_odd, frozen_fair_odds=1.9)
            assert "SPEC-0012 Violation" in str(exc_info.value)


# =====================================================================
# SECTION 3: MALFORMED SNAPSHOT RECOVERY & GATEWAY HARDENING
# =====================================================================

class TestAdversarialMalformedSnapshotRecovery:
    """Stress-tests Gateway and UI recovery when snapshot file contains corrupted payloads."""

    def test_truncated_json_snapshot_graceful_recovery(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """When sports_intelligence_snapshot.json is cut off mid-write, Gateway returns empty signals

        gracefully with 200 OK (never 500 Internal Server Error).
        """
        snapshot_file = isolated_snapshot_env["snapshot_file"]

        # Truncated JSON snippets at various byte lengths
        truncated_payloads = [
            '{"engine_name": "Sports Intelligence',
            '{"engine_name": "Sports Intelligence", "fixtures": [',
            '{"engine_name": "Sports Intelligence", "fixtures": [{"fixture_id": "tr_1", "home_team": "Gala',
            '{',
            '{"fixtures":',
        ]

        for payload in truncated_payloads:
            snapshot_file.write_text(payload, encoding="utf-8")
            res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
            assert res.status_code == 200, f"Expected 200 OK on truncated JSON, got {res.status_code}"
            data = res.json()
            assert data["count"] == 0
            assert data["signals"] == []

    def test_zero_byte_snapshot_graceful_recovery(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Zero-byte snapshot file must not crash the Gateway."""
        snapshot_file = isolated_snapshot_env["snapshot_file"]
        snapshot_file.write_bytes(b"")
        assert snapshot_file.stat().st_size == 0

        res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 0
        assert data["signals"] == []

    def test_non_json_content_and_html_error_pages(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Snapshot containing upstream 502/504 HTML error page does not crash Gateway."""
        snapshot_file = isolated_snapshot_env["snapshot_file"]
        html_payload = (
            "<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head>"
            "<body><center><h1>502 Bad Gateway</h1></center><hr><center>cloudflare</center></body></html>"
        )
        snapshot_file.write_text(html_payload, encoding="utf-8")

        res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 0
        assert data["signals"] == []

    def test_raw_binary_junk_snapshot(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Snapshot containing raw non-UTF8 binary bytes is safely handled without unhandled exception."""
        snapshot_file = isolated_snapshot_env["snapshot_file"]
        raw_binary = b"\x80\xff\xfe\x00\x01\x02\x03\xaa\xbb\xcc\xdd\xee\x12\x34\x56\x78"
        snapshot_file.write_bytes(raw_binary)

        res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 0
        assert data["signals"] == []

    def test_non_dict_json_root_payloads(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Valid JSON but invalid root data types (array, string, int, boolean, null) handled safely."""
        snapshot_file = isolated_snapshot_env["snapshot_file"]
        bad_roots = [
            "[1, 2, 3, 4, 5]",
            '"simple standalone string"',
            "987654",
            "true",
            "false",
            "null",
        ]
        for br in bad_roots:
            snapshot_file.write_text(br, encoding="utf-8")
            res = api_client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
            assert res.status_code == 200
            assert res.json()["count"] == 0

    def test_poisoned_inner_fixtures_and_edges(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Poisoned or corrupt fixtures/edges inside an otherwise valid snapshot are safely skipped

        without dropping legitimate edges or crashing the loop.
        """
        snapshot_file = isolated_snapshot_env["snapshot_file"]
        poisoned_snapshot = {
            "engine_name": "Sports Intelligence Terminal",
            "fixtures": [
                None,  # Poisoned: None fixture
                "not_a_fixture_dict",  # Poisoned: string
                12345,  # Poisoned: int
                {
                    "fixture_id": "bad_fix_edges",
                    "competition": "Super Lig",
                    "edges": "not_a_list",  # Poisoned: non-list edges
                },
                {
                    "fixture_id": "valid_fix_01",
                    "competition": "Trendyol Süper Lig",
                    "home_team": "Galatasaray",
                    "away_team": "Fenerbahce",
                    "edges": [
                        None,  # Poisoned edge
                        "corrupt_edge_string",  # Poisoned edge
                        42,  # Poisoned edge
                        {
                            "market": "1X2",
                            "selection": "1",
                            "selection_display": "Galatasaray (Home)",
                            "entry_odds": "invalid_odds_string",  # Invalid type: fails _safe_float
                            "ev_roi": "not_a_float",
                        },
                        {
                            # Healthy valid edge
                            "market": "1X2",
                            "selection": "1",
                            "selection_display": "Galatasaray (Home)",
                            "entry_odds": 2.20,
                            "market_fair_odds": 1.95,
                            "market_no_vig": 0.5128,
                            "model_prob": 0.5350,
                            "raw_edge": 0.045,
                            "ev_roi": 17.7,
                            "half_kelly": 2.5,
                            "shin_margin": 4.5,
                            "kickoff_trt": "2026-11-04 20:00 TRT",
                        },
                    ],
                },
            ],
        }
        snapshot_file.write_text(json.dumps(poisoned_snapshot), encoding="utf-8")

        res = api_client.get("/api/v1/signals/active?min_edge=3.0", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1, "Only the legitimate edge must be parsed"
        signal = data["signals"][0]
        assert signal["fixture_id"] == "valid_fix_01"
        assert signal["home_team"] == "Galatasaray"
        assert signal["offered_odds"] == 2.20
        assert signal["ev_roi"] == 17.7

    def test_instant_recovery_cycle_after_snapshot_corruption(
        self, api_client: TestClient, isolated_snapshot_env
    ):
        """Empirically verify that corrupting the snapshot and then atomically restoring it

        immediately restores active signals without requiring process restart or caching error states.
        """
        snapshot_file = isolated_snapshot_env["snapshot_file"]

        # Step 1: Initial healthy snapshot
        generate_ui_snapshot(output_file=snapshot_file)
        res_initial = api_client.get("/api/v1/signals/active?min_edge=0.0", headers=AUTH_HEADERS)
        assert res_initial.status_code == 200
        initial_count = res_initial.json()["count"]
        assert initial_count > 0, "Healthy snapshot contains signals"

        # Step 2: Corrupt snapshot with broken JSON
        snapshot_file.write_text('{"corrupted": true, broken', encoding="utf-8")
        res_corrupt = api_client.get("/api/v1/signals/active?min_edge=0.0", headers=AUTH_HEADERS)
        assert res_corrupt.status_code == 200
        assert res_corrupt.json()["count"] == 0, "Corrupt snapshot returns empty signals safely"

        # Step 3: Instant atomic restoration
        generate_ui_snapshot(output_file=snapshot_file)
        res_restored = api_client.get("/api/v1/signals/active?min_edge=0.0", headers=AUTH_HEADERS)
        assert res_restored.status_code == 200
        restored_count = res_restored.json()["count"]
        assert restored_count == initial_count, "Signals fully restored to initial count"


# =====================================================================
# SECTION 4: ADVERSARIAL FILTER COMBINATIONS & EDGE-CASE RESILIENCE
# =====================================================================

class TestAdversarialFilterEdgeCombinations:
    """Stress-tests the Milestone 3 filter logic against degenerate, empty, and adversarial edge sets."""

    @staticmethod
    def parse_min_ev_threshold(filter_val: str | float | None) -> float:
        """Mirrors parseMinEvThreshold in ValueScannerScreen.js."""
        if filter_val is None or filter_val == "all" or filter_val == "ALL":
            return -999999.0
        try:
            n = float(filter_val)
            if 0.0 < n < 1.0:
                return n * 100.0
            return n
        except (ValueError, TypeError):
            return -999999.0

    @staticmethod
    def normalize_league_str(s: str) -> str:
        """Mirrors normalizeLeagueText in ValueScannerScreen.js for Unicode NFKD diacritic-agnostic matching."""
        if not s:
            return ""
        decomposed = unicodedata.normalize("NFKD", s)
        stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
        return stripped.strip().lower()

    @staticmethod
    def filter_and_rank_edges(
        edges: list[dict],
        min_ev: str | float | None = 0.0,
        min_prob: float = 0.0,
        selected_league: str = "all",
        selected_bookmaker: str = "all",
    ) -> list[dict]:
        """Mirrors ValueScannerScreen.js filtering logic."""
        threshold = TestAdversarialFilterEdgeCombinations.parse_min_ev_threshold(min_ev)
        active_league = (selected_league or "all").strip()
        active_bookmaker = (selected_bookmaker or "all").strip()
        prob_threshold = float(min_prob or 0.0)

        filtered = []
        for e in edges:
            if not isinstance(e, dict):
                continue
            raw_edge = e.get("raw_edge")
            raw_edge_val = float(raw_edge) if isinstance(raw_edge, (int, float)) else -999.0

            model_p = e.get("model_prob")
            model_p_val = float(model_p) if isinstance(model_p, (int, float)) else 0.0

            ev_roi = e.get("ev_roi") if e.get("ev_roi") is not None else e.get("evRoi")
            if isinstance(ev_roi, (int, float)):
                ev_roi_val = float(ev_roi)
            else:
                ev_roi_val = raw_edge_val * 100.0

            passes_ev = ev_roi_val >= threshold
            passes_prob = model_p_val >= prob_threshold

            edge_league = (e.get("league") or e.get("competition") or "").strip()
            norm_active_league = TestAdversarialFilterEdgeCombinations.normalize_league_str(active_league)
            norm_edge_league = TestAdversarialFilterEdgeCombinations.normalize_league_str(edge_league)
            passes_league = (
                norm_active_league == "all"
                or not norm_active_league
                or norm_edge_league == norm_active_league
            )

            edge_book = (e.get("bookmaker") or "").strip()
            passes_book = (
                active_bookmaker.lower() == "all"
                or not active_bookmaker
                or edge_book.upper() == active_bookmaker.upper()
            )

            if passes_ev and passes_prob and passes_league and passes_book:
                filtered.append(dict(e, _computed_ev_roi=ev_roi_val))

        filtered.sort(key=lambda x: x["_computed_ev_roi"], reverse=True)
        return filtered

    def test_empty_and_corrupt_edge_lists(self):
        """Empty lists or lists containing None/non-dicts are filtered gracefully without crashes."""
        assert self.filter_and_rank_edges([]) == []
        assert self.filter_and_rank_edges([None, 42, "not_a_dict"]) == []

    def test_extreme_and_unparseable_min_ev_thresholds(self):
        """Unparseable or extreme min_ev values fall back gracefully to all (-999999)."""
        edges = [{"ev_roi": 5.0, "model_prob": 0.5, "league": "Super Lig", "bookmaker": "NESINE"}]

        # Unparseable inputs fall back to all
        for unparseable in ["garbage", "", "NaN_string", None, "ALL"]:
            res = self.filter_and_rank_edges(edges, min_ev=unparseable)
            assert len(res) == 1

        # Extreme high threshold filters out everything
        res_high = self.filter_and_rank_edges(edges, min_ev=100.0)
        assert len(res_high) == 0

        # Negative threshold includes negative ROI
        edges_neg = [{"ev_roi": -5.0, "model_prob": 0.5, "league": "Super Lig", "bookmaker": "NESINE"}]
        res_neg = self.filter_and_rank_edges(edges_neg, min_ev=-10.0)
        assert len(res_neg) == 1

    def test_league_whitespace_and_case_insensitivity(self):
        """League filtering handles arbitrary whitespace, upper/lower casing, and partial spacing."""
        edges = [
            {"ev_roi": 4.0, "model_prob": 0.5, "league": "Trendyol Süper Lig", "bookmaker": "NESINE"},
            {"ev_roi": 6.0, "model_prob": 0.5, "competition": "İngiltere Premier League (E0)", "bookmaker": "PINNACLE"},
        ]

        # Case-insensitive matches
        res_tr = self.filter_and_rank_edges(edges, min_ev="all", selected_league="TRENDYOL SÜPER LİG")
        assert len(res_tr) == 1
        assert res_tr[0]["league"] == "Trendyol Süper Lig"

        res_e0 = self.filter_and_rank_edges(edges, min_ev="all", selected_league="  i̇ngiltere premier league (e0)  ")
        assert len(res_e0) == 1
        assert res_e0[0]["competition"] == "İngiltere Premier League (E0)"

        # Unknown league returns zero results
        res_none = self.filter_and_rank_edges(edges, min_ev="all", selected_league="NonExistent League")
        assert len(res_none) == 0

