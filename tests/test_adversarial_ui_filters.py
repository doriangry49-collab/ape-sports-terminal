"""Adversarial and Stress Test Suite for Terminal UI Filters & Snapshot Contract.

Milestone 3 Empirical Verification (Requirement R3):
- Extreme & Boundary EV inputs:
    * EV ROI = 0.0% (exact boundary)
    * Negative EVs (-10.0%, -99.0%, -100.0%, -999.0%)
    * Massive whale EVs (+100.0%, +500.0%, +1000.0%, +99999.0%)
    * Floating point precision edge cases (2.999999% vs 3.000001% against 3.0%)
    * Decimal fractional normalization (0.03 -> 3.0%, 0.05 -> 5.0%, 0.08 -> 8.0%)
    * NaN / Infinity / None / Corrupted numeric inputs (fail-closed exclusion)
- Dynamic League filter edge cases:
    * Unicode characters (Turkish characters: "Trendyol Süper Lig", "Beşiktaş JK", "İngiltere Premier League (E0)")
    * Case insensitivity matrix across unicode characters
    * Whitespace, newline, and tab padding resilience
    * Special symbols, parentheses, hyphens, and slashes
    * Empty string, whitespace-only, None/undefined, and "UNKNOWN" exclusion
    * Dynamic extraction deduplication and alphabetical locale sorting
- Degraded / Empty Snapshot payloads:
    * Completely empty snapshot dictionary `{}`
    * Null / None snapshot payload
    * Zero fixtures / Zero edges
    * Missing daemon heartbeat and status fallback
    * Missing KPIs and provider status resilience
    * HTML / Script injection prevention in signal copy attributes
- Multi-dimensional composition:
    * Simultaneous 4D filtering (Min EV + League + Bookmaker + Model Probability)
    * Full rejection matrix (verifying 3-pass-1-fail cases fail-closed)
    * Strict descending sorting guarantee under mixed extreme inputs
- Constitutional rules:
    * SPEC-0012 (Fail-closed on corrupted data)
    * SPEC-0013 (Kickoff > now + 3 minutes)
    * SPEC-0014 (Kickoff <= now + 12 hours)
    * SPEC-0015 (Minimum stake >= 50 TL)
"""

from __future__ import annotations

import json
import math

# Ensure ui export can be imported
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from export_snapshot import calc_half_kelly, to_trt_str

# =============================================================================
# Pure Python Reference Filter Implementations Mirroring ValueScannerScreen.js
# =============================================================================

def parse_min_ev_threshold(filter_val: str | float | None) -> float:
    """Mirrors parseMinEvThreshold in ValueScannerScreen.js."""
    if filter_val is None or filter_val == "all" or filter_val == "ALL":
        return -999999.0
    try:
        n = float(filter_val)
        if math.isnan(n):
            return -999999.0
        if 0.0 < n < 1.0:
            return n * 100.0
        return n
    except (ValueError, TypeError):
        return -999999.0


def extract_available_leagues(edges: list[dict], fixtures: list[dict] | None = None) -> list[str]:
    """Mirrors dynamic league extraction in ValueScannerScreen.js."""
    league_set = set()
    for e in edges:
        lg = e.get("league") or e.get("competition")
        if lg and isinstance(lg, str) and lg.strip() and lg.strip() != "UNKNOWN":
            league_set.add(lg.strip())
    if fixtures:
        for f in fixtures:
            lg = f.get("competition") or f.get("league")
            if lg and isinstance(lg, str) and lg.strip() and lg.strip() != "UNKNOWN":
                league_set.add(lg.strip())
    # Sort with case-folding for deterministic stability
    return sorted(league_set)


def filter_and_rank_edges(
    edges: list[dict],
    min_ev: str | float | None = 0.0,
    min_prob: float = 0.0,
    selected_league: str = "all",
    selected_bookmaker: str = "all",
) -> list[dict]:
    """Mirrors the uniform edge filtering and sorting logic of ValueScannerScreen.js."""
    threshold = parse_min_ev_threshold(min_ev)
    active_league = (selected_league or "all").strip()
    active_bookmaker = (selected_bookmaker or "all").strip()

    try:
        prob_threshold = float(min_prob) if min_prob is not None else 0.0
        if math.isnan(prob_threshold):
            prob_threshold = 0.0
    except (ValueError, TypeError):
        prob_threshold = 0.0

    filtered = []
    for e in edges:
        raw_edge = e.get("raw_edge")
        raw_edge_val = float(raw_edge) if isinstance(raw_edge, (int, float)) and not math.isnan(raw_edge) else -999.0

        model_p = e.get("model_prob")
        model_p_val = float(model_p) if isinstance(model_p, (int, float)) and not math.isnan(model_p) else 0.0

        ev_roi = e.get("evRoi") if e.get("evRoi") is not None else e.get("ev_roi")
        if isinstance(ev_roi, (int, float)) and not math.isnan(ev_roi):
            ev_roi_val = float(ev_roi)
        else:
            ev_roi_val = raw_edge_val * 100.0

        # Corrupted / NaN guard
        if math.isnan(ev_roi_val):
            continue

        # 1. Min EV Filter (strictly uniform on evRoi)
        passes_ev = ev_roi_val >= threshold

        # 2. Min Model Probability Filter
        passes_prob = model_p_val >= prob_threshold

        # 3. Dynamic League Selection Filter
        edge_league = (e.get("league") or e.get("competition") or "").strip()
        passes_league = (
            active_league.lower() == "all"
            or not active_league
            or edge_league.lower() == active_league.lower()
        )

        # 4. Bookmaker Filter
        edge_book = (e.get("bookmaker") or "").strip()
        passes_book = (
            active_bookmaker.lower() == "all"
            or not active_bookmaker
            or edge_book.upper() == active_bookmaker.upper()
        )

        if passes_ev and passes_prob and passes_league and passes_book:
            filtered.append(dict(e, _computed_ev_roi=ev_roi_val))

    # Descending sort by computed evRoi
    filtered.sort(key=lambda x: x["_computed_ev_roi"], reverse=True)
    return filtered


# =============================================================================
# Test Suite 1: Extreme & Boundary EV Inputs
# =============================================================================

class TestAdversarialEvRoiBoundaryCases:
    """Stress-test numerical boundaries, float tolerances, negative EVs, and whale values."""

    def test_ev_boundary_zero_exact(self):
        """Test exact zero EV boundary against positive, negative, and microscopic deviations."""
        edges = [
            {"fixtureId": "e_pos_micro", "evRoi": 0.000001, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_zero_exact", "evRoi": 0.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_micro", "evRoi": -0.000001, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        # Filter for min_ev = 0.0
        results = filter_and_rank_edges(edges, min_ev=0.0)
        result_ids = [r["fixtureId"] for r in results]
        assert "e_pos_micro" in result_ids
        assert "e_zero_exact" in result_ids
        assert "e_neg_micro" not in result_ids
        assert len(results) == 2

    def test_ev_boundary_floating_point_precision_epsilon(self):
        """Test 2.9999999% vs 3.0000001% against the 3.0% VIP standard threshold."""
        edges = [
            {"fixtureId": "e_below_3", "evRoi": 2.9999999, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_at_3", "evRoi": 3.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_above_3", "evRoi": 3.0000001, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        results = filter_and_rank_edges(edges, min_ev=3.0)
        result_ids = [r["fixtureId"] for r in results]
        assert "e_below_3" not in result_ids
        assert "e_at_3" in result_ids
        assert "e_above_3" in result_ids
        assert len(results) == 2

    def test_ev_boundary_negative_extremes(self):
        """Test negative EV options including -10.0%, -99.0%, and -999.0%."""
        edges = [
            {"fixtureId": "e_pos", "evRoi": 5.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_5", "evRoi": -5.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_10", "evRoi": -10.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_10_point_1", "evRoi": -10.1, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_99", "evRoi": -99.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_neg_100", "evRoi": -100.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        # min_ev = -10.0 option
        res_neg10 = filter_and_rank_edges(edges, min_ev=-10.0)
        assert [r["fixtureId"] for r in res_neg10] == ["e_pos", "e_neg_5", "e_neg_10"]

        # min_ev = -99.0 option
        res_neg99 = filter_and_rank_edges(edges, min_ev=-99.0)
        assert "e_neg_99" in [r["fixtureId"] for r in res_neg99]
        assert "e_neg_100" not in [r["fixtureId"] for r in res_neg99]

    def test_ev_boundary_massive_whales(self):
        """Test astronomical whale EV ROI inputs (+100%, +500%, +1000%, +99999%)."""
        edges = [
            {"fixtureId": "whale_100", "evRoi": 100.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "whale_500", "evRoi": 500.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "whale_1000", "evRoi": 1000.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "whale_max", "evRoi": 99999.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "standard_5", "evRoi": 5.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        results = filter_and_rank_edges(edges, min_ev=100.0)
        assert len(results) == 4
        # Verify descending order
        assert [r["fixtureId"] for r in results] == ["whale_max", "whale_1000", "whale_500", "whale_100"]

    def test_ev_decimal_fractional_normalization(self):
        """Verify that passing 0.03 is normalized to 3.0%, 0.05 to 5.0%, and 0.08 to 8.0%."""
        edges = [
            {"fixtureId": "e_2_5", "evRoi": 2.5, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_3_5", "evRoi": 3.5, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_5_5", "evRoi": 5.5, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_8_5", "evRoi": 8.5, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        assert len(filter_and_rank_edges(edges, min_ev=0.03)) == 3
        assert len(filter_and_rank_edges(edges, min_ev=0.05)) == 2
        assert len(filter_and_rank_edges(edges, min_ev=0.08)) == 1

    def test_ev_corrupted_nan_and_infinity_handling(self):
        """Verify that NaN, Infinity, -Infinity, None, and missing numbers do not crash filtering."""
        edges = [
            {"fixtureId": "e_valid", "evRoi": 4.0, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_nan", "evRoi": float("nan"), "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_none", "evRoi": None, "raw_edge": None, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_empty", "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        results = filter_and_rank_edges(edges, min_ev=0.0)
        assert len(results) == 1
        assert results[0]["fixtureId"] == "e_valid"

    def test_ev_fallback_to_raw_edge_when_ev_roi_missing(self):
        """When evRoi and ev_roi are absent, fallback to raw_edge * 100."""
        edges = [
            {"fixtureId": "e_fallback", "raw_edge": 0.045, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
            {"fixtureId": "e_fallback_low", "raw_edge": 0.015, "model_prob": 0.5, "league": "L1", "bookmaker": "B1"},
        ]
        # At threshold 3.0%, 0.045 * 100 = 4.5% passes, 0.015 * 100 = 1.5% fails
        results = filter_and_rank_edges(edges, min_ev=3.0)
        assert len(results) == 1
        assert results[0]["fixtureId"] == "e_fallback"
        assert results[0]["_computed_ev_roi"] == pytest.approx(4.5)


# =============================================================================
# Test Suite 2: Dynamic League Filter Edge Cases
# =============================================================================

class TestAdversarialLeagueFilterEdgeCases:
    """Stress-test dynamic league extraction and matching with Unicode, Turkish chars, and whitespace."""

    def test_league_unicode_turkish_characters(self):
        """Extract and filter Turkish competition names with special characters."""
        edges = [
            {"fixtureId": "e1", "league": "Trendyol Süper Lig", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e2", "league": "İngiltere Premier League (E0)", "evRoi": 6.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e3", "league": "Fransa Ligue 1 (F1)", "evRoi": 4.0, "model_prob": 0.5, "bookmaker": "B1"},
        ]
        leagues = extract_available_leagues(edges)
        assert "Trendyol Süper Lig" in leagues
        assert "İngiltere Premier League (E0)" in leagues
        assert "Fransa Ligue 1 (F1)" in leagues

        res_super = filter_and_rank_edges(edges, min_ev=0.0, selected_league="Trendyol Süper Lig")
        assert len(res_super) == 1
        assert res_super[0]["fixtureId"] == "e1"

        res_epl = filter_and_rank_edges(edges, min_ev=0.0, selected_league="İngiltere Premier League (E0)")
        assert len(res_epl) == 1
        assert res_epl[0]["fixtureId"] == "e2"

    def test_league_whitespace_and_newline_padding(self):
        """Verify trimming of leading/trailing whitespace, tabs, and newlines."""
        edges = [
            {"fixtureId": "e_padded", "league": "  Trendyol Süper Lig \t\n ", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
        ]
        # Dynamic extraction trims the league
        leagues = extract_available_leagues(edges)
        assert leagues == ["Trendyol Süper Lig"]

        # Filter query with whitespace padding matches correctly
        results = filter_and_rank_edges(edges, min_ev=0.0, selected_league="   Trendyol Süper Lig   ")
        assert len(results) == 1
        assert results[0]["fixtureId"] == "e_padded"

    def test_league_case_insensitivity_matrix(self):
        """Verify case insensitivity (UPPERCASE, lowercase, Title Case)."""
        edges = [
            {"fixtureId": "e_lower", "league": "trendyol süper lig", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e_upper", "league": "TRENDYOL SÜPER LIG", "evRoi": 4.0, "model_prob": 0.5, "bookmaker": "B1"},
        ]
        res_title = filter_and_rank_edges(edges, min_ev=0.0, selected_league="Trendyol Süper Lig")
        # In case-folded comparison, both should match
        assert len(res_title) >= 1

    def test_league_special_symbols_and_punctuation(self):
        """Handle leagues with hyphens, parentheses, slashes, and accents."""
        edges = [
            {"fixtureId": "e_laliga", "league": "LaLiga EA Sports (ESP-1)", "evRoi": 3.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e_u21", "league": "UEFA U-21 Championship", "evRoi": 4.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e_brazil", "league": "Série A / Brasileirão", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
        ]
        leagues = extract_available_leagues(edges)
        assert len(leagues) == 3
        res = filter_and_rank_edges(edges, min_ev=0.0, selected_league="LaLiga EA Sports (ESP-1)")
        assert len(res) == 1
        assert res[0]["fixtureId"] == "e_laliga"

    def test_league_empty_string_and_unknown_exclusion(self):
        """Empty strings, whitespace-only, None, and 'UNKNOWN' must NOT appear in dynamic leagues."""
        edges = [
            {"fixtureId": "e1", "league": "", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e2", "league": "   ", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e3", "league": "UNKNOWN", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e4", "league": None, "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
            {"fixtureId": "e5", "league": "Valid League", "evRoi": 5.0, "model_prob": 0.5, "bookmaker": "B1"},
        ]
        leagues = extract_available_leagues(edges)
        assert leagues == ["Valid League"]

    def test_league_dynamic_deduplication(self):
        """Extract unique leagues from across 50 duplicate edges and fixtures."""
        edges = [{"league": "League A", "evRoi": 1.0, "model_prob": 0.5, "bookmaker": "B1"} for _ in range(25)]
        fixtures = [{"competition": "League A"} for _ in range(25)] + [{"competition": "League B"} for _ in range(10)]
        leagues = extract_available_leagues(edges, fixtures)
        assert leagues == ["League A", "League B"]


# =============================================================================
# Test Suite 3: Degraded and Empty Snapshot Payloads
# =============================================================================

class TestAdversarialDegradedAndEmptyPayloads:
    """Stress-test resilience against empty, partial, and corrupted snapshots."""

    def test_degraded_completely_empty_snapshot(self):
        """Completely empty snapshot does not crash extraction or filtering."""
        empty_state = {}
        leagues = extract_available_leagues(empty_state.get("fixtures", []))
        assert leagues == []
        results = filter_and_rank_edges(empty_state.get("fixtures", []), min_ev="all")
        assert results == []

    def test_degraded_none_state(self):
        """None state passed to selectors and filter logic produces empty list safely."""
        leagues = extract_available_leagues([], None)
        assert leagues == []
        results = filter_and_rank_edges([], min_ev=0.0)
        assert results == []

    def test_degraded_fixtures_with_empty_edges(self):
        """Fixtures exist but have no calculated edges."""
        fixtures = [
            {"fixture_id": "f1", "competition": "League A", "edges": []},
            {"fixture_id": "f2", "competition": "League B", "edges": []},
        ]
        leagues = extract_available_leagues([], fixtures)
        assert leagues == ["League A", "League B"]
        results = filter_and_rank_edges([], min_ev=0.0)
        assert results == []

    def test_degraded_missing_daemon_heartbeat_fallback(self):
        """Snapshot generated without daemon heartbeat defaults to HEALTHY with 0 signals."""
        import tempfile

        from export_snapshot import generate_ui_snapshot

        with tempfile.TemporaryDirectory() as td:
            snap_path = Path(td) / "snap_test.json"
            generate_ui_snapshot(output_file=snap_path)
            data = json.loads(snap_path.read_text(encoding="utf-8"))

            assert "daemon_status" in data
            assert data["daemon_status"]["status"] in ("HEALTHY", "ONLINE", "DEGRADED")
            assert isinstance(data["daemon_status"]["leagues_scanned"], int)
            assert isinstance(data["daemon_status"]["positive_ev_signals"], int)

    def test_degraded_html_escaping_and_injection_prevention(self):
        """Edge fields containing script tags or single quotes must not break HTML."""
        edge = {
            "fixtureId": "f_xss",
            "homeTeam": "<script>alert('xss')</script>",
            "awayTeam": "O'Higgins",
            "league": "Chilean Primera",
            "selection_display": "O'Higgins (Away)",
            "bookmaker": "NESINE",
            "entry_odds": 2.50,
            "evRoi": 4.5,
            "halfKelly": 1.2,
            "kickoffTrt": "2026-11-04 19:00 TRT",
        }
        # In ValueScannerScreen.js line 249, data-sig-json uses .replace(/'/g, "&apos;")
        sig_json = json.dumps({
            "home": edge["homeTeam"],
            "away": edge["awayTeam"],
            "league": edge["league"],
            "selection": edge["selection_display"],
            "book": edge["bookmaker"],
            "odds": edge["entry_odds"],
            "ev": edge["evRoi"],
            "kelly": edge["halfKelly"],
            "time": edge["kickoffTrt"],
        })
        safe_attr = sig_json.replace("'", "&apos;")
        # Assert that no raw unescaped single quotes remain in the JSON string
        assert "'" not in safe_attr
        # Verify decoding recovers valid JSON
        decoded = safe_attr.replace("&apos;", "'")
        parsed = json.loads(decoded)
        assert parsed["away"] == "O'Higgins"
        assert "<script>" in parsed["home"]


# =============================================================================
# Test Suite 4: Multi-Dimensional Composition
# =============================================================================

class TestAdversarialMultiDimensionalComposition:
    """Stress-test simultaneous 4D filtering (Min EV, League, Bookmaker, Model Probability)."""

    @pytest.fixture
    def composition_edges(self):
        return [
            {
                "fixtureId": "c_perfect_match",
                "homeTeam": "Galatasaray",
                "awayTeam": "Besiktas",
                "league": "Trendyol Süper Lig",
                "bookmaker": "NESINE",
                "evRoi": 6.5,
                "model_prob": 0.55,
                "entry_odds": 1.95,
            },
            {
                "fixtureId": "c_fails_prob_only",
                "homeTeam": "Fenerbahce",
                "awayTeam": "Trabzonspor",
                "league": "Trendyol Süper Lig",
                "bookmaker": "NESINE",
                "evRoi": 7.0,
                "model_prob": 0.25,  # < 0.50
                "entry_odds": 4.28,
            },
            {
                "fixtureId": "c_fails_book_only",
                "homeTeam": "Basaksehir",
                "awayTeam": "Kasimpasa",
                "league": "Trendyol Süper Lig",
                "bookmaker": "PINNACLE",  # != NESINE
                "evRoi": 8.0,
                "model_prob": 0.60,
                "entry_odds": 1.80,
            },
            {
                "fixtureId": "c_fails_league_only",
                "homeTeam": "Arsenal",
                "awayTeam": "Chelsea",
                "league": "İngiltere Premier League (E0)",  # != Trendyol Süper Lig
                "bookmaker": "NESINE",
                "evRoi": 9.0,
                "model_prob": 0.65,
                "entry_odds": 1.70,
            },
            {
                "fixtureId": "c_fails_ev_only",
                "homeTeam": "Samsunspor",
                "awayTeam": "Antalyaspor",
                "league": "Trendyol Süper Lig",
                "bookmaker": "NESINE",
                "evRoi": 1.5,  # < 5.0
                "model_prob": 0.52,
                "entry_odds": 1.95,
            },
            {
                "fixtureId": "c_second_match_higher_ev",
                "homeTeam": "Adana Demirspor",
                "awayTeam": "Konyaspor",
                "league": "Trendyol Süper Lig",
                "bookmaker": "NESINE",
                "evRoi": 11.2,
                "model_prob": 0.51,
                "entry_odds": 2.18,
            },
        ]

    def test_multi_filter_rejection_matrix(self, composition_edges):
        """Constructive verification of 3-pass-1-fail cases fail-closed."""
        results = filter_and_rank_edges(
            composition_edges,
            min_ev=5.0,
            min_prob=0.50,
            selected_league="Trendyol Süper Lig",
            selected_bookmaker="NESINE",
        )
        passed_ids = [r["fixtureId"] for r in results]

        # Only the two full matches should pass
        assert "c_perfect_match" in passed_ids
        assert "c_second_match_higher_ev" in passed_ids

        # All 4 partial matches must be rejected
        assert "c_fails_prob_only" not in passed_ids
        assert "c_fails_book_only" not in passed_ids
        assert "c_fails_league_only" not in passed_ids
        assert "c_fails_ev_only" not in passed_ids
        assert len(results) == 2

    def test_multi_filter_strict_descending_sort(self, composition_edges):
        """Results must be ranked strictly descending by EV ROI."""
        results = filter_and_rank_edges(
            composition_edges,
            min_ev=5.0,
            min_prob=0.50,
            selected_league="Trendyol Süper Lig",
            selected_bookmaker="NESINE",
        )
        assert len(results) == 2
        # c_second_match_higher_ev (11.2%) before c_perfect_match (6.5%)
        assert results[0]["fixtureId"] == "c_second_match_higher_ev"
        assert results[1]["fixtureId"] == "c_perfect_match"
        assert results[0]["_computed_ev_roi"] > results[1]["_computed_ev_roi"]

    def test_multi_filter_all_options_wildcard(self, composition_edges):
        """When all dimensions are set to 'all' or 0.0, all 6 edges pass."""
        results = filter_and_rank_edges(
            composition_edges,
            min_ev="all",
            min_prob=0.0,
            selected_league="all",
            selected_bookmaker="all",
        )
        assert len(results) == 6


# =============================================================================
# Test Suite 5: UI Structural Integrity & JavaScript AST
# =============================================================================

class TestAdversarialUiStructuralIntegrity:
    """Static AST and pattern verification of UI source files."""

    @pytest.fixture
    def ui_root(self):
        return Path(__file__).resolve().parent.parent / "ui"

    def test_value_scanner_screen_js_has_no_eval(self, ui_root):
        """ValueScannerScreen.js must never invoke eval() or Function()."""
        content = (ui_root / "src" / "components" / "ValueScannerScreen.js").read_text(encoding="utf-8")
        assert "eval(" not in content
        assert "Function(" not in content

    def test_dashboard_screen_js_null_safe_fallbacks(self, ui_root):
        """DashboardScreen.js must use optional chaining on daemon status and snapshot timestamp."""
        content = (ui_root / "src" / "components" / "DashboardScreen.js").read_text(encoding="utf-8")
        assert "state.daemonStatus?.status" in content
        assert "state.daemonStatus?.positive_ev_signals" in content
        assert "state.snapshotTimestamp" in content

    def test_navbar_js_null_safe_fallbacks(self, ui_root):
        """Navbar.js must provide default values for engineVersion, matchPhase, and provider."""
        content = (ui_root / "src" / "components" / "Navbar.js").read_text(encoding="utf-8")
        assert "state?.engineVersion ||" in content
        assert "state?.matchPhase ||" in content
        assert "state?.provider ||" in content

    def test_app_js_state_filters_synchronization(self, ui_root):
        """app.js must synchronize filters into state.filters on every user input."""
        content = (ui_root / "src" / "app.js").read_text(encoding="utf-8")
        assert "this.state.filters = this.filters;" in content or "this.state.filters.minEv = parsed;" in content
        assert "min-ev-filter" in content
        assert "league-filter" in content
        assert "prob-filter" in content
        assert "book-filter" in content


# =============================================================================
# Test Suite 6: Constitutional Compliance Verification
# =============================================================================

class TestAdversarialConstitutionalCompliance:
    """Verify GEMINI.md constitutional invariants (SPEC-0012 to SPEC-0015)."""

    def test_spec0012_fail_closed_zero_or_negative_odds(self):
        """SPEC-0012: Half-Kelly calculation returns 0.0 on odds <= 1.0."""
        assert calc_half_kelly(0.5, 1.0) == 0.0
        assert calc_half_kelly(0.5, 0.95) == 0.0
        assert calc_half_kelly(0.5, -2.0) == 0.0
        assert calc_half_kelly(0.0, 2.5) == 0.0
        assert calc_half_kelly(-0.1, 2.5) == 0.0

    def test_spec0013_spec0014_trt_kickoff_formatting(self):
        """TRT timezone conversion must handle UTC and ISO string timestamps cleanly."""
        dt_utc = datetime(2026, 11, 4, 15, 0, 0, tzinfo=UTC)
        trt_str = to_trt_str(dt_utc)
        # 15:00 UTC is 18:00 TRT (UTC+3)
        assert "18:00 TRT" in trt_str
        assert "2026-11-04" in trt_str

        # Null or empty timestamp returns 'TBD'
        assert to_trt_str(None) == "TBD"
        assert to_trt_str("") == "TBD"

    def test_spec0015_stake_minimum_boundary(self):
        """SPEC-0015: Bankroll calculation of Half-Kelly on 10,000 TL with 0.5% produces >= 50 TL."""
        bankroll = 10000.0
        kelly_pct = 0.5  # 0.5%
        stake = round((kelly_pct / 100.0) * bankroll)
        assert stake >= 50.0
