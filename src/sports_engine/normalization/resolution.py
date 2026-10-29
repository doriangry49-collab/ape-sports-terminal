"""Entity resolution engine with exact normalization and RapidFuzz fallback."""

from rapidfuzz import fuzz, process

from sports_engine.domain.schemas import SourceMapping
from sports_engine.normalization.canonical import normalize_entity_name


class EntityResolver:
    """Resolves raw entity names from external sources to canonical IDs.

    Order of precedence:
    1. Exact normalized match against canonical registry or known verified mappings.
    2. RapidFuzz similarity matching against candidate keys (fallback).

    Hard constraints:
    - Fuzzy matches are NEVER marked as verified automatically.
    - Verified status is only assigned to pre-verified mappings or 1.0 exact canonical matches.
    """

    def __init__(self, fuzzy_threshold: float = 75.0):
        self.fuzzy_threshold = fuzzy_threshold
        # canonical_id -> display_name
        self._canonical_entities: dict[str, str] = {}
        # normalized_text -> canonical_id
        self._lookup_to_canonical_id: dict[str, str] = {}
        # (source, source_entity_id) -> SourceMapping
        self._source_mappings: dict[tuple[str, str], SourceMapping] = {}

    def register_canonical_entity(
        self, canonical_id: str, display_name: str, aliases: list[str] | None = None
    ) -> None:
        """Register a canonical entity with standard name and optional aliases."""
        self._canonical_entities[canonical_id] = display_name
        norm_canonical = normalize_entity_name(canonical_id)
        norm_display = normalize_entity_name(display_name)

        self._lookup_to_canonical_id[canonical_id] = canonical_id
        self._lookup_to_canonical_id[norm_canonical] = canonical_id
        self._lookup_to_canonical_id[norm_display] = canonical_id

        if aliases:
            for alias in aliases:
                norm_alias = normalize_entity_name(alias)
                self._lookup_to_canonical_id[norm_alias] = canonical_id

    def add_verified_mapping(self, mapping: SourceMapping) -> None:
        """Add an explicitly verified source mapping."""
        mapping.verified = True
        self._source_mappings[(mapping.source, mapping.source_entity_id)] = mapping

    def resolve(
        self,
        raw_name: str,
        source: str,
        source_entity_id: str,
        entity_type: str = "team",
    ) -> SourceMapping:
        """Resolve a raw name to a canonical ID.

        Step 1: Check existing source mappings.
        Step 2: Check exact normalized string match.
        Step 3: RapidFuzz fallback.
        """
        # Step 1: Pre-existing mapping
        cache_key = (source, source_entity_id)
        if cache_key in self._source_mappings:
            return self._source_mappings[cache_key]

        normalized_query = normalize_entity_name(raw_name)

        # Step 2: Exact normalization match
        if normalized_query in self._lookup_to_canonical_id:
            resolved_id = self._lookup_to_canonical_id[normalized_query]
            mapping = SourceMapping(
                source=source,
                source_entity_id=source_entity_id,
                raw_name=raw_name,
                canonical_id=resolved_id,
                confidence=1.0,
                verified=True,
                entity_type=entity_type,
            )
            self._source_mappings[cache_key] = mapping
            return mapping

        # Step 3: RapidFuzz fallback
        choices = list(self._lookup_to_canonical_id.keys())
        if choices:
            match_result = process.extractOne(
                normalized_query,
                choices,
                scorer=fuzz.token_sort_ratio,
            )
            if match_result:
                best_match, score, _ = match_result
                if score >= self.fuzzy_threshold:
                    resolved_id = self._lookup_to_canonical_id[best_match]
                    confidence = round(score / 100.0, 4)

                    mapping = SourceMapping(
                        source=source,
                        source_entity_id=source_entity_id,
                        raw_name=raw_name,
                        canonical_id=resolved_id,
                        confidence=confidence,
                        verified=False,  # CRITICAL: Never auto-verify fuzzy matches
                        entity_type=entity_type,
                    )
                    self._source_mappings[cache_key] = mapping
                    return mapping

        # Fallback when resolution cannot be made
        return SourceMapping(
            source=source,
            source_entity_id=source_entity_id,
            raw_name=raw_name,
            canonical_id=f"unresolved_{normalized_query}",
            confidence=0.0,
            verified=False,
            entity_type=entity_type,
        )
