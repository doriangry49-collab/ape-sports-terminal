"""NBA historical dataset builder using public scoreboard feeds with strict temporal anti-leakage."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from config.settings import get_settings
from sports_engine.normalization.canonical import normalize_entity_name


def parse_iso_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string and ensure UTC timezone awareness."""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def fetch_or_load_nba_historical_games(
    seasons: list[int] | None = None,
    limit: int = 600,
    data_cutoff: datetime | None = None,
    force_refresh: bool = False,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch or load historical finished NBA games, applying strict temporal cutoff.

    Args:
        seasons: List of NBA season ending years (default [2024, 2025]).
        limit: Max games to return.
        data_cutoff: Strict temporal cutoff datetime (games strictly after this are excluded).
        force_refresh: If True, queries external public API even if local cache exists.
        cache_path: Optional custom cache file path.

    Returns:
        List of chronological finished NBA match dicts:
        ['game_id', 'event_date', 'home_team', 'away_team', 'home_score', 'away_score', 'home_won']
    """
    settings = get_settings()
    if cache_path is None:
        cache_path = settings.bronze_dir / "nba" / "historical_games.json"

    if seasons is None:
        seasons = [2024, 2025]

    raw_games: dict[str, dict[str, Any]] = {}

    # 1. Try reading from cache if available and not force_refresh
    if cache_path.exists() and not force_refresh:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_list = json.load(f)
                if isinstance(cached_list, list) and len(cached_list) > 0:
                    raw_games = {g["game_id"]: g for g in cached_list}
        except Exception:
            raw_games = {}

    # 2. Fetch from ESPN Public NBA API if empty or force_refresh
    if not raw_games:
        client = httpx.Client(timeout=10.0)
        # Iterate over representative sample of teams (IDs 1-20 cover ~700-1000 unique matchups across 30 teams)
        for season in seasons:
            for team_id in range(1, 21):
                url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule?season={season}"
                try:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        events = resp.json().get("events", [])
                        for ev in events:
                            gid = str(ev.get("id"))
                            if gid in raw_games:
                                continue
                            comps = ev.get("competitions", [])
                            if not comps:
                                continue
                            comp = comps[0]
                            # Only completed games
                            status_obj = comp.get("status", {}).get("type", {})
                            if not status_obj.get("completed"):
                                continue

                            competitors = comp.get("competitors", [])
                            home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
                            away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)

                            if not home_comp or not away_comp:
                                continue

                            h_score_val = home_comp.get("score", {}).get("value")
                            a_score_val = away_comp.get("score", {}).get("value")
                            if h_score_val is None or a_score_val is None:
                                continue

                            h_name = home_comp.get("team", {}).get("displayName", "")
                            a_name = away_comp.get("team", {}).get("displayName", "")

                            raw_games[gid] = {
                                "game_id": gid,
                                "event_date": ev.get("date"),
                                "home_team_raw": h_name,
                                "away_team_raw": a_name,
                                "home_score": int(float(h_score_val)),
                                "away_score": int(float(a_score_val)),
                                "season": season,
                            }
                except Exception:
                    continue

                if len(raw_games) >= limit * 1.5:
                    break
            if len(raw_games) >= limit * 1.5:
                break

        # Persist raw cache
        if raw_games:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(list(raw_games.values()), f, ensure_ascii=False, indent=2)

    # 3. Clean, normalize, and enforce strict temporal anti-leakage
    cleaned_games: list[dict[str, Any]] = []
    for g in raw_games.values():
        raw_date = g.get("event_date")
        if not raw_date:
            continue
        try:
            event_dt = parse_iso_datetime(raw_date)
        except Exception:
            continue

        # Strict cutoff filter
        if data_cutoff is not None and event_dt > data_cutoff:
            continue

        h_norm = normalize_entity_name(g["home_team_raw"])
        a_norm = normalize_entity_name(g["away_team_raw"])
        if not h_norm or not a_norm:
            continue

        h_score = g["home_score"]
        a_score = g["away_score"]

        cleaned_games.append({
            "game_id": g["game_id"],
            "event_date": event_dt.isoformat(),
            "home_team": h_norm,
            "away_team": a_norm,
            "home_team_raw": g["home_team_raw"],
            "away_team_raw": g["away_team_raw"],
            "home_score": h_score,
            "away_score": a_score,
            "home_won": 1 if h_score > a_score else 0,
            "point_margin": h_score - a_score,
        })

    # Sort strictly chronologically ascending (oldest first)
    cleaned_games.sort(key=lambda x: x["event_date"])

    if limit and len(cleaned_games) > limit:
        cleaned_games = cleaned_games[:limit]

    return cleaned_games
