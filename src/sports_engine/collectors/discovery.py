"""Multi-sport discovery and event availability engine."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from config.settings import get_settings


def categorize_sport(sport_key: str) -> str:
    """Categorize sport key into broad family."""
    if sport_key.startswith("soccer_"):
        return "Football"
    elif sport_key.startswith("basketball_"):
        return "Basketball"
    elif sport_key.startswith("baseball_"):
        return "Baseball"
    elif "tennis" in sport_key:
        return "Tennis"
    elif sport_key.startswith("hockey_"):
        return "Hockey"
    elif sport_key.startswith("football_"):
        return "American Football"
    elif any(k in sport_key for k in ["mma_", "boxing"]):
        return "Combat Sports"
    elif "golf" in sport_key:
        return "Golf"
    return "Other"


def discover_all_sports(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Discover all supported sports from PropLine API or local cached artifact."""
    settings = get_settings()
    artifact_dir = Path("artifacts/sports_discovery")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cache_file = artifact_dir / "sports_list.json"

    raw_sports: list[dict[str, Any]] = []

    # 1. Try Live API if key is present
    if settings.propline_key and force_refresh:
        try:
            r = httpx.get(
                "https://api.prop-line.com/v1/sports",
                headers={"x-api-key": settings.propline_key},
                timeout=8.0,
            )
            if r.status_code == 200:
                raw_sports = r.json()
        except Exception:
            raw_sports = []

    # 2. Try previous discovery cache if not refreshed or failed
    if not raw_sports and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if isinstance(cached_data, dict) and "sports" in cached_data:
                    return cached_data["sports"]
                elif isinstance(cached_data, list):
                    raw_sports = cached_data
        except Exception:
            raw_sports = []

    # 3. Fallback to provider validation raw evidence
    if not raw_sports:
        fallback_art = Path("artifacts/provider_validation/raw/propline/Sport Discovery_20260929_154502.json")
        if fallback_art.exists():
            try:
                with open(fallback_art, "r", encoding="utf-8") as f:
                    raw_sports = json.load(f)
            except Exception:
                raw_sports = []

    # Process and annotate sports
    annotated_sports: list[dict[str, Any]] = []
    for s in raw_sports:
        key = s.get("key", "")
        title = s.get("title", key)
        active = s.get("active", False)
        category = categorize_sport(key)

        # Model eligibility rule
        if key == "soccer_turkey_super_lig":
            model_status = "MODEL_AVAILABLE"
            model_name = "poisson_bivariate_baseline v0.1.0"
        elif category == "Football":
            model_status = "NO_MODEL_YET (INSUFFICIENT_LOCAL_HISTORY)"
            model_name = None
        else:
            model_status = "NO_MODEL_YET"
            model_name = None

        annotated_sports.append({
            "sport_key": key,
            "title": title,
            "category": category,
            "active": active,
            "model_status": model_status,
            "model_name": model_name,
        })

    # Save to artifacts/sports_discovery/sports_list.json
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_sports": len(annotated_sports),
        "sports": annotated_sports,
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return annotated_sports


def fetch_sport_upcoming_events(sport_key: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch upcoming events for a specific sport from PropLine."""
    settings = get_settings()
    if not settings.propline_key:
        return []

    url = f"https://api.prop-line.com/v1/sports/{sport_key}/events"
    try:
        r = httpx.get(
            url,
            headers={"x-api-key": settings.propline_key},
            timeout=8.0,
        )
        if r.status_code == 200:
            events = r.json()
            return events if isinstance(events, list) else []
    except Exception:
        pass

    # Fallback for Süper Lig if API times out
    if sport_key == "soccer_turkey_super_lig":
        fallback_path = Path("artifacts/provider_validation/raw/propline/Upcoming Event Discovery_20260929_154502.json")
        if fallback_path.exists():
            try:
                with open(fallback_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    return []


def check_sport_scores_availability(sport_keys: list[str]) -> dict[str, Any]:
    """Check PropLine /scores availability across sports."""
    settings = get_settings()
    results: dict[str, Any] = {}

    for key in sport_keys:
        status_info = {"status": "UNCHECKED", "event_count": 0, "sample": None}
        if settings.propline_key:
            url = f"https://api.prop-line.com/v1/sports/{key}/scores"
            try:
                r = httpx.get(
                    url,
                    headers={"x-api-key": settings.propline_key},
                    timeout=6.0,
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        status_info["status"] = "AVAILABLE"
                        status_info["event_count"] = len(data)
                        if data:
                            status_info["sample"] = {
                                "id": data[0].get("id"),
                                "home_team": data[0].get("home_team"),
                                "away_team": data[0].get("away_team"),
                                "status": data[0].get("status"),
                                "home_score": data[0].get("home_score"),
                                "away_score": data[0].get("away_score"),
                            }
                elif r.status_code == 404:
                    status_info["status"] = "NOT_FOUND"
                else:
                    status_info["status"] = f"HTTP_{r.status_code}"
            except Exception as e:
                status_info["status"] = f"ERROR_{type(e).__name__}"

        results[key] = status_info

    # Save to artifacts/sports_discovery/scores_availability.json
    artifact_path = Path("artifacts/sports_discovery/scores_availability.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sports_checked": len(results),
        "results": results,
    }
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload
