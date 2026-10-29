"""Unit tests for TeamNormalizer."""

import pytest

from team_normalizer import TeamNormalizer


@pytest.fixture
def normalizer():
    return TeamNormalizer()


def test_turkish_character_handling(normalizer):
    """Test that dotless 'ı' and other Turkish characters are correctly preserved into 'i'."""
    tokens_tr = normalizer.normalize_tokens("Kasımpaşa")
    tokens_en = normalizer.normalize_tokens("Kasimpasa")
    assert "kasimpasa" in tokens_tr
    assert tokens_tr == tokens_en

    tokens_bjk = normalizer.normalize_tokens("Beşiktaş")
    tokens_bjk_en = normalizer.normalize_tokens("Besiktas")
    assert "besiktas" in tokens_bjk
    assert tokens_bjk == tokens_bjk_en


def test_manchester_united_alias(normalizer):
    """Test that 'Man. Utd' matches 'Manchester United'."""
    sim = normalizer.compute_similarity("Manchester United", "Man. Utd")
    assert sim >= 0.85


def test_queens_park_rangers_alias(normalizer):
    """Test that 'Queens Park Rangers' matches 'QPR'."""
    sim = normalizer.compute_similarity("Queens Park Rangers", "QPR")
    assert sim >= 0.85


def test_borussia_monchengladbach_alias(normalizer):
    """Test that 'B. M'gladbach' matches 'Borussia Monchengladbach'."""
    sim = normalizer.compute_similarity("Borussia Monchengladbach", "B. M'gladbach")
    assert sim >= 0.85


def test_empty_and_garbage_input(normalizer):
    """Test that empty or non-string inputs return 0 similarity."""
    assert normalizer.compute_similarity("", "Chelsea") == 0.0
    assert normalizer.compute_similarity("   ", "") == 0.0
    assert normalizer.normalize_tokens("") == set()


def test_match_fixture_selection(normalizer):
    """Test match_fixture selects the best candidate fixture from a list."""
    cand_tr = [
        {"id": 1, "home": "Arsenal", "away": "Chelsea"},
        {"id": 2, "home": "Kasımpaşa", "away": "Beşiktaş"},
        {"id": 3, "home": "Man. Utd", "away": "Liverpool"},
    ]

    matched = normalizer.match_fixture("Kasimpasa", "Besiktas", cand_tr)
    assert matched is not None
    assert matched["id"] == 2

    matched_utd = normalizer.match_fixture("Manchester United", "Liverpool", cand_tr)
    assert matched_utd is not None
    assert matched_utd["id"] == 3

    unmatched = normalizer.match_fixture("Real Madrid", "Barcelona", cand_tr)
    assert unmatched is None
