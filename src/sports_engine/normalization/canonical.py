"""Canonical ID generation and deterministic text normalization."""

import re
import unicodedata
from datetime import datetime

# Turkish character mapping for deterministic transliteration
TURKISH_CHAR_MAP = {
    "ı": "i",
    "İ": "i",
    "ğ": "g",
    "Ğ": "g",
    "ü": "u",
    "Ü": "u",
    "ş": "s",
    "Ş": "s",
    "ö": "o",
    "Ö": "o",
    "ç": "c",
    "Ç": "c",
}

# Common club suffixes / stop words in Turkish football
CLUB_SUFFIXES = [
    r"\bfutbol\s+kulubu\b",
    r"\bspor\s+kulubu\b",
    r"\bjimnastik\s+kulubu\b",
    r"\bkulubu\b",
    r"\bfk\b",
    r"\bsk\b",
    r"\bas\b",
    r"\bk\b",
]


def normalize_entity_name(text: str) -> str:
    """Deterministically normalize an entity name.

    1. Transliterate Turkish characters.
    2. Lowercase and strip unicode diacritics.
    3. Remove punctuation dots (e.g. A.S. -> as).
    4. Remove club suffixes (FK, SK, AS, Kulubu, etc.).
    5. Keep only alphanumeric and spaces.
    6. Consolidate whitespace to single underscore.
    """
    if not text:
        return ""

    # Transliterate Turkish specific characters
    for k, v in TURKISH_CHAR_MAP.items():
        text = text.replace(k, v)

    # Decompose unicode accents
    nfkd_form = unicodedata.normalize("NFKD", text)
    cleaned = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    cleaned = cleaned.lower()

    # Remove dots so A.S. / A.Ş. -> as, S.K. -> sk, F.K. -> fk
    cleaned = cleaned.replace(".", "")

    # Remove known suffixes
    for suffix in CLUB_SUFFIXES:
        cleaned = re.sub(suffix, " ", cleaned)

    # Keep only alphanumeric and spaces
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)

    # Normalize whitespace into underscores
    tokens = [t for t in cleaned.split() if t]
    return "_".join(tokens)


def build_canonical_league_id(country: str, league_name: str) -> str:
    """Generate canonical league ID, e.g. 'turkey_super_lig'."""
    norm_country = normalize_entity_name(country)
    norm_league = normalize_entity_name(league_name)
    return f"{norm_country}_{norm_league}"


def build_canonical_team_id(team_name: str, country: str = "tr") -> str:
    """Generate canonical team ID, e.g. 'galatasaray'."""
    norm_name = normalize_entity_name(team_name)
    return f"{norm_name}"


def build_canonical_player_id(player_name: str, canonical_team_id: str | None = None) -> str:
    """Generate canonical player ID."""
    norm_name = normalize_entity_name(player_name)
    if canonical_team_id:
        return f"{canonical_team_id}_{norm_name}"
    return f"player_{norm_name}"


def build_canonical_fixture_id(
    canonical_league_id: str,
    season: str,
    home_team_id: str,
    away_team_id: str,
    event_time: datetime,
) -> str:
    """Generate deterministic canonical fixture ID.

    Format: {league}_{season}_{date}_{home}_vs_{away}
    Example: tr_super_lig_2024_2025_20241028_galatasaray_vs_besiktas
    """
    date_str = event_time.strftime("%Y%m%d")
    norm_season = season.replace("-", "_").replace("/", "_")
    return f"{canonical_league_id}_{norm_season}_{date_str}_{home_team_id}_vs_{away_team_id}"
