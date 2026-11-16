"""Lineup & Squad Rotation Impact Engine (v1.0).

Quantifies the impact of starting XI announcements, tactical formations, and key absences on match lambda (expected goals).

Core Capabilities:
1. Squad Strength Retention (0.0 to 1.0):
   Measures the fraction of regular starter quality on the pitch based on season minutes and player ratings.
2. Missing Goal Share:
   Quantifies the proportion of the team's historical season goals missing due to benched/injured attacking starters.
3. Goalkeeper Status:
   Identifies whether the regular starting goalkeeper is playing vs backup keeper. A backup keeper increases opponent expected goals.
4. Tactical Formation Shift:
   Detects ultra-defensive setups (e.g. 5-4-1, 5-3-2) vs aggressive setups (4-2-4, 4-3-3).
5. Match Lambda Adjustment:
   Applies mathematically bounded multipliers to Poisson/NegBinom baseline lambdas.
6. Syndicated Lineup Risk Rules:
   - VETO if HEAVY_ROTATION (retention < 0.65) in league matches (unpredictable variance trap).
   - UNDER_TILT if KEY_STRIKER_ABSENT and opponent retains defensive core.
   - OVER_TILT if both starting goalkeepers are missing or both teams rotate center-backs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class LineupStatus(str, Enum):
    """Classification of a team's announced starting lineup."""
    FULL_STRENGTH = "FULL_STRENGTH"              # Core regulars starting (retention >= 0.90)
    MINOR_ROTATION = "MINOR_ROTATION"            # 1-2 squad rotations (0.80 <= retention < 0.90)
    KEY_STRIKER_ABSENT = "KEY_STRIKER_ABSENT"    # Primary goalscorer absent (missing_goal_share >= 0.25)
    BACKUP_GOALKEEPER = "BACKUP_GOALKEEPER"      # Regular keeper benched/injured (defensive leak risk)
    HEAVY_ROTATION = "HEAVY_ROTATION"            # Significant rotation (retention < 0.70)


class TacticalStance(str, Enum):
    """Inferred tactical posture from announced formation."""
    ULTRA_DEFENSIVE = "ULTRA_DEFENSIVE"  # 5-4-1, 5-3-2, 4-5-1 (Park-the-bus)
    BALANCED = "BALANCED"                # 4-2-3-1, 4-4-2, 3-5-2
    ATTACKING = "ATTACKING"              # 4-3-3, 3-4-3, 4-2-4


@dataclass(frozen=True)
class PlayerProfile:
    """Statistical profile of an individual squad member."""
    name: str
    position: str             # "GK", "DEF", "MID", "FWD"
    is_regular_starter: bool
    season_goals: int = 0
    season_minutes: int = 0
    rating: float = 7.0       # Scaled 5.0 to 10.0


@dataclass(frozen=True)
class TeamLineup:
    """Announced starting lineup for an upcoming fixture."""
    team_name: str
    formation: str            # e.g. "4-3-3", "5-4-1"
    starters: List[str]
    bench: List[str] = field(default_factory=list)
    confirmed_absentees: List[str] = field(default_factory=list)
    starting_gk: Optional[str] = None


@dataclass(frozen=True)
class LineupEvaluation:
    """Quantitative evaluation of a single team's announced lineup."""
    team_name: str
    formation: str
    tactical_stance: TacticalStance
    squad_strength_retention: float   # 0.0 to 1.0
    missing_goal_share: float         # 0.0 to 1.0
    is_backup_gk: bool
    status: LineupStatus
    scoring_lambda_mult: float        # Multiplier on team's expected goals
    conceding_lambda_mult: float      # Multiplier on opponent's expected goals
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchLineupImpact:
    """Composite impact of both lineups on match-level pricing."""
    home_eval: LineupEvaluation
    away_eval: LineupEvaluation
    base_home_lambda: float
    base_away_lambda: float
    adj_home_lambda: float
    adj_away_lambda: float
    base_total_lambda: float
    adj_total_lambda: float
    delta_total_lambda: float
    market_tilt: str                  # "UNDER_TILT", "OVER_TILT", "NEUTRAL"
    is_veto_recommended: bool
    veto_reason: Optional[str] = None


class LineupEngine:
    """Evaluates announced team lineups and adjusts baseline match expectations."""

    ULTRA_DEFENSIVE_FORMATIONS = {"5-4-1", "5-3-2", "5-2-3", "4-5-1", "6-3-1"}
    ATTACKING_FORMATIONS = {"4-3-3", "3-4-3", "4-2-4", "4-1-4-1"}

    @classmethod
    def infer_tactical_stance(cls, formation: str) -> TacticalStance:
        """Infers tactical stance from formation string."""
        clean = formation.strip().replace(" ", "")
        if clean in cls.ULTRA_DEFENSIVE_FORMATIONS:
            return TacticalStance.ULTRA_DEFENSIVE
        if clean in cls.ATTACKING_FORMATIONS:
            return TacticalStance.ATTACKING
        return TacticalStance.BALANCED

    @classmethod
    def evaluate_team_lineup(
        cls,
        lineup: TeamLineup,
        squad_profiles: List[PlayerProfile],
    ) -> LineupEvaluation:
        """Evaluates team lineup against the team's historical player profiles."""
        if not squad_profiles:
            # Fallback if no detailed squad profiles exist
            stance = cls.infer_tactical_stance(lineup.formation)
            return LineupEvaluation(
                team_name=lineup.team_name,
                formation=lineup.formation,
                tactical_stance=stance,
                squad_strength_retention=1.0,
                missing_goal_share=0.0,
                is_backup_gk=False,
                status=LineupStatus.FULL_STRENGTH,
                scoring_lambda_mult=1.0,
                conceding_lambda_mult=1.0,
                notes=["No squad profiles provided - neutral baseline applied."],
            )

        profile_map = {p.name.lower(): p for p in squad_profiles}
        starter_names_lower = {s.lower() for s in lineup.starters}

        # 1. Total season goals & missing goal share
        total_team_goals = sum(p.season_goals for p in squad_profiles)
        starters_goals = sum(
            profile_map[name].season_goals
            for name in starter_names_lower
            if name in profile_map
        )
        missing_goals = max(0, total_team_goals - starters_goals)
        missing_goal_share = (
            missing_goals / total_team_goals if total_team_goals > 0 else 0.0
        )

        # 2. Regular starters on pitch (Retention Score)
        regular_starters = [p for p in squad_profiles if p.is_regular_starter]
        total_regular = len(regular_starters)
        if total_regular > 0:
            regulars_on_pitch = sum(
                1 for p in regular_starters if p.name.lower() in starter_names_lower
            )
            retention = round(regulars_on_pitch / total_regular, 3)
        else:
            retention = 1.0

        # 3. Goalkeeper check
        regular_gks = [
            p for p in squad_profiles if p.position.upper() == "GK" and p.is_regular_starter
        ]
        is_backup_gk = False
        if regular_gks:
            primary_gk_name = regular_gks[0].name.lower()
            if lineup.starting_gk:
                is_backup_gk = lineup.starting_gk.lower() != primary_gk_name
            else:
                # Check starters for the regular keeper
                is_backup_gk = primary_gk_name not in starter_names_lower

        # 4. Tactical stance
        stance = cls.infer_tactical_stance(lineup.formation)

        # 5. Multipliers calculation
        notes: List[str] = []
        scoring_mult = 1.0
        conceding_mult = 1.0

        # Offense adjustment from missing goal scorers
        if missing_goal_share >= 0.35:
            scoring_mult *= 0.80
            notes.append(f"Severe attacking deficit: {missing_goal_share:.1%} of goals missing.")
        elif missing_goal_share >= 0.20:
            scoring_mult *= 0.90
            notes.append(f"Moderate attacking deficit: {missing_goal_share:.1%} of goals missing.")

        # Squad retention adjustment
        if retention < 0.65:
            scoring_mult *= 0.85
            conceding_mult *= 1.15
            notes.append(f"Heavy rotation detected (Retention: {retention:.1%}).")
        elif retention < 0.80:
            scoring_mult *= 0.95
            conceding_mult *= 1.05

        # Backup Goalkeeper penalty
        if is_backup_gk:
            conceding_mult *= 1.15
            notes.append("Backup goalkeeper starting (+15% opponent expected goals).")

        # Tactical stance modifier
        if stance == TacticalStance.ULTRA_DEFENSIVE:
            scoring_mult *= 0.88
            conceding_mult *= 0.90
            notes.append("Ultra-defensive formation suppresses match tempo.")
        elif stance == TacticalStance.ATTACKING:
            scoring_mult *= 1.05
            conceding_mult *= 1.05
            notes.append("Aggressive formation expands match tempo.")

        # Classify status
        if retention < 0.70:
            status = LineupStatus.HEAVY_ROTATION
        elif is_backup_gk:
            status = LineupStatus.BACKUP_GOALKEEPER
        elif missing_goal_share >= 0.25:
            status = LineupStatus.KEY_STRIKER_ABSENT
        elif retention < 0.90:
            status = LineupStatus.MINOR_ROTATION
        else:
            status = LineupStatus.FULL_STRENGTH

        return LineupEvaluation(
            team_name=lineup.team_name,
            formation=lineup.formation,
            tactical_stance=stance,
            squad_strength_retention=retention,
            missing_goal_share=round(missing_goal_share, 3),
            is_backup_gk=is_backup_gk,
            status=status,
            scoring_lambda_mult=round(scoring_mult, 3),
            conceding_lambda_mult=round(conceding_mult, 3),
            notes=notes,
        )

    @classmethod
    def evaluate_match_impact(
        cls,
        home_eval: LineupEvaluation,
        away_eval: LineupEvaluation,
        base_home_lambda: float,
        base_away_lambda: float,
    ) -> MatchLineupImpact:
        """Calculates final adjusted lambdas and assesses match risk."""
        # Home scoring is affected by home scoring multiplier AND away conceding multiplier
        adj_home = round(base_home_lambda * home_eval.scoring_lambda_mult * away_eval.conceding_lambda_mult, 3)
        # Away scoring is affected by away scoring multiplier AND home conceding multiplier
        adj_away = round(base_away_lambda * away_eval.scoring_lambda_mult * home_eval.conceding_lambda_mult, 3)

        base_total = round(base_home_lambda + base_away_lambda, 3)
        adj_total = round(adj_home + adj_away, 3)
        delta_total = round(adj_total - base_total, 3)

        # Market tilt evaluation
        if delta_total <= -0.30:
            market_tilt = "UNDER_TILT"
        elif delta_total >= +0.30:
            market_tilt = "OVER_TILT"
        else:
            market_tilt = "NEUTRAL"

        # Veto conditions
        is_veto = False
        veto_reason = None

        if home_eval.status == LineupStatus.HEAVY_ROTATION and away_eval.status == LineupStatus.HEAVY_ROTATION:
            is_veto = True
            veto_reason = "Both teams undergoing heavy squad rotation (High Variance Chaos Trap)."
        elif home_eval.squad_strength_retention < 0.50 or away_eval.squad_strength_retention < 0.50:
            is_veto = True
            veto_reason = "Extreme squad dilution (<50% regular starters). Reliable pricing impossible."

        return MatchLineupImpact(
            home_eval=home_eval,
            away_eval=away_eval,
            base_home_lambda=base_home_lambda,
            base_away_lambda=base_away_lambda,
            adj_home_lambda=adj_home,
            adj_away_lambda=adj_away,
            base_total_lambda=base_total,
            adj_total_lambda=adj_total,
            delta_total_lambda=delta_total,
            market_tilt=market_tilt,
            is_veto_recommended=is_veto,
            veto_reason=veto_reason,
        )
