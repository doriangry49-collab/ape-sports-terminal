"""Adversarial Stress Test Suite for Milestone 1 (Iteration 1).

Adversarial stress-testing of Operational Resilience, Atomic I/O, Network Adapter
Backoff & Error Handling, and Telegram Daemon Command Processing.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from atomic_io import atomic_write_json, atomic_write_text
from live_settlement_engine import (
    calculate_system_payout,
    evaluate_pick_result,
    fetch_espn_scores,
    load_bankroll,
    run_settlement_cycle,
)
from live_stale_line_adapter import (
    AdapterError,
    AdapterHTTPError,
    AdapterPayloadError,
    AdapterTimeoutError,
    _get_json,
    fetch_nesine_live_bulletin,
)
from telegram_notifier import (
    check_and_reply_telegram_commands,
    load_telegram_offset,
    process_user_command,
    save_telegram_offset,
)

# =====================================================================
# 1. ATOMIC I/O ADVERSARIAL STRESS TESTS
# =====================================================================

def test_atomic_write_json_nested_deep_path(tmp_path: Path):
    """Stress test: Atomic write to deeply nested non-existent directory hierarchies."""
    deep_target = tmp_path / "a" / "b" / "c" / "d" / "e" / "ledger.json"
    data = {"system": "sports-engine", "iteration": 1, "status": "HARDENED"}

    assert not deep_target.parent.exists()
    atomic_write_json(deep_target, data)
    assert deep_target.exists()

    loaded = json.loads(deep_target.read_text(encoding="utf-8"))
    assert loaded == data

    # Verify no dangling temp files anywhere in the tree
    temp_files = list(tmp_path.glob("**/.*.tmp_*"))
    assert len(temp_files) == 0


def test_atomic_write_json_unserializable_objects_preserves_original(tmp_path: Path):
    """Stress test: Unserializable objects (sets, functions, cyclic refs) must fail cleanly without corrupting original."""
    target = tmp_path / "protected_state.json"
    initial_payload = {"version": "v1.0", "balance": 150.0, "active_tickets": 3}
    atomic_write_json(target, initial_payload)

    # 1. Unserializable type (set)
    bad_payload_set = {"version": "v2.0", "invalid_field": {1, 2, 3}}
    with pytest.raises(TypeError):
        atomic_write_json(target, bad_payload_set)

    # 2. Unserializable function
    bad_payload_fn = {"version": "v2.0", "fn": lambda x: x}
    with pytest.raises(TypeError):
        atomic_write_json(target, bad_payload_fn)

    # Original file must remain 100% intact with v1.0 data
    preserved = json.loads(target.read_text(encoding="utf-8"))
    assert preserved == initial_payload
    assert preserved["balance"] == 150.0

    # Ensure zero leftover temp files
    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0


def test_atomic_write_json_high_frequency_overwrites(tmp_path: Path):
    """Stress test: 100 rapid sequential atomic writes to the same file."""
    target = tmp_path / "high_freq_ledger.json"
    for i in range(100):
        atomic_write_json(target, {"iteration": i, "timestamp": 1000 + i})

    final = json.loads(target.read_text(encoding="utf-8"))
    assert final["iteration"] == 99

    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0


def test_atomic_write_text_persistence_and_cleanup(tmp_path: Path):
    """Stress test: Rapid atomic text writes and invalid type rejection."""
    target = tmp_path / "offset_test.txt"
    atomic_write_text(target, "1001")
    assert target.read_text(encoding="utf-8") == "1001"

    # Attempt to write non-string (int) -> raises TypeError
    with pytest.raises(TypeError):
        atomic_write_text(target, 1002)  # type: ignore

    # Target content must remain unchanged
    assert target.read_text(encoding="utf-8") == "1001"
    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0


# =====================================================================
# 2. NETWORK RESILIENCE & SPEC-0012 ADVERSARIAL TESTS
# =====================================================================

def test_nesine_bulletin_exponential_backoff_execution():
    """Stress test: Verify exponential backoff delays (1s, 2s) across 3 failed attempts."""
    sleep_calls: list[float] = []

    def mock_sleep(seconds: float):
        sleep_calls.append(seconds)

    def mock_urlopen_always_fails(req, timeout=10.0):
        raise urllib.error.URLError("Simulated connection dropped by remote peer")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_always_fails):
        with patch("time.sleep", side_effect=mock_sleep):
            res = fetch_nesine_live_bulletin(timeout=10.0, max_retries=3, backoff_factor=1.0, raise_on_error=False)

    # Fail-closed returns empty list
    assert res == []
    # Exactly 2 sleep calls between 3 attempts: attempt 1 -> sleep 1.0s, attempt 2 -> sleep 2.0s
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == 1.0
    assert sleep_calls[1] == 2.0


def test_nesine_bulletin_http_503_spec0012_raising():
    """Stress test: HTTP 503 Server Error must raise AdapterHTTPError with status 503 when raise_on_error=True."""
    def mock_urlopen_503(req, timeout=10.0):
        raise urllib.error.HTTPError("https://cdnbulten.nesine.com", 503, "Service Temporarily Unavailable", {}, None)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_503):
        with patch("time.sleep", return_value=None):
            with pytest.raises(AdapterHTTPError) as exc_info:
                fetch_nesine_live_bulletin(timeout=10.0, max_retries=3, backoff_factor=0.01, raise_on_error=True)

    assert exc_info.value.status_code == 503
    assert "Service Temporarily Unavailable" in str(exc_info.value)
    assert issubclass(AdapterHTTPError, AdapterError)


def test_nesine_bulletin_socket_timeout_spec0012_raising():
    """Stress test: Socket timeouts must raise AdapterTimeoutError when raise_on_error=True."""
    def mock_urlopen_timeout(req, timeout=10.0):
        raise TimeoutError("The read operation timed out")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_timeout):
        with patch("time.sleep", return_value=None):
            with pytest.raises(AdapterTimeoutError) as exc_info:
                fetch_nesine_live_bulletin(timeout=10.0, max_retries=2, backoff_factor=0.01, raise_on_error=True)

    assert "timed out" in str(exc_info.value).lower()
    assert issubclass(AdapterTimeoutError, AdapterError)


def test_nesine_bulletin_corrupted_json_payload():
    """Stress test: Corrupted/truncated JSON payload raises AdapterPayloadError when raise_on_error=True."""
    class MockCorruptResp:
        def __init__(self):
            self.status = 200

        def read(self):
            return b'{"sg": {"EA": [{"incomplete": true'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockCorruptResp()):
        with patch("time.sleep", return_value=None):
            with pytest.raises(AdapterPayloadError) as exc_info:
                fetch_nesine_live_bulletin(timeout=10.0, max_retries=2, backoff_factor=0.01, raise_on_error=True)

    assert "JSON" in str(exc_info.value)
    assert issubclass(AdapterPayloadError, AdapterError)


def test_get_json_total_outage_fail_closed():
    """Stress test: PropLine network failure across all 3 retries returns None and logs warning."""
    def mock_urlopen_fail(req, timeout=10.0):
        raise urllib.error.URLError("Connection reset by peer")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_fail):
        with patch("time.sleep", return_value=None):
            payload = _get_json("https://api.prop-line.com/v1/odds", {}, {}, timeout=10.0, max_retries=3, backoff_factor=0.01)

    assert payload is None


# =====================================================================
# 3. TELEGRAM BOT & DAEMON ADVERSARIAL STRESS TESTS
# =====================================================================

def test_telegram_command_casing_variations(tmp_path: Path, monkeypatch):
    """Stress test: Bot commands must be case-insensitive (/KASA, /Kuponlar, /DURUM, /YARDIM)."""
    import telegram_notifier
    monkeypatch.setattr(telegram_notifier, "BANKROLL_FILE", tmp_path / "bankroll.json")
    monkeypatch.setattr(telegram_notifier, "COUPONS_FILE", tmp_path / "coupons.json")

    # UPPERCASE
    res_kasa_upper = process_user_command("/KASA")
    assert "GÜNCEL KASA BİLANÇOSU" in res_kasa_upper

    res_kupon_mixed = process_user_command("/KuPoNlAr")
    assert "BEKLEYEN AKTİF KUPONLAR" in res_kupon_mixed

    res_durum_upper = process_user_command("/DURUM")
    assert "SİSTEM SAĞLIĞI" in res_durum_upper

    res_yardim_upper = process_user_command("/YARDIM")
    assert "KOMUTA MASASI" in res_yardim_upper

    res_help_upper = process_user_command("/HELP")
    assert "KOMUTA MASASI" in res_help_upper


def test_telegram_group_bot_username_syntax_all_commands(tmp_path: Path, monkeypatch):
    """Stress test: Bot username suffixes in Telegram groups (/cmd@OddieroBot) across all endpoints."""
    import telegram_notifier
    monkeypatch.setattr(telegram_notifier, "BANKROLL_FILE", tmp_path / "bankroll.json")
    monkeypatch.setattr(telegram_notifier, "COUPONS_FILE", tmp_path / "coupons.json")

    suffixes = ["@OddieroBot", "@oddierobot", "@ODDIEROBOT", "@Oddiero_Bot"]
    for sfx in suffixes:
        assert "GÜNCEL KASA BİLANÇOSU" in process_user_command(f"/kasa{sfx}")
        assert "BEKLEYEN AKTİF KUPONLAR" in process_user_command(f"/kuponlar{sfx}")
        assert "SİSTEM SAĞLIĞI" in process_user_command(f"/durum{sfx}")
        assert "ODAK MAÇLARIMIZ" in process_user_command(f"/maclar{sfx}")
        assert "KOMUTA MASASI" in process_user_command(f"/yardim{sfx}")


def test_telegram_adversarial_malformed_inputs():
    """Stress test: Malformed, empty, or unexpected user inputs must not raise uncaught exceptions."""
    inputs = [
        "",
        "   ",
        "/",
        "//",
        "/@OddieroBot",
        "/unknown_cmd",
        "/kasa/kuponlar",
        "hello bot",
        "12345",
        "/*-+'~!",
    ]
    for inp in inputs:
        reply = process_user_command(inp)
        assert isinstance(reply, str)
        assert len(reply) > 0


def test_telegram_offset_edge_cases(tmp_path: Path, monkeypatch):
    """Stress test: Offset file parsing edge cases (empty, non-numeric, negative, trailing whitespace)."""
    import telegram_notifier
    offset_file = tmp_path / "telegram_last_update_id.txt"
    monkeypatch.setattr(telegram_notifier, "TELEGRAM_OFFSET_FILE", offset_file)

    # 1. Non-existent -> None
    assert load_telegram_offset() is None

    # 2. Empty string -> None
    offset_file.write_text("", encoding="utf-8")
    assert load_telegram_offset() is None

    # 3. Non-numeric text -> None
    offset_file.write_text("invalid_offset_xyz", encoding="utf-8")
    assert load_telegram_offset() is None

    # 4. Trailing whitespace/newlines -> properly stripped
    offset_file.write_text("   987654 \n", encoding="utf-8")
    assert load_telegram_offset() == 987654

    # 5. Save and reload
    save_telegram_offset(987655)
    assert load_telegram_offset() == 987655


def test_telegram_unauthorized_chat_dropped_offset_advanced(tmp_path: Path, monkeypatch):
    """Stress test: Messages from unauthorized chat IDs must be ignored while offset advances."""
    import telegram_notifier
    offset_file = tmp_path / "offset.txt"
    offset_file.write_text("100", encoding="utf-8")
    monkeypatch.setattr(telegram_notifier, "TELEGRAM_OFFSET_FILE", offset_file)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")  # Only 12345 is authorized

    mock_updates = {
        "ok": True,
        "result": [
            {
                "update_id": 100,
                "message": {
                    "chat": {"id": 99999999},  # UNAUTHORIZED SPAMMER CHAT
                    "text": "/kasa",
                },
            }
        ],
    }

    class MockResp:
        def read(self):
            return json.dumps(mock_updates).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    sent_messages = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5.0: MockResp())
    monkeypatch.setattr(telegram_notifier, "send_telegram_message", lambda msg, **kwargs: sent_messages.append(msg))

    new_offset = check_and_reply_telegram_commands()
    # No message sent to unauthorized sender
    assert len(sent_messages) == 0
    # Offset must advance to 101 to prevent infinite re-processing of spam update
    assert new_offset == 101
    assert load_telegram_offset() == 101


# =====================================================================
# 4. SETTLEMENT ENGINE & LEDGER ADVERSARIAL STRESS TESTS
# =====================================================================

def test_settlement_htft_fail_closed_on_missing_ht_score():
    """Stress test: HT/FT bet must evaluate to False (fail-closed) if half-time score is missing."""
    # When ht_hg or ht_ag is None, evaluate_pick_result must return False
    assert evaluate_pick_result("HT_FT", "1/1", hg=2, ag=0, ht_hg=None, ht_ag=None) is False
    assert evaluate_pick_result("HT_FT", "X/1", hg=1, ag=0, ht_hg=None, ht_ag=0) is False
    assert evaluate_pick_result("HT_FT", "2/2", hg=0, ag=2, ht_hg=0, ht_ag=None) is False


def test_settlement_competitor_inversion_invariant(monkeypatch):
    """Stress test: Regardless of whether home or away is listed first in competitions competitors,
    home score and away score must be mapped to the correct competitor.
    """
    mock_espn = {
        "events": [
            {
                "name": "Team A vs Team B",
                "status": {"type": {"description": "Full Time"}, "period": 2},
                "competitions": [
                    {
                        "competitors": [
                            {
                                "homeAway": "away",
                                "team": {"name": "AwayTeam"},
                                "score": "2",
                                "linescores": [{"period": 1, "value": 1.0}],
                            },
                            {
                                "homeAway": "home",
                                "team": {"name": "HomeTeam"},
                                "score": "4",
                                "linescores": [{"period": 1, "value": 2.0}],
                            },
                        ]
                    }
                ],
            }
        ]
    }

    class MockResp:
        def read(self):
            return json.dumps(mock_espn).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResp()):
        matches = fetch_espn_scores("test.league")

    assert len(matches) == 1
    m = matches[0]
    assert m["home"] == "HomeTeam"
    assert m["away"] == "AwayTeam"
    assert m["hg"] == 4
    assert m["ag"] == 2
    assert m["ht_hg"] == 2
    assert m["ht_ag"] == 1


def test_system_payout_combinatorics_exact_values():
    """Stress test: Combinatorial payouts for System 1,2,3 and System 2,3."""
    pick_a = {"odds": 3.0, "status": "WON"}
    pick_b = {"odds": 4.0, "status": "WON"}
    pick_c = {"odds": 5.0, "status": "WON"}

    # 1 won pick in System 1,2,3 (misli 8):
    # Combos of length 1: (3.0) * 8 = 24.0 TL
    p1 = calculate_system_payout([pick_a], (1, 2, 3), misli=8.0)
    assert p1 == 24.0

    # 2 won picks in System 2,3 (misli 11):
    # Combos of length 2: (3.0 * 4.0) * 11 = 132.0 TL
    p2 = calculate_system_payout([pick_a, pick_b], (2, 3), misli=11.0)
    assert p2 == 132.0

    # 3 won picks in System 2,3 (misli 11):
    # Combos of length 2: (3*4 + 3*5 + 4*5) * 11 = (12 + 15 + 20) * 11 = 47 * 11 = 517.0
    # Combos of length 3: (3 * 4 * 5) * 11 = 60 * 11 = 660.0
    # Total = 517.0 + 660.0 = 1177.0 TL
    p3 = calculate_system_payout([pick_a, pick_b, pick_c], (2, 3), misli=11.0)
    assert p3 == 1177.0

    # 0 won picks -> 0.0 TL
    assert calculate_system_payout([], (1, 2, 3), misli=8.0) == 0.0
    assert calculate_system_payout([], (2, 3), misli=11.0) == 0.0


def test_bankroll_ledger_accounting_conservation(tmp_path: Path, monkeypatch):
    """Stress test: Conservation of total portfolio value and PnL mathematical consistency."""
    import live_settlement_engine
    test_coupons_file = tmp_path / "active_coupons.json"
    test_bankroll_file = tmp_path / "active_bankroll.json"
    monkeypatch.setattr(live_settlement_engine, "COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr(live_settlement_engine, "BANKROLL_FILE", test_bankroll_file)
    monkeypatch.setattr(live_settlement_engine, "send_telegram_message", lambda *args, **kwargs: True)

    # Initial state: 3 coupons total staked = 150 TL, cash = 0 TL, portfolio = 150 TL
    coupons = [
        {
            "id": "c1",
            "name": "Coupon 1",
            "type": "ACCUMULATOR",
            "stake": 50.0,
            "potential_return": 147.0,
            "status": "PENDING",
            "picks": [
                {"match": "M1", "league_key": "fra.1", "market": "1X2", "selection": "MS 1", "odds": 2.94, "status": "PENDING"}
            ],
        },
        {
            "id": "c2",
            "name": "Coupon 2",
            "type": "ACCUMULATOR",
            "stake": 56.0,
            "potential_return": 200.0,
            "status": "PENDING",
            "picks": [
                {"match": "M2", "league_key": "eng.1", "market": "1X2", "selection": "MS 1", "odds": 3.57, "status": "PENDING"}
            ],
        },
    ]
    test_coupons_file.write_text(json.dumps(coupons), encoding="utf-8")

    bankroll = {
        "currency": "TL",
        "initial_bankroll": 150.0,
        "total_staked": 106.0,
        "cash_balance": 44.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "active_tickets_count": 2,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(json.dumps(bankroll), encoding="utf-8")

    # Settle M1: WON (hg=2, ag=0), M2: Still in progress
    def mock_fetch_espn(l_key, *args):
        if l_key == "fra.1":
            return [{"name": "M1", "league": "fra.1", "home": "M1_H", "away": "M1_A", "hg": 2, "ag": 0, "status": "Full Time", "is_completed": True, "is_in_progress": False}]
        return [{"name": "M2", "league": "eng.1", "home": "M2_H", "away": "M2_A", "hg": 0, "ag": 0, "status": "In Progress", "is_completed": False, "is_in_progress": True}]

    # Match pick names
    coupons[0]["picks"][0]["home"] = "M1_H"
    coupons[0]["picks"][0]["away"] = "M1_A"
    coupons[1]["picks"][0]["home"] = "M2_H"
    coupons[1]["picks"][0]["away"] = "M2_A"
    test_coupons_file.write_text(json.dumps(coupons), encoding="utf-8")

    monkeypatch.setattr(live_settlement_engine, "fetch_espn_scores", mock_fetch_espn)

    res = run_settlement_cycle()
    assert res["settled_coupons"] == 1
    assert res["new_winnings"] == 147.0

    updated_b = load_bankroll()
    # Cash: 44.0 + 147.0 = 191.0
    assert updated_b["cash_balance"] == 191.0
    # Active tickets: 1 remaining (c2, stake 56.0)
    assert updated_b["active_tickets_count"] == 1
    assert updated_b["settled_tickets_count"] == 1
    # Total portfolio value = cash (191.0) + active stakes (56.0) = 247.0
    assert updated_b["total_portfolio_value"] == 247.0
    # Realized PnL = winnings from settled (147.0) - stake of settled (50.0) = +97.0
    assert updated_b["realized_pnl"] == 97.0
    assert updated_b["status"] == "PARTIALLY_SETTLED"
