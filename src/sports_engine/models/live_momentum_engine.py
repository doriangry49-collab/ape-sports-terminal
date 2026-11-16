"""Live Match Momentum & Velocity Engine (v2.0).

Quantifies real-time match dynamics:
- Shot Velocity (shots per minute across match duration and rolling windows)
- Shot on Target (SoT) Ratio & Accuracy
- Corner Velocity (corners per minute)
- Attack Symmetry Index (0.0 to 1.0): Evaluates if chances are two-sided (shootout) vs one-sided wall (grind)
- Rolling 15-Minute Shot & Corner Activity (Rolling Window Momentum)
- Danger Index: Combines Shot + SoT + Corner velocities + Symmetry into a unified 0-100 tempo score
- Momentum State Classification:
    * SIEGE_PRESSURE (Danger >= 70): Relentless attacking pressure (prime for escalation/over)
    * ACTIVE_OPEN (50 <= Danger < 70): Healthy back-and-forth tempo
    * BALANCED_NEUTRAL (35 <= Danger < 50): Standard league tempo
    * DEAD_RUBBER / STALL (Danger < 35): Low pace, passivity, time-wasting, or park-the-bus
- Fail-Closed Veto Rules:
    * Vetoes In-Play Goal Anomaly (GASI Ambush) if Shot Velocity < 0.20 or Danger Index < 45
    * Vetoes In-Play Goal Anomaly if Rolling 15m Shots < 2 (tempo suddenly died in recent 15 mins)
    * Vetoes In-Play Goal Anomaly if Wall-Match detected (Possession > 72% but opponent has 0 shots and Total Shots < 14)
    * Vetoes In-Play Corner Sniper if Corner Velocity < 0.08 or Total Attacks stalled
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MomentumState(str, Enum):
    """Dynamic tempo & pressure state of an in-play football match."""
    SIEGE_PRESSURE = "SIEGE_PRESSURE"      # Relentless offensive wave (Danger >= 70)
    ACTIVE_OPEN = "ACTIVE_OPEN"            # Open game, end-to-end chances (50 <= Danger < 70)
    BALANCED_NEUTRAL = "BALANCED_NEUTRAL"  # Average tempo (35 <= Danger < 50)
    STALL_DEFENSIVE = "STALL_DEFENSIVE"    # Grind / defensive lock / dead rubber (Danger < 35)


@dataclass(frozen=True)
class LiveMomentumEvaluation:
    """Quantitative outcome of a live match momentum evaluation."""
    elapsed_min: int
    total_shots: int
    shots_on_target: int
    total_corners: int
    shot_velocity: float           # shots / min
    sot_velocity: float            # shots on target / min
    sot_accuracy: float            # sot / total_shots (0.0 to 1.0)
    corner_velocity: float         # corners / min
    danger_index: float            # Unified 0 - 100 pressure score
    state: MomentumState
    attack_symmetry: float         # 0.0 (one-sided bus) to 1.0 (perfect balance)
    is_wall_match: bool            # True if 1-sided park-the-bus defense grind
    rolling_15m_shots: int         # Estimated or parsed shots in last 15 mins
    rolling_15m_corners: int       # Estimated or parsed corners in last 15 mins
    is_ambush_qualified: bool      # Passes fail-closed tempo bar for Goal Anomaly
    is_corner_qualified: bool      # Passes fail-closed tempo bar for Corner Sniper
    veto_reasons: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)


class LiveMomentumEngine:
    """Calculates granular real-time velocity metrics from live match statistics."""

    MIN_AMBUSH_SHOT_VELOCITY: float = 0.20       # At least 1 shot every 5 mins
    MIN_AMBUSH_DANGER_INDEX: float = 45.0        # Minimum offensive intensity
    MIN_CORNER_VELOCITY: float = 0.08           # At least 1 corner every 12 mins
    MIN_CORNER_DANGER_INDEX: float = 40.0
    MIN_ROLLING_15M_SHOTS: int = 2              # At least 2 shots in recent 15m window

    def parse_rolling_events(
        self,
        key_events: list[dict[str, Any]] | None,
        elapsed_min: int,
        window_minutes: int = 15,
    ) -> tuple[int, int]:
        """Extract number of shots and corners occurring within the last N minutes from key events."""
        if not key_events or elapsed_min <= 0:
            return 0, 0

        cutoff_min = max(0, elapsed_min - window_minutes)
        window_shots = 0
        window_corners = 0

        clock_regex = re.compile(r"(\d+)")

        for ev in key_events:
            text = str(ev.get("text", "")).lower()
            ev_type = str(ev.get("type", {}).get("text", "")).lower()

            # Parse event clock minute
            clock_val = ev.get("clock", {})
            min_str = clock_val.get("displayValue", "") if isinstance(clock_val, dict) else str(clock_val)
            m = clock_regex.search(min_str)
            if not m:
                continue

            ev_min = int(m.group(1))
            if ev_min >= cutoff_min:
                if "goal" in ev_type or "goal" in text or "shot" in text:
                    window_shots += 1
                if "corner" in text:
                    window_corners += 1

        return window_shots, window_corners

    def evaluate_momentum(
        self,
        elapsed_min: int,
        total_shots: int,
        shots_on_target: int = 0,
        total_corners: int = 0,
        home_shots: int | None = None,
        away_shots: int | None = None,
        home_possession: float = 50.0,
        away_possession: float = 50.0,
        red_cards_total: int = 0,
        current_score_diff: int = 0,
        key_events: list[dict[str, Any]] | None = None,
        rolling_15m_shots: int | None = None,
        rolling_15m_corners: int | None = None,
    ) -> LiveMomentumEvaluation:
        """Evaluate match momentum, symmetry, and rolling velocity from live match telemetry."""
        safe_min = max(1, elapsed_min)

        shot_vel = round(total_shots / safe_min, 3)
        sot_vel = round(shots_on_target / safe_min, 3) if shots_on_target > 0 else round(shot_vel * 0.35, 3)
        corner_vel = round(total_corners / safe_min, 3)
        sot_acc = round(shots_on_target / max(1, total_shots), 3) if shots_on_target > 0 else 0.35

        # 1. Attack Symmetry & Wall Match Detection
        # Symmetry = 1.0 - abs(home_shots - away_shots) / total_shots (if shots provided)
        if home_shots is not None and away_shots is not None and total_shots > 0:
            h_s = max(0, home_shots)
            a_s = max(0, away_shots)
            tot_s = max(1, h_s + a_s)
            symmetry = round(1.0 - (abs(h_s - a_s) / tot_s), 2)
        else:
            # Fallback based on possession parity
            poss_skew = abs(home_possession - away_possession)
            symmetry = round(max(0.20, 1.0 - (poss_skew / 100.0)), 2)

        # Detect Wall Match: Severe one-sided siege where inferior team parks the bus
        # (e.g. Possession >= 72% or one team has <= 1 shot after 55 min while total shots < 16)
        is_wall_match = False
        if safe_min >= 50:
            if max(home_possession, away_possession) >= 72.0:
                is_wall_match = True
            elif home_shots is not None and away_shots is not None:
                min_side = min(home_shots, away_shots)
                max_side = max(home_shots, away_shots)
                if min_side <= 1 and max_side >= 8 and total_shots < 16:
                    is_wall_match = True

        # 2. Rolling 15-Minute Window Velocity
        if rolling_15m_shots is not None and rolling_15m_corners is not None:
            r15_shots = rolling_15m_shots
            r15_corners = rolling_15m_corners
        elif key_events and safe_min >= 20:
            parsed_shots, parsed_corners = self.parse_rolling_events(key_events, safe_min, window_minutes=15)
            # Baseline estimation blended with parsed key events (since not all shots are key events)
            exp_15m = int(round(shot_vel * 15.0))
            r15_shots = max(parsed_shots, exp_15m)
            r15_corners = max(parsed_corners, int(round(corner_vel * 15.0)))
        else:
            # Pro-rated rolling estimation
            r15_shots = int(round(shot_vel * min(15, safe_min)))
            r15_corners = int(round(corner_vel * min(15, safe_min)))

        # 3. Danger Index Formula (0 - 100):
        # Base components:
        shot_pts = min(40.0, (shot_vel / 0.40) * 40.0)
        sot_pts = min(30.0, (sot_vel / 0.18) * 30.0)
        corner_pts = min(20.0, (corner_vel / 0.16) * 20.0)

        # Symmetry & Context Modifier (-15 to +10 pts):
        context_pts = 0.0

        # Two-sided shootout boost (+5 pts for high symmetry)
        if symmetry >= 0.70 and shot_vel >= 0.25:
            context_pts += 5.0
        # Wall match penalty (-12 pts for stubborn park-the-bus grind)
        elif is_wall_match:
            context_pts -= 12.0

        # Trailing by 1 goal (desperation push): +5 pts
        if current_score_diff == 1 and safe_min >= 60:
            context_pts += 5.0
        elif current_score_diff >= 3 and safe_min >= 70:
            context_pts -= 5.0

        if red_cards_total > 0 and safe_min >= 45:
            context_pts += 5.0

        raw_danger = shot_pts + sot_pts + corner_pts + context_pts
        danger_index = round(max(0.0, min(100.0, raw_danger)), 1)

        # 4. Determine State
        if danger_index >= 70.0:
            state = MomentumState.SIEGE_PRESSURE
        elif danger_index >= 50.0:
            state = MomentumState.ACTIVE_OPEN
        elif danger_index >= 35.0:
            state = MomentumState.BALANCED_NEUTRAL
        else:
            state = MomentumState.STALL_DEFENSIVE

        # 5. Qualification & Fail-Closed Veto Logic
        veto_reasons: list[str] = []
        signals: list[str] = []

        is_ambush_qualified = True
        is_corner_qualified = True

        # Check A: Shot Velocity threshold
        if shot_vel < self.MIN_AMBUSH_SHOT_VELOCITY:
            is_ambush_qualified = False
            veto_reasons.append(
                f"Şut temposu yetersiz ({shot_vel:.2f} şut/dk < {self.MIN_AMBUSH_SHOT_VELOCITY:.2f} eşiği)"
            )

        # Check B: Unified Danger Index threshold
        if danger_index < self.MIN_AMBUSH_DANGER_INDEX:
            is_ambush_qualified = False
            veto_reasons.append(
                f"Canlı tehlike endeksi düşük ({danger_index:.1f}/100 < {self.MIN_AMBUSH_DANGER_INDEX:.1f} eşiği)"
            )

        # Check C: Rolling 15-Minute Window Stalled
        if safe_min >= 60 and r15_shots < self.MIN_ROLLING_15M_SHOTS:
            is_ambush_qualified = False
            veto_reasons.append(
                f"Son 15 dakikada şut temposu çöktü ({r15_shots} şut < {self.MIN_ROLLING_15M_SHOTS} asgari)"
            )

        # Check D: Defensive Wall Match Veto
        if is_wall_match and danger_index < 55.0:
            is_ambush_qualified = False
            veto_reasons.append(
                "Duvar Maçı Vetosu: Tek taraflı savunma kilidi ve düşük hücum simetrisi"
            )

        # Corner Sniper Veto Checks
        if corner_vel < self.MIN_CORNER_VELOCITY:
            is_corner_qualified = False
            veto_reasons.append(
                f"Korner temposu durgun ({corner_vel:.2f} korner/dk < {self.MIN_CORNER_VELOCITY:.2f} eşiği)"
            )

        if danger_index < self.MIN_CORNER_DANGER_INDEX:
            is_corner_qualified = False

        # Positive Signals
        if state == MomentumState.SIEGE_PRESSURE:
            signals.append(f"Abluka Baskısı: {shot_vel:.2f} şut/dk ve {corner_vel:.2f} korner/dk ile kriz penceresi aktif")
        elif state == MomentumState.ACTIVE_OPEN:
            signals.append(f"Açık Düello: Simetri %{symmetry*100:.0f} ile karşılıklı pozisyon üretimi sürüyor")

        if is_wall_match:
            signals.append("Duvar Maçı Uyarısı: Rakip takım tamamen kapandı")

        return LiveMomentumEvaluation(
            elapsed_min=safe_min,
            total_shots=total_shots,
            shots_on_target=shots_on_target,
            total_corners=total_corners,
            shot_velocity=shot_vel,
            sot_velocity=sot_vel,
            sot_accuracy=sot_acc,
            corner_velocity=corner_vel,
            danger_index=danger_index,
            state=state,
            attack_symmetry=symmetry,
            is_wall_match=is_wall_match,
            rolling_15m_shots=r15_shots,
            rolling_15m_corners=r15_corners,
            is_ambush_qualified=is_ambush_qualified,
            is_corner_qualified=is_corner_qualified,
            veto_reasons=veto_reasons,
            signals=signals,
        )
