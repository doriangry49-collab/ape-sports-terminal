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


class TeamNormalizer:
    """Normalizes team names and computes robust cross-provider similarity."""

    def __init__(self, aliases_path: Path | None = None) -> None:
        path = aliases_path or DEFAULT_ALIASES_PATH
        self.aliases: dict[str, str] = {}
        self.stopwords: set[str] = set()

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.aliases = data.get("aliases", {})
                self.stopwords = set(data.get("club_prefixes_to_strip", []))
            except Exception:
                self.aliases = {}
                self.stopwords = set()

    def normalize_tokens(self, name: str) -> set[str]:
        """Convert team name into standardized semantic tokens."""
        if not name or not name.strip():
            return set()

        # Step 1: Pre-translate Turkish special characters before NFKD
        sanitized = name.translate(TR_CHAR_MAP)

        # Step 2: Unicode normalization & ascii fold
        s = unicodedata.normalize("NFKD", sanitized).encode("ascii", "ignore").decode("ascii").lower()
        s = re.sub(r"[^a-z0-9\s]", " ", s)

        # Step 3: Extract base tokens excluding prefixes
        raw_tokens = {t for t in s.split() if len(t) >= 2 and t not in self.stopwords}
        if not raw_tokens:
            raw_tokens = {t for t in s.split() if t}

        # Step 4: Expand via alias mapping
        expanded = set(raw_tokens)
        for t in raw_tokens:
            if t in self.aliases:
                expanded.add(self.aliases[t])
        return expanded

    def compute_similarity(self, a: str, b: str) -> float:
        """Compute Jaccard-like token overlap with prefix tolerance."""
        ta = self.normalize_tokens(a)
        tb = self.normalize_tokens(b)
        if not ta or not tb:
            return 0.0

        if ta == tb or ta.issubset(tb) or tb.issubset(ta):
            return 1.0

        # Prefix similarity for truncated team names (e.g., 'mönchengladbach' vs 'gladbach')
        for x in ta:
            for y in tb:
                if len(x) >= 4 and len(y) >= 4 and (x.startswith(y[:4]) or y.startswith(x[:4])):
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
