"""Turkey Football Universe Discovery and Multi-Competition Cataloger (TASK-007)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from config.settings import get_settings


# Official TFF competitions registry
TFF_OFFICIAL_COMPETITIONS = [
    {
        "competition_id": "tr_super_lig",
        "provider": "propline+bzzoiro",
        "sport_key": "soccer_turkey_super_lig",
        "competition_name": "Trendyol Süper Lig",
        "country": "Turkey",
        "competition_type": "LEAGUE_TIER_1",
        "active": True,
        "historical_data_available": True,
        "odds_available": True,
        "model_available": "MODEL_READY",
    },
    {
        "competition_id": "tr_1_lig",
        "provider": "propline",
        "sport_key": "soccer_turkey_super_lig",  # Fed under Turkish soccer provider key
        "competition_name": "Trendyol 1. Lig",
        "country": "Turkey",
        "competition_type": "LEAGUE_TIER_2",
        "active": True,
        "historical_data_available": True,  # Cross-season matchups in bronze
        "odds_available": True,
        "model_available": "MODEL_READY",
    },
    {
        "competition_id": "tr_turkiye_kupasi",
        "provider": "api_football",
        "sport_key": "soccer_turkey_cup",
        "competition_name": "Ziraat Türkiye Kupası",
        "country": "Turkey",
        "competition_type": "NATIONAL_CUP",
        "active": True,
        "historical_data_available": False,
        "odds_available": False,
        "model_available": "INSUFFICIENT_HISTORY",
    },
    {
        "competition_id": "tr_2_lig",
        "provider": "api_football",
        "sport_key": "soccer_turkey_2_lig",
        "competition_name": "TFF 2. Lig (Beyaz / Kırmızı)",
        "country": "Turkey",
        "competition_type": "LEAGUE_TIER_3",
        "active": False,
        "historical_data_available": False,
        "odds_available": False,
        "model_available": "INSUFFICIENT_HISTORY",
    },
    {
        "competition_id": "tr_3_lig",
        "provider": "api_football",
        "sport_key": "soccer_turkey_3_lig",
        "competition_name": "TFF 3. Lig (Grup 1-4)",
        "country": "Turkey",
        "competition_type": "LEAGUE_TIER_4",
        "active": False,
        "historical_data_available": False,
        "odds_available": False,
        "model_available": "NO_RESULT_DATA",
    },
    {
        "competition_id": "tr_kadin_futbol",
        "provider": "api_football",
        "sport_key": "soccer_turkey_women",
        "competition_name": "Turkcell Kadın Futbol Süper Ligi",
        "country": "Turkey",
        "competition_type": "WOMENS_LEAGUE",
        "active": False,
        "historical_data_available": False,
        "odds_available": False,
        "model_available": "NO_MARKET_DATA",
    },
]

# Known clubs playing in 1. Lig
TURKISH_1_LIG_CLUBS = {
    "genclerbirligi", "amedspor", "amed", "erzurumspor", "corum_fk", "corum",
    "kocaelispor", "bandirmaspor", "boluspor", "sakaryaspor", "istanbulspor",
    "ankagucu", "mke_ankaragucu", "umraniyespor", "sanliurfaspor", "adanaspor",
    "pendikspor", "karagumruk", "fatih_karagumruk", "igdir_fk", "eski_sehirspor",
}


def discover_turkey_football_universe() -> list[dict[str, Any]]:
    """Discover all active Turkish football competitions and annotate event availability."""
    settings = get_settings()
    out_dir = Path("artifacts/turkey_football")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "competitions.json"

    # Fetch live upcoming events from PropLine for Turkish football
    upcoming_events = []
    if settings.propline_key:
        try:
            r = httpx.get(
                "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events",
                headers={"x-api-key": settings.propline_key},
                timeout=8.0,
            )
            if r.status_code == 200:
                upcoming_events = r.json() if isinstance(r.json(), list) else []
        except Exception:
            upcoming_events = []

    # Count 1. Lig vs Süper Lig events
    super_lig_count = 0
    tff_1_lig_count = 0

    for ev in upcoming_events:
        h_norm = ev.get("home_team", "").lower().replace(" ", "_")
        a_norm = ev.get("away_team", "").lower().replace(" ", "_")
        is_1_lig = any(c in h_norm or c in a_norm for c in TURKISH_1_LIG_CLUBS)
        if is_1_lig:
            tff_1_lig_count += 1
        else:
            super_lig_count += 1

    catalog: list[dict[str, Any]] = []
    for c in TFF_OFFICIAL_COMPETITIONS:
        c_copy = dict(c)
        if c["competition_id"] == "tr_super_lig":
            c_copy["upcoming_event_count"] = super_lig_count
        elif c["competition_id"] == "tr_1_lig":
            c_copy["upcoming_event_count"] = tff_1_lig_count
        else:
            c_copy["upcoming_event_count"] = 0

        catalog.append(c_copy)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_competitions": len(catalog),
        "total_upcoming_events": len(upcoming_events),
        "competitions": catalog,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return catalog


def classify_fixture_competition(home_team: str, away_team: str) -> str:
    """Classify whether a match belongs to Süper Lig or Turkish 1. Lig / Cup."""
    h = home_team.lower().replace(" ", "_")
    a = away_team.lower().replace(" ", "_")

    if any(c in h or c in a for c in TURKISH_1_LIG_CLUBS):
        return "Trendyol 1. Lig"
    return "Trendyol Süper Lig"
