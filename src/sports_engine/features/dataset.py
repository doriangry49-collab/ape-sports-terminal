"""Dataset builder for football model training with strict point-in-time cutoff."""

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


def fetch_or_load_historical_matches(
    league_id: int = 11,
    limit: int = 200,
    data_cutoff: datetime | None = None,
    force_refresh: bool = False,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch or load historical finished matches for a league, applying strict temporal cutoff.

    Args:
        league_id: Provider league ID (default 11 for Süper Lig in Bzzoiro).
        limit: Number of recent historical matches to fetch (e.g. 200).
        data_cutoff: Strict point-in-time timestamp: matches after this cutoff are discarded (anti-leakage).
        force_refresh: If True, queries external API even if local cache exists.
        cache_path: Optional custom path for local caching.

    Returns:
        List of normalized match dictionaries with keys:
        ['home_team', 'away_team', 'home_score', 'away_score', 'event_date', 'raw_home', 'raw_away']
    """
    settings = get_settings()
    if cache_path is None:
        cache_path = settings.data_dir / "bronze" / "bzzoiro" / f"finished_matches_league_{league_id}.json"

    raw_matches: list[dict[str, Any]] = []

    # 1. Try reading from cache if available and not force_refresh
    if cache_path.exists() and not force_refresh:
        try:
            with open(cache_path, encoding="utf-8") as f:
                raw_matches = json.load(f)
        except Exception:
            raw_matches = []

    # 2. Fetch from Bzzoiro API if raw_matches is empty or force_refresh
    if not raw_matches and settings.bzzoiro_key:
        headers = {"Authorization": f"Token {settings.bzzoiro_key}"}
        fetched: list[dict[str, Any]] = []
        batch_size = min(100, limit)
        offset = 0

        while len(fetched) < limit:
            url = f"https://sports.bzzoiro.com/api/v2/events/?league={league_id}&status=finished&limit={batch_size}&offset={offset}"
            try:
                resp = httpx.get(url, headers=headers, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break
                    fetched.extend(results)
                    offset += len(results)
                    if len(results) < batch_size:
                        break
                else:
                    break
            except Exception:
                break

        if fetched:
            raw_matches = fetched
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(raw_matches, f, ensure_ascii=False, indent=2)

    # 3. Fallback: check provider_validation raw artifacts if still empty
    if not raw_matches:
        fallback_art = get_settings().project_root / "artifacts" / "provider_validation" / "raw" / "bzzoiro" / "Event Discovery_20260929_154507.json"
        if not fallback_art.exists():
            fallback_art = Path("artifacts/provider_validation/raw/bzzoiro/Event Discovery_20260929_154507.json")
        if fallback_art.exists():
            try:
                with open(fallback_art, encoding="utf-8") as f:
                    ev_data = json.load(f)
                    raw_matches = ev_data.get("results", [])
            except Exception:
                raw_matches = []

    # 4. Normalize records and enforce data_cutoff
    cleaned_matches: list[dict[str, Any]] = []

    for m in raw_matches:
        h_score = m.get("home_score")
        a_score = m.get("away_score")

        # Skip matches without valid scorelines
        if h_score is None or a_score is None:
            continue

        raw_date_str = m.get("event_date")
        if not raw_date_str:
            continue

        try:
            event_dt = parse_iso_datetime(raw_date_str)
        except Exception:
            continue

        # STRICT DATA CUTOFF: Anti-leakage rule
        if data_cutoff is not None and event_dt > data_cutoff:
            continue

        raw_home = m.get("home_team", "")
        raw_away = m.get("away_team", "")
        norm_home = normalize_entity_name(raw_home)
        norm_away = normalize_entity_name(raw_away)

        if not norm_home or not norm_away:
            continue

        cleaned_matches.append({
            "home_team": norm_home,
            "away_team": norm_away,
            "home_score": int(h_score),
            "away_score": int(a_score),
            "event_date": event_dt.isoformat(),
            "raw_home": raw_home,
            "raw_away": raw_away,
        })

    return cleaned_matches
