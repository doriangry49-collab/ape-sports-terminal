"""Deterministic Team Name Normalization & Match Matching Engine.

Provides bidirectional alias lookup, Turkish-specific Unicode diacritic
sanitization (protecting dotless 'ı' against NFKD drop), prefix/suffix stripping,
and token-overlap similarity scoring for cross-bookmaker fixture matching.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ALIASES_PATH = ROOT_DIR / "data" / "team_aliases.json"

TR_CHAR_MAP = str.maketrans("ıİğĞşŞçÇöÖüÜ", "iIgGsScCoOuU")

WOMEN_SQUAD_TOKENS: set[str] = {
    "k",
    "w",
    "kadin",
    "women",
    "femeni",
    "ladies",
}

PROTECTED_SQUAD_TOKENS: set[str] = WOMEN_SQUAD_TOKENS | {
    "b",
    "u19",
    "u20",
    "u21",
    "u23",
    "u18",
    "u17",
    "ii",
    "reserves",
    "reserve",
    "youth",
}


class TeamNormalizer:
    """Normalizes team names and computes robust cross-provider similarity."""

    PROTECTED_TOKENS = PROTECTED_SQUAD_TOKENS

    def __init__(self, aliases_path: Path | None = None) -> None:
        path = aliases_path or DEFAULT_ALIASES_PATH
        self.aliases: dict[str, str] = {}
        self.stopwords: set[str] = set()

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.aliases = data.get("aliases", {})
                self.stopwords = set(data.get("club_prefixes_to_strip", [])) - PROTECTED_SQUAD_TOKENS
            except Exception:
                self.aliases = {}
                self.stopwords = set()

    def normalize_tokens(self, name: str) -> set[str]:
        """Convert team name into standardized semantic tokens while preserving squad/gender markers."""
        if not name or not name.strip():
            return set()

        # Step 1: Pre-translate Turkish special characters before NFKD
        sanitized = name.translate(TR_CHAR_MAP)

        # Step 2: Unicode normalization & ascii fold
        s = unicodedata.normalize("NFKD", sanitized).encode("ascii", "ignore").decode("ascii").lower()

        # Expand leading "b." abbreviation accurately: "B. Münih" -> "bayern munich", others -> "borussia "
        s = re.sub(r"^\s*b\.\s+(?=munic|munih)", "bayern ", s)
        s = re.sub(r"^\s*b\.\s+", "borussia ", s)

        # Normalize common multi-word Turkish country/club phrases before tokenization
        _phrase_map = (
            ("kosta rika", "costa rica"),
            ("faroe adalari", "faroe islands"),
            ("bosna hersek", "bosnia herzegovina"),
            ("kuzey irlanda", "northern ireland"),
            ("guney irlanda", "republic of ireland"),
            ("cek cumhuriyeti", "czech republic"),
            ("yeni zelanda", "new zealand"),
            ("suudi arabistan", "saudi arabia"),
            ("fildisi sahili", "ivory coast"),
            ("guney afrika", "south africa"),
            ("kuzey makedonya", "north macedonia"),
            ("beyaz rusya", "belarus"),
            ("yesil burun adalari", "cape verde"),
            ("birlesik arap emirlikleri", "united arab emirates"),
        )
        for tr_phrase, en_phrase in _phrase_map:
            if tr_phrase in s:
                s = s.replace(tr_phrase, en_phrase)

        s = re.sub(r"[^a-z0-9\s]", " ", s)
        parts = s.split()

        # Step 3: Extract base tokens, keeping protected squad markers ('k', 'w', 'b', 'u19', 'u21', 'ii', 'reserves')
        raw_tokens: set[str] = set()
        for idx, t in enumerate(parts):
            if t in PROTECTED_SQUAD_TOKENS:
                # Single-letter 'b', 'k', 'w' are squad markers when trailing or parenthesized (or standalone)
                if len(t) == 1 and idx == 0 and len(parts) > 1 and "(" not in name and ")" not in name:
                    continue
                raw_tokens.add("women" if t in WOMEN_SQUAD_TOKENS else t)
            elif len(t) >= 2 and t not in self.stopwords:
                raw_tokens.add(t)

        if not raw_tokens:
            raw_tokens = {t for t in parts if t}

        # Step 4: Expand via alias mapping
        expanded: set[str] = set()
        for t in raw_tokens:
            if t in self.aliases and t not in PROTECTED_SQUAD_TOKENS:
                alias_tokens = self.aliases[t].split()
                expanded.update(alias_tokens)
                if t == "inter":
                    expanded.add("inter")
            else:
                expanded.add(t)
        return expanded

    _tokenize = normalize_tokens

    def compute_similarity(self, a: str, b: str) -> float:
        """Compute Jaccard-like token overlap with prefix tolerance and strict squad-marker isolation."""
        ta = self.normalize_tokens(a)
        tb = self.normalize_tokens(b)
        if not ta or not tb:
            return 0.0

        # Strict isolation: Reserve, Youth, or Women's teams must never match senior first teams
        prot_a = ta & PROTECTED_SQUAD_TOKENS
        prot_b = tb & PROTECTED_SQUAD_TOKENS
        if prot_a != prot_b:
            return 0.0

        if ta == tb:
            return 1.0

        if ta.issubset(tb) or tb.issubset(ta):
            smaller = ta - {"internazionale"} if len(ta) <= len(tb) else tb - {"internazionale"}
            larger = tb - {"internazionale"} if len(ta) <= len(tb) else ta - {"internazionale"}
            ambiguous_singletons = {
                "inter", "real", "sporting", "athletic", "atletico", "union",
                "nacional", "independiente", "racing", "dinamo", "dynamo",
            }
            if len(smaller) == 1 and next(iter(smaller)) in ambiguous_singletons and len(larger) >= 2:
                if not (next(iter(smaller)) == "inter" and "milan" in larger):
                    return len(ta & tb) / max(len(ta), len(tb))
            return 1.0

        # Subword prefix/suffix similarity for truncated team names (e.g., 'monchengladbach' vs 'gladbach')
        if len(ta) == 1 or len(tb) == 1 or len(ta & tb) >= 1:
            for x in ta:
                for y in tb:
                    if x != y and min(len(x), len(y)) >= 5 and (
                        x.startswith(y) or y.startswith(x) or x.endswith(y) or y.endswith(x)
                    ):
                        return 0.85

        intersection = len(ta & tb)
        return intersection / max(len(ta), len(tb))

    def match_fixture(
        self,
        home: str,
        away: str,
        candidates: list[dict[str, Any]],
        home_key: str = "home",
        away_key: str = "away",
        threshold: float = 0.65,
    ) -> dict[str, Any] | None:
        """Find the closest candidate fixture matching (home, away)."""
        best_candidate: dict[str, Any] | None = None
        best_score = 0.0

        for cand in candidates:
            cand_home = cand.get(home_key, "")
            cand_away = cand.get(away_key, "")
            sh = self.compute_similarity(home, cand_home)
            sa = self.compute_similarity(away, cand_away)

            if sh >= threshold and sa >= threshold:
                avg_score = (sh + sa) / 2.0
                if avg_score > best_score:
                    best_score = avg_score
                    best_candidate = cand

        return best_candidate
