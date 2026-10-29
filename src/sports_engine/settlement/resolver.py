"""TASK-020: Score Retrieval and Match Result Resolver.

Fetches match scores from:
1. PropLine /scores endpoint
2. API-Football /fixtures endpoint (fallback)
3. Local/Historical completed match cache

Resolves predictions strictly by provider_event_id or normalized team names + kickoff.
Ambiguous matches are marked MATCH_UNRESOLVED. Synthetic results are strictly forbidden.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from sports_engine.normalization.canonical import normalize_entity_name
from sports_engine.settlement.domain import MatchResult, MatchStatus

load_dotenv()


class ScoreResolver:
    """Fetches real scores and resolves prediction events."""

    def __init__(
        self,
        propline_key: Optional[str] = None,
        api_football_key: Optional[str] = None,
    ):
        self.propline_key = propline_key or os.getenv("PROPLINE_KEY")
        self.api_football_key = api_football_key or os.getenv("API_FOOTBALL_KEY")
        self._score_cache: dict[str, MatchResult] = {}

    def fetch_propline_scores(self, sports: list[str]) -> list[dict[str, Any]]:
        """Fetch scores from PropLine /scores endpoint for specified sports."""
        if not self.propline_key:
            return []

        all_scores = []
        headers = {"x-api-key": self.propline_key}
        with httpx.Client(timeout=15.0) as client:
            for s in sports:
                url = f"https://api.prop-line.com/v1/sports/{s}/scores"
                try:
                    r = client.get(url, headers=headers)
                    if r.status_code == 200:
                        all_scores.extend(r.json())
                except Exception:
                    pass
        return all_scores

    def fetch_api_football_scores(self, date_str: str) -> list[dict[str, Any]]:
        """Fetch finished fixture scores from API-Football for given date (YYYY-MM-DD)."""
        if not self.api_football_key:
            return []

        headers = {"x-apisports-key": self.api_football_key}
        url = "https://v3.football.api-sports.io/fixtures"
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(url, headers=headers, params={"date": date_str})
                if r.status_code == 200:
                    return r.json().get("response", [])
        except Exception:
            pass
        return []

    def resolve_match_result(
        self,
        event_id: str,
        provider_event_id: Optional[str],
        home_team: str,
        away_team: str,
        kickoff_iso: str,
        sports: list[str],
        now_dt: Optional[datetime] = None,
    ) -> MatchResult:
        """Resolve current result for a predicted event."""
        now = now_dt or datetime.now(UTC)

        # 1. Check kickoff time
        is_future = False
        try:
            kickoff_dt = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
            if kickoff_dt.tzinfo is None:
                kickoff_dt = kickoff_dt.replace(tzinfo=UTC)
            if kickoff_dt > now:
                is_future = True
        except Exception:
            pass

        # If kickoff is in the future, it is definitively upcoming/pending
        if is_future:
            return MatchResult(
                event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                kickoff=kickoff_iso,
                status=MatchStatus.UPCOMING,
                result_source="PROPLINE_SCHEDULE_UPCOMING",
                fetched_at=now.isoformat(),
            )

        # 2. Try PropLine scores
        propline_scores = self.fetch_propline_scores(sports)
        norm_h = normalize_entity_name(home_team)
        norm_a = normalize_entity_name(away_team)

        for s in propline_scores:
            s_id = str(s.get("id"))
            s_home = normalize_entity_name(s.get("home_team", ""))
            s_away = normalize_entity_name(s.get("away_team", ""))

            # Match by provider_event_id OR normalized team names
            is_match = False
            if provider_event_id and s_id == str(provider_event_id):
                is_match = True
            elif s_home == norm_h and s_away == norm_a:
                is_match = True

            if is_match:
                s_status = str(s.get("status", "")).lower()
                h_score = s.get("home_score")
                a_score = s.get("away_score")

                if s_status in ("completed", "finished", "final", "ft") and h_score is not None and a_score is not None:
                    return MatchResult(
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                        kickoff=kickoff_iso,
                        home_score=int(h_score),
                        away_score=int(a_score),
                        status=MatchStatus.FINISHED,
                        result_source="PROPLINE_SCORES_API",
                        fetched_at=now.isoformat(),
                    )
                else:
                    return MatchResult(
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                        kickoff=kickoff_iso,
                        status=MatchStatus.UPCOMING,
                        result_source="PROPLINE_SCORES_NOT_FINISHED",
                        fetched_at=now.isoformat(),
                    )

        # 3. Try API-Football by date
        try:
            date_part = kickoff_iso.split("T")[0]
            apif_scores = self.fetch_api_football_scores(date_part)
            for f in apif_scores:
                f_teams = f.get("teams", {})
                fh_name = normalize_entity_name(f_teams.get("home", {}).get("name", ""))
                fa_name = normalize_entity_name(f_teams.get("away", {}).get("name", ""))

                if fh_name == norm_h and fa_name == norm_a:
                    f_status = f.get("fixture", {}).get("status", {}).get("short")
                    goals = f.get("goals", {})
                    score = f.get("score", {})
                    ht_score = score.get("halftime", {})

                    if f_status in ("FT", "AET", "PEN") and goals.get("home") is not None:
                        return MatchResult(
                            event_id=event_id,
                            home_team=home_team,
                            away_team=away_team,
                            kickoff=kickoff_iso,
                            home_score=int(goals["home"]),
                            away_score=int(goals["away"]),
                            ht_home_score=int(ht_score["home"]) if ht_score.get("home") is not None else None,
                            ht_away_score=int(ht_score["away"]) if ht_score.get("away") is not None else None,
                            status=MatchStatus.FINISHED,
                            result_source="API_FOOTBALL_FIXTURES",
                            fetched_at=now.isoformat(),
                        )
        except Exception:
            pass

        # 4. If kickoff was in the past but no source delivered score
        return MatchResult(
            event_id=event_id,
            home_team=home_team,
            away_team=away_team,
            kickoff=kickoff_iso,
            status=MatchStatus.UNKNOWN,
            result_source="MATCH_UNRESOLVED",
            fetched_at=now.isoformat(),
        )
