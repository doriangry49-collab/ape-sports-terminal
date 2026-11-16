"""Goal Timing & In-Play Interval Hazard Engine (v1.0).

Analyzes goal distribution patterns across standard 15-minute match intervals:
- 0-15'   : Opening Phase (Tactical sizing up)
- 16-30'  : Mid-First Half (Pattern establishment)
- 31-45+' : Late-First Half (Pre-halftime intensity & psychological blow)
- 46-60'  : Early-Second Half (Halftime tactical adjustments)
- 61-75'  : Mid-Second Half (Fatigue onset & substitution impact)
- 76-90+' : Crunch Window (Fatigue, desperation, late transitions & fat-tail bursts)

Tracks team-specific goal scoring and conceding timing profiles, calculates
joint in-play timing hazard for any elapsed match minute, and integrates
player-level goal event momentum (braces, rapid goal bursts, clutch scorers).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional


MATCH_INTERVALS: list[str] = [
    "0-15",
    "16-30",
    "31-45",
    "46-60",
    "61-75",
    "76-90+",
]

# Historical empirical distribution baseline for European top-tier soccer
DEFAULT_SCORING_BASELINE: dict[str, float] = {
    "0-15": 0.13,
    "16-30": 0.15,
    "31-45": 0.17,
    "46-60": 0.16,
    "61-75": 0.17,
    "76-90+": 0.22,
}

DEFAULT_CONCEDING_BASELINE: dict[str, float] = {
    "0-15": 0.13,
    "16-30": 0.15,
    "31-45": 0.17,
    "46-60": 0.16,
    "61-75": 0.17,
    "76-90+": 0.22,
}


@dataclass
class TeamTimingProfile:
    """Historical goal timing profile for a team across 15-minute intervals."""
    team_name: str
    matches_evaluated: int = 38
    scored_distribution: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORING_BASELINE))
    conceded_distribution: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CONCEDING_BASELINE))
    second_half_scored_ratio: float = 0.55
    second_half_conceded_ratio: float = 0.55
    peak_scoring_interval: str = "76-90+"
    peak_conceding_interval: str = "76-90+"
    clutch_index: float = 1.0          # Multiplier for 76-90+ scoring vs average (e.g. 1.25 = 25% above average)
    late_vulnerability: float = 1.0    # Multiplier for 76-90+ conceding vs average

    def get_scoring_hazard_weight(self, interval: str) -> float:
        """Normalized hazard weight for a given interval (baseline average = 1.0)."""
        pct = self.scored_distribution.get(interval, 0.1667)
        return pct / 0.1667

    def get_conceding_hazard_weight(self, interval: str) -> float:
        """Normalized vulnerability weight for a given interval (baseline average = 1.0)."""
        pct = self.conceded_distribution.get(interval, 0.1667)
        return pct / 0.1667


@dataclass
class LiveTimingEvaluation:
    """Real-time timing hazard analysis for an in-progress match."""
    home_team: str
    away_team: str
    elapsed_min: int
    score_home: int
    score_away: int
    current_interval: str
    upcoming_interval: Optional[str]
    remaining_intervals: list[str]
    home_scoring_weight: float
    away_conceding_weight: float
    away_scoring_weight: float
    home_conceding_weight: float
    joint_hazard_index: float           # 0.0 to 100.0 scale of imminent goal threat
    is_high_pressure_window: bool       # True if joint hazard indicates imminent goal likelihood
    is_crunch_time_active: bool         # True if elapsed >= 75 min with elevated pace
    timing_reasons: list[str] = field(default_factory=list)


@dataclass
class PlayerGoalEvent:
    """Structured goal event with timing and scorer metadata."""
    minute: int
    scorer_name: str
    team_name: str
    is_penalty: bool = False
    is_own_goal: bool = False
    assist_name: Optional[str] = None
    raw_text: str = ""


@dataclass
class LivePlayerThreatContext:
    """Summary of live player scoring momentum and burst dynamics."""
    total_goals: int
    goals: list[PlayerGoalEvent] = field(default_factory=list)
    brace_scorers: list[str] = field(default_factory=list)      # Players with >= 2 goals
    hat_trick_scorers: list[str] = field(default_factory=list)  # Players with >= 3 goals
    has_rapid_burst: bool = False                               # >= 2 goals within 10 minutes
    burst_window_minutes: Optional[int] = None
    last_goal_minute: Optional[int] = None
    momentum_summary: str = ""


# High-Octane Club Timing Priors
PRECONFIGURED_TEAM_PRIORS: dict[str, dict[str, Any]] = {
    "bayern munich": {
        "scored": {"0-15": 0.15, "16-30": 0.18, "31-45": 0.20, "46-60": 0.16, "61-75": 0.14, "76-90+": 0.17},
        "conceded": {"0-15": 0.10, "16-30": 0.14, "31-45": 0.16, "46-60": 0.18, "61-75": 0.20, "76-90+": 0.22},
    },
    "borussia dortmund": {
        "scored": {"0-15": 0.12, "16-30": 0.14, "31-45": 0.16, "46-60": 0.18, "61-75": 0.18, "76-90+": 0.22},
        "conceded": {"0-15": 0.12, "16-30": 0.15, "31-45": 0.18, "46-60": 0.15, "61-75": 0.18, "76-90+": 0.22},
    },
    "manchester city": {
        "scored": {"0-15": 0.16, "16-30": 0.18, "31-45": 0.19, "46-60": 0.15, "61-75": 0.16, "76-90+": 0.16},
        "conceded": {"0-15": 0.08, "16-30": 0.12, "31-45": 0.15, "46-60": 0.18, "61-75": 0.22, "76-90+": 0.25},
    },
    "liverpool": {
        "scored": {"0-15": 0.11, "16-30": 0.13, "31-45": 0.18, "46-60": 0.16, "61-75": 0.18, "76-90+": 0.24},
        "conceded": {"0-15": 0.14, "16-30": 0.12, "31-45": 0.15, "46-60": 0.18, "61-75": 0.18, "76-90+": 0.23},
    },
    "real madrid": {
        "scored": {"0-15": 0.09, "16-30": 0.12, "31-45": 0.16, "46-60": 0.17, "61-75": 0.19, "76-90+": 0.27},
        "conceded": {"0-15": 0.11, "16-30": 0.13, "31-45": 0.16, "46-60": 0.18, "61-75": 0.20, "76-90+": 0.22},
    },
    "galatasaray": {
        "scored": {"0-15": 0.14, "16-30": 0.16, "31-45": 0.18, "46-60": 0.15, "61-75": 0.17, "76-90+": 0.20},
        "conceded": {"0-15": 0.12, "16-30": 0.14, "31-45": 0.16, "46-60": 0.18, "61-75": 0.18, "76-90+": 0.22},
    },
    "fenerbahce": {
        "scored": {"0-15": 0.13, "16-30": 0.15, "31-45": 0.18, "46-60": 0.16, "61-75": 0.18, "76-90+": 0.20},
        "conceded": {"0-15": 0.11, "16-30": 0.13, "31-45": 0.17, "46-60": 0.18, "61-75": 0.19, "76-90+": 0.22},
    },
    "atalanta": {
        "scored": {"0-15": 0.13, "16-30": 0.15, "31-45": 0.18, "46-60": 0.18, "61-75": 0.18, "76-90+": 0.18},
        "conceded": {"0-15": 0.12, "16-30": 0.14, "31-45": 0.16, "46-60": 0.18, "61-75": 0.19, "76-90+": 0.21},
    },
}


def get_minute_interval(minute: int) -> str:
    """Map integer match minute to the canonical 15-minute interval."""
    m = max(1, minute)
    if m <= 15:
        return "0-15"
    elif m <= 30:
        return "16-30"
    elif m <= 45:
        return "31-45"
    elif m <= 60:
        return "46-60"
    elif m <= 75:
        return "61-75"
    else:
        return "76-90+"


def get_remaining_intervals(minute: int) -> list[str]:
    """Return all remaining match intervals starting from the current interval onwards."""
    curr = get_minute_interval(minute)
    try:
        idx = MATCH_INTERVALS.index(curr)
        return MATCH_INTERVALS[idx:]
    except ValueError:
        return ["76-90+"]


class GoalTimingEngine:
    """Engine for Team & Player Goal Timing Analytics and In-Play Hazard Modeling."""

    def __init__(self, custom_team_profiles: Optional[dict[str, TeamTimingProfile]] = None) -> None:
        self.team_profiles: dict[str, TeamTimingProfile] = custom_team_profiles or {}
        self._load_preconfigured_priors()

    def _load_preconfigured_priors(self) -> None:
        """Initialize known club timing profiles from empirical calibration priors."""
        for name, data in PRECONFIGURED_TEAM_PRIORS.items():
            if name not in self.team_profiles:
                scored = data.get("scored", DEFAULT_SCORING_BASELINE)
                conceded = data.get("conceded", DEFAULT_CONCEDING_BASELINE)
                self.team_profiles[name] = self.create_team_profile(
                    team_name=name,
                    scored_dist=scored,
                    conceded_dist=conceded,
                )

    def create_team_profile(
        self,
        team_name: str,
        scored_dist: dict[str, float],
        conceded_dist: dict[str, float],
        matches_evaluated: int = 38,
    ) -> TeamTimingProfile:
        """Create a calibrated TeamTimingProfile from interval distributions."""
        # Normalize distributions to sum to 1.0
        tot_s = sum(scored_dist.values()) or 1.0
        norm_s = {k: round(v / tot_s, 4) for k, v in scored_dist.items()}

        tot_c = sum(conceded_dist.values()) or 1.0
        norm_c = {k: round(v / tot_c, 4) for k, v in conceded_dist.items()}

        # 2nd half ratios (46-60 + 61-75 + 76-90+)
        s2 = round(norm_s.get("46-60", 0) + norm_s.get("61-75", 0) + norm_s.get("76-90+", 0), 3)
        c2 = round(norm_c.get("46-60", 0) + norm_c.get("61-75", 0) + norm_c.get("76-90+", 0), 3)

        # Peaks
        peak_s = max(norm_s.items(), key=lambda x: x[1])[0]
        peak_c = max(norm_c.items(), key=lambda x: x[1])[0]

        # Clutch & Late Vulnerability indices vs uniform baseline (0.1667)
        clutch = round(norm_s.get("76-90+", 0.1667) / 0.1667, 2)
        vuln = round(norm_c.get("76-90+", 0.1667) / 0.1667, 2)

        return TeamTimingProfile(
            team_name=team_name,
            matches_evaluated=matches_evaluated,
            scored_distribution=norm_s,
            conceded_distribution=norm_c,
            second_half_scored_ratio=s2,
            second_half_conceded_ratio=c2,
            peak_scoring_interval=peak_s,
            peak_conceding_interval=peak_c,
            clutch_index=clutch,
            late_vulnerability=vuln,
        )

    def get_or_create_profile(self, team_name: str) -> TeamTimingProfile:
        """Look up team profile by name with fuzzy match, or fallback to default baseline."""
        cleaned = team_name.lower().strip()
        for k, v in self.team_profiles.items():
            if k in cleaned or cleaned in k:
                return v

        # Return baseline profile
        return self.create_team_profile(
            team_name=team_name,
            scored_dist=DEFAULT_SCORING_BASELINE,
            conceded_dist=DEFAULT_CONCEDING_BASELINE,
            matches_evaluated=20,
        )

    def evaluate_live_timing_hazard(
        self,
        home_team: str,
        away_team: str,
        elapsed_min: int,
        score_home: int,
        score_away: int,
        total_shots_rate: float = 0.0,
    ) -> LiveTimingEvaluation:
        """Calculate joint goal timing hazard for the current match minute."""
        m = max(1, min(95, elapsed_min))
        curr_interval = get_minute_interval(m)
        remaining = get_remaining_intervals(m)

        # Identify upcoming interval if any
        upcoming = None
        try:
            curr_idx = MATCH_INTERVALS.index(curr_interval)
            if curr_idx + 1 < len(MATCH_INTERVALS):
                upcoming = MATCH_INTERVALS[curr_idx + 1]
        except ValueError:
            pass

        home_prof = self.get_or_create_profile(home_team)
        away_prof = self.get_or_create_profile(away_team)

        # Scoring & conceding hazard weights for the current interval
        h_score_w = home_prof.get_scoring_hazard_weight(curr_interval)
        a_concede_w = away_prof.get_conceding_hazard_weight(curr_interval)

        a_score_w = away_prof.get_scoring_hazard_weight(curr_interval)
        h_concede_w = home_prof.get_conceding_hazard_weight(curr_interval)

        # Joint hazard components:
        # Home threat = Home scoring tendency * Away defensive vulnerability in this interval
        # Away threat = Away scoring tendency * Home defensive vulnerability in this interval
        home_threat = h_score_w * a_concede_w
        away_threat = a_score_w * h_concede_w
        base_joint_threat = (home_threat + away_threat) / 2.0

        # Game state dynamic multipliers
        score_diff = abs(score_home - score_away)
        state_multiplier = 1.0
        reasons: list[str] = []

        # 1. Trailing / One-goal game urgency
        if score_diff == 1 and m >= 60:
            state_multiplier *= 1.20
            reasons.append(f"Tight 1-goal margin at {m}' increases tactical risk-taking")
        elif score_diff == 0 and m >= 70:
            state_multiplier *= 1.15
            reasons.append(f"Late deadlock at {m}' drives late winner urgency")
        elif score_diff >= 3 and m >= 70:
            state_multiplier *= 0.80
            reasons.append("Blowout lead diminishes late offensive pace")

        # 2. Interval peak alignment
        if curr_interval == home_prof.peak_scoring_interval:
            reasons.append(f"{home_prof.team_name} in PEAK scoring interval ({curr_interval})")
        if curr_interval == away_prof.peak_scoring_interval:
            reasons.append(f"{away_prof.team_name} in PEAK scoring interval ({curr_interval})")
        if curr_interval == home_prof.peak_conceding_interval:
            reasons.append(f"{home_prof.team_name} in PEAK conceding interval ({curr_interval})")
        if curr_interval == away_prof.peak_conceding_interval:
            reasons.append(f"{away_prof.team_name} in PEAK conceding interval ({curr_interval})")

        # 3. High shot tempo
        if total_shots_rate >= 0.35:
            state_multiplier *= 1.12
            reasons.append(f"Elevated shot tempo ({total_shots_rate:.2f} shots/min)")

        # 4. Crunch time (76-90+)
        is_crunch = (curr_interval == "76-90+")
        if is_crunch:
            clutch_blend = (home_prof.clutch_index + away_prof.clutch_index) / 2.0
            if clutch_blend >= 1.15:
                state_multiplier *= 1.15
                reasons.append(f"High collective clutch index ({clutch_blend:.2f}x) in 76-90+' window")

        # Calibrate final joint hazard index on 0-100 scale
        # 1.0 baseline -> ~50 pts, 1.5 -> ~75 pts, 2.0+ -> ~90-100 pts
        effective_threat = base_joint_threat * state_multiplier
        hazard_index = round(min(100.0, max(10.0, effective_threat * 50.0)), 1)

        is_high_pressure = (hazard_index >= 65.0)

        return LiveTimingEvaluation(
            home_team=home_team,
            away_team=away_team,
            elapsed_min=m,
            score_home=score_home,
            score_away=score_away,
            current_interval=curr_interval,
            upcoming_interval=upcoming,
            remaining_intervals=remaining,
            home_scoring_weight=round(h_score_w, 2),
            away_conceding_weight=round(a_concede_w, 2),
            away_scoring_weight=round(a_score_w, 2),
            home_conceding_weight=round(h_concede_w, 2),
            joint_hazard_index=hazard_index,
            is_high_pressure_window=is_high_pressure,
            is_crunch_time_active=is_crunch,
            timing_reasons=reasons,
        )

    def parse_espn_player_events(
        self,
        key_events: list[dict[str, Any]],
        home_team: str = "",
        away_team: str = "",
    ) -> LivePlayerThreatContext:
        """Extract player goal events, braces, and rapid burst dynamics from ESPN keyEvents feed."""
        goal_events: list[PlayerGoalEvent] = []
        player_counts: dict[str, int] = {}
        last_min: Optional[int] = None

        for k in key_events:
            ev_type = str(k.get("type", {}).get("text", "")).lower()
            text = str(k.get("text", ""))

            # Detect goal event
            if "goal" in ev_type or "goal!" in text.lower():
                clock_str = k.get("clock", {}).get("displayValue", "")
                m_match = re.match(r"^(\d+)", clock_str)
                minute = int(m_match.group(1)) if m_match else 45

                is_penalty = "penalty" in text.lower()
                is_own_goal = "own goal" in text.lower()

                # Extract scorer name: e.g.
                # "Goal! Juventus 0, Lyon 1. Marie-Antoinette Katoto (Lyon) right footed shot..." OR
                # "Goal! Harry Kane (Bayern Munich) right footed shot..."
                scorer = "Unknown Player"
                team = ""
                name_match = re.search(r"Goal!\s*(?:[^.]+\.\s*)?([A-Za-z\s\-\'\.]+?)\s*\(([^)]+)\)", text)
                if name_match:
                    scorer = name_match.group(1).strip()
                    team = name_match.group(2).strip()
                else:
                    # Fallback pattern: First words before action
                    p_match = re.search(r"Goal!\s*(?:[^.]+\.\s*)?([A-Za-z\s\-\'\.]+?)\s+(?:right|left|header|scored|penalty|converts)", text)
                    if p_match:
                        scorer = p_match.group(1).strip()

                goal_events.append(
                    PlayerGoalEvent(
                        minute=minute,
                        scorer_name=scorer,
                        team_name=team,
                        is_penalty=is_penalty,
                        is_own_goal=is_own_goal,
                        raw_text=text,
                    )
                )
                player_counts[scorer] = player_counts.get(scorer, 0) + 1
                last_min = minute

        # Detect braces (>= 2) and hat tricks (>= 3)
        braces = [p for p, c in player_counts.items() if c >= 2 and p != "Unknown Player"]
        hat_tricks = [p for p, c in player_counts.items() if c >= 3 and p != "Unknown Player"]

        # Detect rapid burst: any 2 goals within <= 10 minutes of each other
        has_burst = False
        min_gap: Optional[int] = None
        sorted_goals = sorted(goal_events, key=lambda x: x.minute)
        for i in range(len(sorted_goals) - 1):
            gap = sorted_goals[i + 1].minute - sorted_goals[i].minute
            if 0 <= gap <= 10:
                has_burst = True
                if min_gap is None or gap < min_gap:
                    min_gap = gap

        summary_parts: list[str] = []
        if braces:
            summary_parts.append(f"Brace Scorer: {', '.join(braces)}")
        if has_burst and min_gap is not None:
            summary_parts.append(f"Rapid Goal Burst: 2 goals in {min_gap} mins")

        return LivePlayerThreatContext(
            total_goals=len(goal_events),
            goals=goal_events,
            brace_scorers=braces,
            hat_trick_scorers=hat_tricks,
            has_rapid_burst=has_burst,
            burst_window_minutes=min_gap,
            last_goal_minute=last_min,
            momentum_summary="; ".join(summary_parts),
        )
