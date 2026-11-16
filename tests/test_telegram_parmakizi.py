"""Unit tests for /parmakizi Telegram Command and k-NN twin dispatching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from telegram_notifier import get_fingerprint_engine, process_user_command

TRT_TZ = timezone(timedelta(hours=3))
_FUTURE_DT = datetime.now(TRT_TZ) + timedelta(hours=2)

MOCK_PARSED_MATCHES = [
    {
        "home": "Arsenal",
        "away": "Chelsea",
        "nesine_1x2": (1.95, 3.40, 3.60),
        "nesine_ou25": (1.80, 1.85),
        "date_str": _FUTURE_DT.strftime("%d.%m.%Y"),
        "time_str": _FUTURE_DT.strftime("%H:%M"),
        "mbs": 1,
    }
]


@pytest.fixture(scope="module", autouse=True)
def preload_engine():
    """Ensure engine is warmed up and cached in memory."""
    return get_fingerprint_engine()


@patch("telegram_notifier.fetch_nesine_live_bulletin", return_value=MOCK_PARSED_MATCHES)
def test_telegram_parmakizi_command_syntax(mock_fetch):
    """Verify that /parmakizi without team returns first match report."""
    resp = process_user_command("/parmakizi")
    assert isinstance(resp, str)
    assert len(resp) > 10
    assert "TARİHSEL İKİZ" in resp
    assert "Arsenal vs Chelsea" in resp


@patch("telegram_notifier.fetch_nesine_live_bulletin", return_value=MOCK_PARSED_MATCHES)
def test_telegram_parmakizi_command_known_team(mock_fetch):
    """Verify that /parmakizi with matching team returns twin report."""
    resp = process_user_command("/parmakizi Arsenal")
    assert isinstance(resp, str)
    assert "TARİHSEL İKİZ" in resp
    assert "Arsenal vs Chelsea" in resp
    assert "50 TARİHSEL İKİZ" in resp
    assert "Korner Dağılımı" in resp


@patch("telegram_notifier.fetch_nesine_live_bulletin", return_value=MOCK_PARSED_MATCHES)
def test_telegram_parmakizi_command_unknown_team(mock_fetch):
    """Verify that /parmakizi with non-existent team returns informative message."""
    resp = process_user_command("/parmakizi NonExistentTeamXYZ12345")
    assert isinstance(resp, str)
    assert "bulunamadı" in resp
