"""Unit and Integration tests for Live Momentum & Velocity Engine."""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from sports_engine.models.live_momentum_engine import (
    LiveMomentumEngine,
    LiveMomentumEvaluation,
    MomentumState,
)


@pytest.fixture
def momentum_engine():
    return LiveMomentumEngine()


def test_high_intensity_siege_pressure(momentum_engine):
    """Verify that a high-octane match (e.g. 24 shots, 10 SoT, 8 corners in 60 mins) triggers SIEGE_PRESSURE."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=60,
        total_shots=24,
        shots_on_target=10,
        total_corners=8,
        current_score_diff=1,
    )

    assert res.state == MomentumState.SIEGE_PRESSURE
    assert res.shot_velocity == 0.40
    assert res.corner_velocity == 0.133
    assert res.danger_index >= 70.0
    assert res.is_ambush_qualified is True
    assert res.is_corner_qualified is True
    assert len(res.signals) > 0


def test_low_pace_stall_veto_for_ambush(momentum_engine):
    """Verify that a stagnant match (e.g. 6 shots, 2 corners in 65 mins) is vetoed for Goal Ambush."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=65,
        total_shots=6,
        shots_on_target=1,
        total_corners=2,
        current_score_diff=0,
    )

    assert res.state == MomentumState.STALL_DEFENSIVE
    assert res.shot_velocity == 0.092
    assert res.corner_velocity == 0.031
    assert res.danger_index < 35.0
    assert res.is_ambush_qualified is False
    assert res.is_corner_qualified is False
    assert any("Şut temposu yetersiz" in v for v in res.veto_reasons)
    assert any("Canlı tehlike endeksi düşük" in v for v in res.veto_reasons)


def test_active_open_tempo_qualifies(momentum_engine):
    """Verify that an active open match (e.g. 15 shots, 5 SoT, 5 corners in 55 mins) qualifies."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=55,
        total_shots=15,
        shots_on_target=5,
        total_corners=5,
        current_score_diff=0,
    )

    assert res.state == MomentumState.ACTIVE_OPEN
    assert res.is_ambush_qualified is True
    assert res.danger_index >= 50.0


def test_zero_minute_guard(momentum_engine):
    """Verify fail-safe against 0 or negative minute elapsed values."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=0,
        total_shots=0,
        shots_on_target=0,
        total_corners=0,
    )
    assert res.elapsed_min == 1
    assert res.shot_velocity == 0.0
    assert res.is_ambush_qualified is False


def test_rolling_15m_window_stall_veto(momentum_engine):
    """Verify that a match active early on but with 0 shots in last 15m is vetoed."""
    # 65th minute: total 14 shots, but rolling 15m shots is explicitly 0 (stalled!)
    res = momentum_engine.evaluate_momentum(
        elapsed_min=65,
        total_shots=14,
        shots_on_target=5,
        total_corners=5,
        rolling_15m_shots=0,
        rolling_15m_corners=0,
    )
    assert res.is_ambush_qualified is False
    assert any("Son 15 dakikada şut temposu çöktü" in v for v in res.veto_reasons)


def test_defensive_wall_match_veto(momentum_engine):
    """Verify that extreme one-sided possession (76% vs 24%) with zero opponent shots is penalized."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=62,
        total_shots=10,
        shots_on_target=3,
        total_corners=4,
        home_shots=10,
        away_shots=0,
        home_possession=76.0,
        away_possession=24.0,
    )
    assert res.is_wall_match is True
    assert res.attack_symmetry <= 0.25
    assert res.is_ambush_qualified is False
    assert any("Duvar Maçı Vetosu" in v for v in res.veto_reasons)


def test_high_symmetry_shootout_boost(momentum_engine):
    """Verify that a 50-50 open shootout (e.g. 10 shots vs 9 shots) receives symmetry bonus."""
    res = momentum_engine.evaluate_momentum(
        elapsed_min=55,
        total_shots=19,
        shots_on_target=7,
        total_corners=6,
        home_shots=10,
        away_shots=9,
        home_possession=51.0,
        away_possession=49.0,
    )
    assert res.is_wall_match is False
    assert res.attack_symmetry >= 0.90
    assert res.state == MomentumState.SIEGE_PRESSURE
    assert res.is_ambush_qualified is True

