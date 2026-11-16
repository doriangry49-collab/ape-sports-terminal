"""Unit tests for Live Sniper Daemon Adaptive Polling."""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from live_sniper_daemon import (
    calculate_adaptive_sleep,
    IDLE_SLEEP_SECONDS,
    ACTIVE_SLEEP_SECONDS,
    CRUNCH_SLEEP_SECONDS,
)


def test_adaptive_sleep_when_no_matches():
    """Verify that 0 active matches triggers IDLE_SLEEP (10 mins / 600s)."""
    assert calculate_adaptive_sleep([]) == IDLE_SLEEP_SECONDS


def test_adaptive_sleep_when_active_matches():
    """Verify that matches in normal time (e.g. 35') trigger ACTIVE_SLEEP (3 mins / 180s)."""
    matches = [{"name": "A vs B", "elapsed_min": 35}]
    assert calculate_adaptive_sleep(matches) == ACTIVE_SLEEP_SECONDS


def test_adaptive_sleep_when_crunch_window():
    """Verify that matches in late ambush/crunch window (e.g. 68') trigger CRUNCH_SLEEP (2 mins / 120s)."""
    matches = [{"name": "A vs B", "elapsed_min": 68}]
    assert calculate_adaptive_sleep(matches) == CRUNCH_SLEEP_SECONDS
