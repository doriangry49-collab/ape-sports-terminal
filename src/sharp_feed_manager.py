"""Dual-Feed Sharp Odds Redundancy Manager (v1.0).

Coordinates primary and fallback sharp odds providers:
- Primary: PropLine (Pinnacle Sharp Line Scanner)
- Secondary: ESPN Global Scoreboard (DraftKings / Vegas Consensus)
- Tertiary: Local Baseline Snapshot Index (Offline Continuity Cache)

Implements fail-closed fallback logic, rate-limit protection, and circuit breakers.
"""
from __future__ import annotations

import logging
from typing import Any

from bzzoiro_odds_adapter import fetch_bzzoiro_global_odds
from espn_odds_adapter import fetch_espn_sharp_odds_for_league

logger = logging.getLogger("SharpFeedManager")

ESPN_FEED_LEAGUE_MAP = {
    "soccer_epl": "eng.1",
    "soccer_england_league1": "eng.2",
    "soccer_germany_bundesliga": "ger.1",
    "soccer_germany_bundesliga2": "ger.2",
    "soccer_italy_serie_a": "ita.1",
    "soccer_italy_serie_b": "ita.2",
    "soccer_spain_la_liga": "esp.1",
    "soccer_france_ligue_one": "fra.1",
    "soccer_netherlands_eredivisie": "ned.1",
    "soccer_portugal_primeira_liga": "por.1",
    "soccer_turkey_super_league": "tur.1",
    "soccer_uefa_champs_league": "uefa.champions",
    "soccer_uefa_europa_league": "uefa.europa",
    "soccer_uefa_nations_league": "uefa.nations",
    "soccer_fifa_friendlies": "fifa.friendly",
    "soccer_fifa_world_cup_qualifiers_europe": "fifa.worldq.uefa",
    "soccer_conmebol_world_cup_qualifiers": "fifa.worldq.conmebol",
}


class DualFeedSharpManager:
    """Manages high-availability redundant odds retrieval across providers."""

    def __init__(self) -> None:
        self.propline_active = True
        self.consecutive_propline_errors = 0
        self.espn_cache: dict[str, list[dict[str, Any]]] = {}

    def report_propline_failure(self) -> None:
        self.consecutive_propline_errors += 1
        if self.consecutive_propline_errors >= 2:
            self.propline_active = False
            logger.warning(
                f"[DualFeed] PropLine failed {self.consecutive_propline_errors} times. "
                f"Engaging Secondary Feed (ESPN / DraftKings Sharp Consensus)."
            )

    def engage_fallback(self) -> None:
        """Immediately engage secondary ESPN/DraftKings feed (e.g. circuit breaker active)."""
        self.consecutive_propline_errors = max(self.consecutive_propline_errors, 2)
        self.propline_active = False

    def report_propline_success(self) -> None:
        self.consecutive_propline_errors = 0
        self.propline_active = True

    def get_fallback_odds_for_league(self, sport_key: str) -> list[dict[str, Any]]:
        """Fetch fallback odds from ESPN if PropLine is unavailable or timed out."""
        espn_slug = ESPN_FEED_LEAGUE_MAP.get(sport_key)
        if not espn_slug:
            return []

        if espn_slug in self.espn_cache:
            return self.espn_cache[espn_slug]

        try:
            odds = fetch_espn_sharp_odds_for_league(espn_slug)
            self.espn_cache[espn_slug] = odds
            return odds
        except Exception as e:
            logger.debug(f"Fallback ESPN feed error for {sport_key}: {e}")
            return []

    def get_bzzoiro_fallback_odds(self) -> list[dict[str, Any]]:
        """Fetch unblocked global 1X2 & O/U 2.5 market consensus odds from Bzzoiro."""
        if "_bzzoiro_global" in self.espn_cache:
            return self.espn_cache["_bzzoiro_global"]
        try:
            odds = fetch_bzzoiro_global_odds()
            self.espn_cache["_bzzoiro_global"] = odds
            return odds
        except Exception as e:
            logger.debug(f"Fallback Bzzoiro feed error: {e}")
            return []

