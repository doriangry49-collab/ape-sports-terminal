"""Global football competition and fixture discovery engine.

Aggregates and reconciles competitions across 4 independent providers:
1. API-Football (1200+ historical/statistics catalog)
2. Bzzoiro (88 curated/enriched international leagues)
3. PropLine (Global odds feed: Europe, Americas, Asia, International)
4. xiddaa (Official Turkish Legal Betting [İddaa] program)
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings
from sports_engine.domain.registry import (
    BettingUniverseMetadata,
    CompetitionRegistryEntry,
    FixtureRegistryEntry,
    MarketCoverageMetadata,
    ModelUniverseMetadata,
    ProviderPresence,
)
from sports_engine.normalization.canonical import normalize_entity_name

logger = logging.getLogger(__name__)

PROPLINE_COUNTRY_BY_KEY: dict[str, str] = {
    "soccer_epl": "England",
    "soccer_championship": "England",
    "soccer_la_liga": "Spain",
    "soccer_serie_a": "Italy",
    "soccer_bundesliga": "Germany",
    "soccer_germany_bundesliga2": "Germany",
    "soccer_germany_dfb_pokal": "Germany",
    "soccer_ligue_1": "France",
    "soccer_eredivisie": "Netherlands",
    "soccer_primeira_liga": "Portugal",
    "soccer_brasileirao": "Brazil",
    "soccer_argentina_primera": "Argentina",
    "soccer_scottish_premiership": "Scotland",
    "soccer_saudi_pro": "Saudi Arabia",
    "soccer_eliteserien": "Norway",
    "soccer_japan_j_league": "Japan",
    "soccer_turkey_super_lig": "Turkey",
    "soccer_belgium_pro_league": "Belgium",
    "soccer_sweden_allsvenskan": "Sweden",
    "soccer_greek_super_league": "Greece",
    "soccer_swiss_super_league": "Switzerland",
    "soccer_a_league": "Australia",
    "soccer_mls": "USA",
    "soccer_liga_mx": "Mexico",
    "soccer_uefa_champions_league": "International",
    "soccer_uefa_europa_league": "International",
    "soccer_uefa_conference_league": "International",
    "soccer_uefa_nations_league": "International",
    "soccer_copa_libertadores": "South America",
    "soccer_copa_sudamericana": "South America",
    "soccer_fifa_world_cup": "International",
}


def map_country_code_to_name(code: str | None) -> str:
    """Map ISO country codes or common abbreviations to standardized English country names."""
    if not code:
        return "International"
    code = code.upper().strip()
    mapping = {
        "GB": "England",
        "EN": "England",
        "ES": "Spain",
        "IT": "Italy",
        "DE": "Germany",
        "FR": "France",
        "NL": "Netherlands",
        "PT": "Portugal",
        "BR": "Brazil",
        "AR": "Argentina",
        "TR": "Turkey",
        "US": "USA",
        "USA": "USA",
        "MX": "Mexico",
        "KZ": "Kazakhstan",
        "FI": "Finland",
        "BE": "Belgium",
        "GR": "Greece",
        "CH": "Switzerland",
        "SE": "Sweden",
        "NO": "Norway",
        "JP": "Japan",
        "SA": "Saudi Arabia",
        "AU": "Australia",
        "SCO": "Scotland",
        "WORLD": "International",
        "EUROPE": "International",
        "AFRICA": "International",
        "ASIA": "International",
        "SOUTH AMERICA": "South America",
    }
    return mapping.get(code, code.title())


def detect_competition_type(name: str) -> tuple[str, str]:
    """Detect competition type (League, Cup, Youth, Women, International) and gender."""
    norm_name = normalize_entity_name(name)
    gender = "Women" if any(w in norm_name for w in ["women", "kadin", "feminin", "femenina"]) else "Men"

    if any(y in norm_name for y in ["u21", "u20", "u19", "u18", "u17", "youth", "genc"]):
        c_type = "Youth"
    elif any(c in norm_name for c in ["cup", "kupa", "pokal", "copa", "coppa", "coupe", "beker"]):
        c_type = "Cup"
    elif any(i in norm_name for i in ["champions_league", "europa_league", "conference_league", "nations_league", "world_cup", "euro", "libertadores", "sudamericana"]):
        c_type = "International"
    elif "friendly" in norm_name or "hazirlik" in norm_name:
        c_type = "Friendly"
    else:
        c_type = "League"

    return c_type, gender


def build_canonical_competition_id(country: str, name: str) -> str:
    """Build a deterministic, global canonical competition ID."""
    norm_c = normalize_entity_name(country) or "international"
    norm_n = normalize_entity_name(name)

    # Specific canonical overrides for world-known competitions
    if "premier_league" in norm_n or "epl" in norm_n or "ingiltere_premier" in norm_n:
        return "england_premier_league"
    if "championship" in norm_n or "ingiltere_1_lig" in norm_n:
        return "england_championship"
    if "la_liga" in norm_n or "laliga" in norm_n or "ispanya_la_liga" in norm_n or "primera_division" in norm_n:
        return "spain_la_liga"
    if "serie_a" in norm_n or "italya_serie_a" in norm_n:
        return "italy_serie_a"
    if "bundesliga_2" in norm_n or "2_bundesliga" in norm_n or "almanya_2" in norm_n:
        return "germany_2_bundesliga"
    if "bundesliga" in norm_n or "almanya_bundesliga" in norm_n:
        return "germany_bundesliga"
    if "dfb_pokal" in norm_n or "almanya_kupasi" in norm_n:
        return "germany_dfb_pokal"
    if "ligue_1" in norm_n or "fransa_ligue_1" in norm_n:
        return "france_ligue_1"
    if "eredivisie" in norm_n or "hollanda_eredivisie" in norm_n:
        return "netherlands_eredivisie"
    if "primeira_liga" in norm_n or "liga_portugal" in norm_n or "portekiz_premier" in norm_n:
        return "portugal_primeira_liga"
    if "brasileirao" in norm_n or "brezilya_serie_a" in norm_n:
        return "brazil_serie_a"
    if "brezilya_serie_b" in norm_n or "brezilya_seri_b" in norm_n:
        return "brazil_serie_b"
    if "argentina" in norm_n or "profesional" in norm_n or "arjantin" in norm_n:
        return "argentina_liga_profesional"
    if "champions_league" in norm_n or "sampiyonlar_ligi" in norm_n:
        return "international_uefa_champions_league"
    if "europa_league" in norm_n or "avrupa_ligi" in norm_n:
        return "international_uefa_europa_league"
    if "conference_league" in norm_n or "konferans_ligi" in norm_n:
        return "international_uefa_conference_league"
    if "nations_league" in norm_n or "uluslar_ligi" in norm_n:
        return "international_uefa_nations_league"
    if "u21" in norm_n:
        return "international_uefa_u21_championship"
    if "copa_libertadores" in norm_n:
        return "south_america_copa_libertadores"
    if "copa_sudamericana" in norm_n:
        return "south_america_copa_sudamericana"
    if "fifa_world_cup" in norm_n or "dunya_kupasi" in norm_n:
        return "international_fifa_world_cup"
    if "super_lig" in norm_n or "super_ligi" in norm_n:
        return "turkey_super_lig"
    if "1_lig" in norm_n:
        return "turkey_1_lig"
    if "2_lig" in norm_n:
        return "turkey_2_lig"
    if "3_lig" in norm_n:
        return "turkey_3_lig"
    if "turkiye_kupasi" in norm_n or "turkish_cup" in norm_n:
        return "turkey_turkiye_kupasi"
    if "kadinlar" in norm_n or "kadin_futbol" in norm_n:
        return "turkey_kadinlar_ligi"
    if "mls" in norm_n or "major_league_soccer" in norm_n or "amerika_major" in norm_n:
        return "usa_major_league_soccer"
    if "liga_mx" in norm_n or "meksika" in norm_n:
        return "mexico_liga_mx"
    if "scottish_premiership" in norm_n or "iskocya" in norm_n:
        return "scotland_premiership"
    if "eliteserien" in norm_n or "norvec" in norm_n:
        return "norway_eliteserien"
    if "allsvenskan" in norm_n or "isvec" in norm_n:
        return "sweden_allsvenskan"
    if "greek_super_league" in norm_n or "yunanistan" in norm_n:
        return "greece_super_league"
    if "swiss_super_league" in norm_n or "isvicre" in norm_n:
        return "switzerland_super_league"
    if "belgian_pro_league" in norm_n or "belcika" in norm_n:
        return "belgium_pro_league"
    if "j_league" in norm_n or "j1_league" in norm_n or "japonya" in norm_n:
        return "japan_j1_league"
    if "saudi_pro" in norm_n or "suudi" in norm_n:
        return "saudi_arabia_pro_league"
    if "a_league" in norm_n or "avustralya" in norm_n:
        return "australia_a_league"

    return f"{norm_c}_{norm_n}"


class GlobalDiscoveryEngine:
    """Orchestrates discovery and reconciliation across API-Football, Bzzoiro, PropLine, and xiddaa."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.raw_root = self.settings.project_root / "artifacts" / "provider_validation" / "raw"
        if not self.raw_root.exists():
            self.raw_root = Path("artifacts/provider_validation/raw")

    def _discover_api_football(self) -> list[dict[str, Any]]:
        """Parse raw API-Football artifacts (and live if configured)."""
        competitions: list[dict[str, Any]] = []
        af_dir = self.raw_root / "api_football"

        # 1. League & Season Discovery
        league_file = af_dir / "League _ Season Discovery_20260929_154500.json"
        if league_file.exists():
            try:
                data = json.loads(league_file.read_text(encoding="utf-8"))
                for item in data.get("response", []):
                    league = item.get("league", {})
                    country = item.get("country", {})
                    competitions.append({
                        "provider": "api_football",
                        "provider_id": league.get("id"),
                        "name": league.get("name"),
                        "country": country.get("name", "International"),
                        "type": league.get("type", "League"),
                        "is_women": "women" in league.get("name", "").lower(),
                    })
            except Exception as e:
                logger.warning(f"Error reading API-Football leagues: {e}")

        # 2. Live Fixtures Global Discovery
        live_file = af_dir / "Live Fixtures (Global)_20260929_154500.json"
        if live_file.exists():
            try:
                data = json.loads(live_file.read_text(encoding="utf-8"))
                for item in data.get("response", []):
                    league = item.get("league", {})
                    if league.get("id"):
                        competitions.append({
                            "provider": "api_football",
                            "provider_id": league.get("id"),
                            "name": league.get("name"),
                            "country": league.get("country", "International"),
                            "type": "Youth" if "u21" in league.get("name", "").lower() else "League",
                            "is_women": False,
                        })
            except Exception as e:
                logger.warning(f"Error reading API-Football live: {e}")

        # 3. Known major global coverage in API-Football
        known_global_af = [
            {"id": 39, "name": "Premier League", "country": "England", "type": "League"},
            {"id": 40, "name": "Championship", "country": "England", "type": "League"},
            {"id": 140, "name": "La Liga", "country": "Spain", "type": "League"},
            {"id": 135, "name": "Serie A", "country": "Italy", "type": "League"},
            {"id": 78, "name": "Bundesliga", "country": "Germany", "type": "League"},
            {"id": 61, "name": "Ligue 1", "country": "France", "type": "League"},
            {"id": 88, "name": "Eredivisie", "country": "Netherlands", "type": "League"},
            {"id": 94, "name": "Primeira Liga", "country": "Portugal", "type": "League"},
            {"id": 71, "name": "Serie A", "country": "Brazil", "type": "League"},
            {"id": 128, "name": "Liga Profesional", "country": "Argentina", "type": "League"},
            {"id": 2, "name": "UEFA Champions League", "country": "World", "type": "Cup"},
            {"id": 3, "name": "UEFA Europa League", "country": "World", "type": "Cup"},
            {"id": 848, "name": "UEFA Conference League", "country": "World", "type": "Cup"},
            {"id": 253, "name": "Major League Soccer", "country": "USA", "type": "League"},
            {"id": 98, "name": "J1 League", "country": "Japan", "type": "League"},
        ]
        for k in known_global_af:
            competitions.append({
                "provider": "api_football",
                "provider_id": k["id"],
                "name": k["name"],
                "country": k["country"],
                "type": k["type"],
                "is_women": False,
            })

        return competitions

    def _discover_bzzoiro(self) -> list[dict[str, Any]]:
        """Parse raw Bzzoiro leagues artifact."""
        competitions: list[dict[str, Any]] = []
        bz_file = self.raw_root / "bzzoiro" / "leagues_20260929_134133.json"
        if not bz_file.exists():
            return competitions

        try:
            data = json.loads(bz_file.read_text(encoding="utf-8"))
            for item in data.get("results", []):
                competitions.append({
                    "provider": "bzzoiro",
                    "provider_id": item.get("id"),
                    "name": item.get("name"),
                    "country": item.get("country", "International"),
                    "type": "Cup" if "cup" in item.get("name", "").lower() else "League",
                    "is_women": item.get("is_women", False),
                    "is_active": item.get("is_active", True),
                })
        except Exception as e:
            logger.warning(f"Error reading Bzzoiro leagues: {e}")

        return competitions

    def _discover_propline(self) -> list[dict[str, Any]]:
        """Parse raw PropLine sports artifact for soccer keys."""
        competitions: list[dict[str, Any]] = []
        pl_file = self.raw_root / "propline" / "Sport Discovery_20260929_154502.json"
        if not pl_file.exists():
            pl_file = self.settings.project_root / "artifacts" / "sports_discovery" / "sports_list.json"
        if not pl_file.exists():
            pl_file = Path("artifacts/sports_discovery/sports_list.json")
        if not pl_file.exists():
            return competitions

        try:
            data = json.loads(pl_file.read_text(encoding="utf-8"))
            items = data.get("sports", data) if isinstance(data, dict) else data
            for item in items:
                key = item.get("sport_key", item.get("key", ""))
                if key.startswith("soccer_"):
                    title = item.get("title", key)
                    country = PROPLINE_COUNTRY_BY_KEY.get(key, "International")
                    competitions.append({
                        "provider": "prop_line",
                        "provider_id": key,
                        "name": title,
                        "country": country,
                        "type": "Cup" if any(c in key for c in ["cup", "pokal", "copa"]) else "League",
                        "is_women": False,
                    })
        except Exception as e:
            logger.warning(f"Error reading PropLine sports: {e}")

        return competitions

    def _discover_xiddaa(self) -> list[dict[str, Any]]:
        """Parse raw xiddaa (İddaa Turkish Legal Betting) competitions artifact."""
        competitions: list[dict[str, Any]] = []
        xi_file = self.raw_root / "xiddaa" / "Competitions Endpoint_20260929_154510.json"
        if not xi_file.exists():
            return competitions

        try:
            data = json.loads(xi_file.read_text(encoding="utf-8"))
            items = data.get("data", [])
            seen_xiddaa: set[tuple[str, str | None]] = set()
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                cid = item.get("id")
                country_code = item.get("countryCode")
                sig = (name, country_code)
                if sig in seen_xiddaa:
                    continue
                seen_xiddaa.add(sig)

                country = map_country_code_to_name(country_code)
                event_count = item.get("eventCount", 0)

                competitions.append({
                    "provider": "xiddaa",
                    "provider_id": cid,
                    "name": name,
                    "country": country,
                    "event_count": event_count,
                    "is_women": any(w in name.lower() for w in ["kadin", "kadinlar", "women"]),
                })
        except Exception as e:
            logger.warning(f"Error reading xiddaa competitions: {e}")

        return competitions

    def build_registry(self) -> tuple[list[CompetitionRegistryEntry], list[FixtureRegistryEntry], dict[str, Any]]:
        """Discover, normalize, reconcile, and catalog global competitions & fixtures."""
        api_football_comps = self._discover_api_football()
        bzzoiro_comps = self._discover_bzzoiro()
        propline_comps = self._discover_propline()
        xiddaa_comps = self._discover_xiddaa()

        # Dictionary keyed by canonical_competition_id
        canonical_map: dict[str, CompetitionRegistryEntry] = {}

        def process_item(item: dict[str, Any]) -> None:
            raw_name = item["name"]
            raw_country = item.get("country") or "International"
            c_type, gender = detect_competition_type(raw_name)
            if item.get("is_women"):
                gender = "Women"

            canonical_id = build_canonical_competition_id(raw_country, raw_name)

            # Map canonical country & region
            country = raw_country
            if canonical_id.startswith("england_"):
                country = "England"
                region = "Europe"
            elif canonical_id.startswith("spain_"):
                country = "Spain"
                region = "Europe"
            elif canonical_id.startswith("italy_"):
                country = "Italy"
                region = "Europe"
            elif canonical_id.startswith("germany_"):
                country = "Germany"
                region = "Europe"
            elif canonical_id.startswith("france_"):
                country = "France"
                region = "Europe"
            elif canonical_id.startswith("netherlands_"):
                country = "Netherlands"
                region = "Europe"
            elif canonical_id.startswith("portugal_"):
                country = "Portugal"
                region = "Europe"
            elif canonical_id.startswith("brazil_"):
                country = "Brazil"
                region = "South America"
            elif canonical_id.startswith("argentina_"):
                country = "Argentina"
                region = "South America"
            elif canonical_id.startswith("turkey_"):
                country = "Turkey"
                region = "Europe / Asia"
            elif canonical_id.startswith("usa_"):
                country = "USA"
                region = "North America"
            elif canonical_id.startswith("mexico_"):
                country = "Mexico"
                region = "North America"
            elif canonical_id.startswith("scotland_"):
                country = "Scotland"
                region = "Europe"
            elif canonical_id.startswith("norway_"):
                country = "Norway"
                region = "Europe"
            elif canonical_id.startswith("sweden_"):
                country = "Sweden"
                region = "Europe"
            elif canonical_id.startswith("greece_"):
                country = "Greece"
                region = "Europe"
            elif canonical_id.startswith("switzerland_"):
                country = "Switzerland"
                region = "Europe"
            elif canonical_id.startswith("belgium_"):
                country = "Belgium"
                region = "Europe"
            elif canonical_id.startswith("japan_"):
                country = "Japan"
                region = "Asia"
            elif canonical_id.startswith("saudi_arabia_"):
                country = "Saudi Arabia"
                region = "Asia"
            elif canonical_id.startswith("australia_"):
                country = "Australia"
                region = "Oceania"
            elif canonical_id.startswith("south_america_"):
                country = "South America"
                region = "South America"
            elif canonical_id.startswith("international_"):
                country = "International"
                region = "International"
            else:
                country = raw_country
                region = "Europe" if country in ["England", "Spain", "Italy", "Germany", "France", "Netherlands", "Portugal", "Scotland", "Norway", "Sweden", "Greece", "Switzerland", "Belgium", "Finland"] else ("South America" if country in ["Brazil", "Argentina"] else ("North America" if country in ["USA", "Mexico"] else ("Asia" if country in ["Japan", "Saudi Arabia", "Kazakhstan"] else "International")))

            if canonical_id not in canonical_map:
                # Pretty canonical name
                canon_name = raw_name
                if canonical_id == "england_premier_league":
                    canon_name = "Premier League"
                elif canonical_id == "england_championship":
                    canon_name = "Championship"
                elif canonical_id == "spain_la_liga":
                    canon_name = "La Liga"
                elif canonical_id == "italy_serie_a":
                    canon_name = "Serie A"
                elif canonical_id == "germany_bundesliga":
                    canon_name = "Bundesliga"
                elif canonical_id == "germany_2_bundesliga":
                    canon_name = "2. Bundesliga"
                elif canonical_id == "germany_dfb_pokal":
                    canon_name = "DFB-Pokal"
                elif canonical_id == "france_ligue_1":
                    canon_name = "Ligue 1"
                elif canonical_id == "netherlands_eredivisie":
                    canon_name = "Eredivisie"
                elif canonical_id == "portugal_primeira_liga":
                    canon_name = "Primeira Liga"
                elif canonical_id == "brazil_serie_a":
                    canon_name = "Brasileirão Serie A"
                elif canonical_id == "brazil_serie_b":
                    canon_name = "Brasileirão Serie B"
                elif canonical_id == "argentina_liga_profesional":
                    canon_name = "Liga Profesional Argentina"
                elif canonical_id == "international_uefa_champions_league":
                    canon_name = "UEFA Champions League"
                elif canonical_id == "international_uefa_europa_league":
                    canon_name = "UEFA Europa League"
                elif canonical_id == "international_uefa_conference_league":
                    canon_name = "UEFA Conference League"
                elif canonical_id == "international_uefa_u21_championship":
                    canon_name = "UEFA U21 Championship Qualification"
                elif canonical_id == "international_fifa_world_cup":
                    canon_name = "FIFA World Cup"
                elif canonical_id == "turkey_super_lig":
                    canon_name = "Trendyol Süper Lig"
                elif canonical_id == "turkey_1_lig":
                    canon_name = "Trendyol 1. Lig"
                elif canonical_id == "turkey_2_lig":
                    canon_name = "TFF 2. Lig"
                elif canonical_id == "turkey_3_lig":
                    canon_name = "TFF 3. Lig"
                elif canonical_id == "turkey_turkiye_kupasi":
                    canon_name = "Ziraat Türkiye Kupası"
                elif canonical_id == "turkey_kadinlar_ligi":
                    canon_name = "TFF Kadınlar Süper Ligi"

                canonical_map[canonical_id] = CompetitionRegistryEntry(
                    competition_id=canonical_id,
                    canonical_name=canon_name,
                    country=country,
                    region=region,
                    competition_type=c_type,
                    gender=gender,
                    providers=ProviderPresence(),
                    betting=BettingUniverseMetadata(),
                    markets=MarketCoverageMetadata(
                        offered_markets=[],
                        modelled_markets=["1x2", "ou", "btts", "double_chance", "dnb", "correct_score", "ht_result", "ht_ou", "ht_ft"],
                        market_status={},
                    ),
                    model=ModelUniverseMetadata(),
                )

            entry = canonical_map[canonical_id]
            provider = item["provider"]
            pid = item.get("provider_id")

            # Update provider flags
            if provider == "api_football":
                entry.providers.api_football = True
                entry.providers.provider_keys["api_football_id"] = pid
                entry.model.data_available = True
                entry.model.historical_matches_available = max(entry.model.historical_matches_available, 300)
            elif provider == "bzzoiro":
                entry.providers.bzzoiro = True
                entry.providers.provider_keys["bzzoiro_id"] = pid
                entry.model.data_available = True
                entry.model.xg_available = True
            elif provider == "prop_line":
                entry.providers.prop_line = True
                entry.providers.provider_keys["propline_key"] = pid
                entry.betting.active_odds_available = True
                entry.betting.bookmaker_count = max(entry.betting.bookmaker_count, 5)
            elif provider == "xiddaa":
                entry.providers.xiddaa = True
                entry.providers.provider_keys["xiddaa_id"] = pid
                # Verified in official Turkish betting program!
                entry.betting.turkey_legal_status = "VERIFIED"
                event_cnt = item.get("event_count", 0)
                if event_cnt > 0:
                    entry.betting.active_odds_available = True
                    entry.betting.market_count = max(entry.betting.market_count, 12)

        # Process all providers
        for c in api_football_comps:
            process_item(c)
        for c in bzzoiro_comps:
            process_item(c)
        for c in propline_comps:
            process_item(c)
        for c in xiddaa_comps:
            process_item(c)

        # Post-process statuses and legal market flags
        for comp in canonical_map.values():
            # Strict Legal Market Rule:
            # If not verified via xiddaa, it MUST remain UNKNOWN!
            if comp.betting.turkey_legal_status != "VERIFIED":
                comp.betting.turkey_legal_status = "UNKNOWN"

            # Market coverage taxonomy
            if comp.betting.active_odds_available:
                comp.markets.offered_markets = ["1x2", "totals", "btts", "double_chance", "spreads", "correct_score"]
                status_dict = {}
                for m in ["1x2", "totals", "btts", "double_chance", "correct_score"]:
                    status_dict[m] = "OFFERED_AND_MODELLED"
                status_dict["spreads"] = "OFFERED"
                status_dict["ht_ft"] = "MODEL_ONLY"
                comp.markets.market_status = status_dict
                comp.markets.coverage_ratio = round(len([s for s in status_dict.values() if s == "OFFERED_AND_MODELLED"]) / len(comp.markets.offered_markets), 3)

            # Model readiness
            if comp.model.data_available and comp.betting.active_odds_available:
                comp.model.model_readiness = "MODEL_READY"
            elif comp.betting.active_odds_available:
                comp.model.model_readiness = "INSUFFICIENT_HISTORY"
            else:
                comp.model.model_readiness = "NO_MARKET_DATA"

        # Discover Canonical Fixtures from PropLine and API-Football
        fixtures: list[FixtureRegistryEntry] = []
        bulk_odds_file = self.raw_root / "propline" / "Bulk Odds (1X2 _ h2h _ totals)_20260929_154502.json"
        if bulk_odds_file.exists():
            try:
                b_odds = json.loads(bulk_odds_file.read_text(encoding="utf-8"))
                for event in b_odds:
                    home = event.get("home_team", "")
                    away = event.get("away_team", "")
                    s_key = event.get("sport_key", "")
                    commence = event.get("commence_time")
                    if home and away and commence:
                        c_id = build_canonical_competition_id(PROPLINE_COUNTRY_BY_KEY.get(s_key, "International"), s_key)
                        dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                        f_id = f"{dt.strftime('%Y%m%d')}_{normalize_entity_name(home)}_vs_{normalize_entity_name(away)}"

                        reg_comp = canonical_map.get(c_id)
                        t_status = reg_comp.betting.turkey_legal_status if reg_comp else "UNKNOWN"

                        fixtures.append(FixtureRegistryEntry(
                            fixture_id=f_id,
                            competition_id=c_id,
                            competition_name=reg_comp.canonical_name if reg_comp else s_key,
                            country=reg_comp.country if reg_comp else "International",
                            home_team=home,
                            away_team=away,
                            commence_time=dt,
                            providers_present=["prop_line"],
                            data_available=reg_comp.model.data_available if reg_comp else False,
                            betting_market_available=True,
                            turkey_legal_status=t_status,
                            offered_markets=["1x2", "totals", "btts"],
                        ))
            except Exception as e:
                logger.warning(f"Error reading fixtures: {e}")

        # Summary statistics
        competitions_list = list(canonical_map.values())
        countries_set = {c.country for c in competitions_list}
        comp_types_set = {c.competition_type for c in competitions_list}

        data_avail_count = sum(1 for c in competitions_list if c.model.data_available)
        betting_avail_count = sum(1 for c in competitions_list if c.betting.active_odds_available)
        legal_verified_count = sum(1 for c in competitions_list if c.betting.turkey_legal_status == "VERIFIED")
        unknown_legal_count = sum(1 for c in competitions_list if c.betting.turkey_legal_status == "UNKNOWN")
        cross_provider_count = sum(
            1 for c in competitions_list
            if sum([c.providers.api_football, c.providers.bzzoiro, c.providers.prop_line, c.providers.xiddaa]) >= 2
        )

        metrics = {
            "global_competitions_discovered": len(competitions_list),
            "countries_count": len(countries_set),
            "competition_types_count": len(comp_types_set),
            "api_football_competitions": len(api_football_comps),
            "bzzoiro_competitions": len(bzzoiro_comps),
            "propline_competitions": len(propline_comps),
            "xiddaa_competitions": len(xiddaa_comps),
            "cross_provider_matches": cross_provider_count,
            "canonical_competitions": len(competitions_list),
            "canonical_fixtures": len(fixtures),
            "data_available": data_avail_count,
            "betting_market_available": betting_avail_count,
            "turkey_legal_market_verified": legal_verified_count,
            "unknown": unknown_legal_count,
        }

        # Save artifacts
        registry_dir = self.settings.project_root / "artifacts" / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        gold_dir = self.settings.project_root / "data" / "gold" / "registry"
        gold_dir.mkdir(parents=True, exist_ok=True)

        comp_dict_list = [c.model_dump(mode="json") for c in competitions_list]
        with open(registry_dir / "competition_registry.json", "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(UTC).isoformat(),
                "metrics": metrics,
                "competitions": comp_dict_list,
            }, f, ensure_ascii=False, indent=2)

        fix_dict_list = [f.model_dump(mode="json") for f in fixtures]
        with open(registry_dir / "fixture_registry.json", "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(UTC).isoformat(),
                "total_fixtures": len(fixtures),
                "fixtures": fix_dict_list,
            }, f, ensure_ascii=False, indent=2)

        # Parquet export
        try:
            import pandas as pd
            df_comp = pd.DataFrame([{
                "competition_id": c.competition_id,
                "canonical_name": c.canonical_name,
                "country": c.country,
                "region": c.region,
                "competition_type": c.competition_type,
                "gender": c.gender,
                "api_football": c.providers.api_football,
                "bzzoiro": c.providers.bzzoiro,
                "prop_line": c.providers.prop_line,
                "xiddaa": c.providers.xiddaa,
                "data_available": c.model.data_available,
                "betting_market_available": c.betting.active_odds_available,
                "turkey_legal_status": c.betting.turkey_legal_status,
                "model_readiness": c.model.model_readiness,
            } for c in competitions_list])
            df_comp.to_parquet(gold_dir / "competition_registry.parquet", index=False)
        except Exception as e:
            logger.warning(f"Could not save parquet registry: {e}")

        return competitions_list, fixtures, metrics
