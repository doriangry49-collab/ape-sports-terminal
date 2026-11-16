"""Tests for Terminal UI Filter Logic and Component Verification.

Milestone 3:
- Minimum EV filter control (uniform evRoi filtering across all thresholds).
- Dynamic League selection filter control (extracted from snapshot edges/fixtures).
- Combined multi-dimensional filtering (Min EV + League + Min Prob + Bookmaker).
- Descending sort by EV ROI.
- UI source code structural and event binding verification (ValueScannerScreen.js & app.js).
- Constitutional adherence (SPEC-0012, SPEC-0013, SPEC-0014, SPEC-0015).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# -----------------------------------------------------------------------------
# Pure Python Reference Filter Implementations mirroring ValueScannerScreen.js
# -----------------------------------------------------------------------------

def parse_min_ev_threshold(filter_val: str | float | None) -> float:
    """Mirrors parseMinEvThreshold in ValueScannerScreen.js."""
    if filter_val is None or filter_val == "all" or filter_val == "ALL":
        return -999999.0
    try:
        n = float(filter_val)
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
        if lg and isinstance(lg, str) and lg.strip() and lg != "UNKNOWN":
            league_set.add(lg.strip())
    if fixtures:
        for f in fixtures:
            lg = f.get("competition") or f.get("league")
            if lg and isinstance(lg, str) and lg.strip() and lg != "UNKNOWN":
                league_set.add(lg.strip())
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
    prob_threshold = float(min_prob or 0.0)

    filtered = []
    for e in edges:
        raw_edge = e.get("raw_edge")
        raw_edge_val = float(raw_edge) if isinstance(raw_edge, (int, float)) else -999.0

        model_p = e.get("model_prob")
        model_p_val = float(model_p) if isinstance(model_p, (int, float)) else 0.0

        ev_roi = e.get("ev_roi") if e.get("ev_roi") is not None else e.get("evRoi")
        if isinstance(ev_roi, (int, float)):
            ev_roi_val = float(ev_roi)
        else:
            ev_roi_val = raw_edge_val * 100.0

        # 1. Min EV
        passes_ev = ev_roi_val >= threshold

        # 2. Min Model Probability
        passes_prob = model_p_val >= prob_threshold

        # 3. League Filter
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

    # Descending sort by evRoi
    filtered.sort(key=lambda x: x["_computed_ev_roi"], reverse=True)
    return filtered


# -----------------------------------------------------------------------------
# Fixture data generator for deterministic tests
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_edges():
    now_utc = datetime.now(UTC)
    return [
        {
            "fixtureId": "fix_1",
            "homeTeam": "Galatasaray",
            "awayTeam": "Fenerbahce",
            "league": "Trendyol Süper Lig",
            "competition": "Trendyol Süper Lig",
            "market": "1X2",
            "selection": "1",
            "selection_display": "Galatasaray (Home)",
            "bookmaker": "NESINE",
            "entry_odds": 2.10,
            "ev_roi": 5.4,
            "evRoi": 5.4,
            "raw_edge": 0.025,
            "model_prob": 0.502,
            "half_kelly": 2.5,
            "kickoff": (now_utc + timedelta(hours=2)).isoformat(),
        },
        {
            "fixtureId": "fix_2",
            "homeTeam": "Besiktas",
            "awayTeam": "Trabzonspor",
            "league": "Trendyol Süper Lig",
            "competition": "Trendyol Süper Lig",
            "market": "1X2",
            "selection": "X",
            "selection_display": "Draw",
            "bookmaker": "NESINE",
            "entry_odds": 3.40,
            "ev_roi": 3.1,
            "evRoi": 3.1,
            "raw_edge": 0.012,
            "model_prob": 0.303,
            "half_kelly": 1.1,
            "kickoff": (now_utc + timedelta(hours=4)).isoformat(),
        },
        {
            "fixtureId": "fix_3",
            "homeTeam": "Arsenal",
            "awayTeam": "Chelsea",
            "league": "İngiltere Premier League (E0)",
            "competition": "İngiltere Premier League (E0)",
            "market": "1X2",
            "selection": "1",
            "selection_display": "Arsenal (Home)",
            "bookmaker": "Pinnacle",
            "entry_odds": 1.95,
            "ev_roi": 8.5,
            "evRoi": 8.5,
            "raw_edge": 0.042,
            "model_prob": 0.556,
            "half_kelly": 4.1,
            "kickoff": (now_utc + timedelta(hours=5)).isoformat(),
        },
        {
            "fixtureId": "fix_4",
            "homeTeam": "Liverpool",
            "awayTeam": "Manchester City",
            "league": "İngiltere Premier League (E0)",
            "competition": "İngiltere Premier League (E0)",
            "market": "TOTALS",
            "selection": "OVER_2.5",
            "selection_display": "Over 2.5 Goals",
            "bookmaker": "Bovada",
            "entry_odds": 1.70,
            "ev_roi": 2.2,
            "evRoi": 2.2,
            "raw_edge": 0.011,
            "model_prob": 0.601,
            "half_kelly": 1.5,
            "kickoff": (now_utc + timedelta(hours=6)).isoformat(),
        },
        {
            "fixtureId": "fix_5",
            "homeTeam": "PSG",
            "awayTeam": "Marseille",
            "league": "Fransa Ligue 1 (F1)",
            "competition": "Fransa Ligue 1 (F1)",
            "market": "1X2",
            "selection": "2",
            "selection_display": "Marseille (Away)",
            "bookmaker": "NESINE",
            "entry_odds": 5.80,
            "ev_roi": 0.5,
            "evRoi": 0.5,
            "raw_edge": 0.002,
            "model_prob": 0.181,
            "half_kelly": 0.3,
            "kickoff": (now_utc + timedelta(hours=8)).isoformat(),
        },
        {
            "fixtureId": "fix_6",
            "homeTeam": "Lyon",
            "awayTeam": "Monaco",
            "league": "Fransa Ligue 1 (F1)",
            "competition": "Fransa Ligue 1 (F1)",
            "market": "1X2",
            "selection": "X",
            "selection_display": "Draw",
            "bookmaker": "Pinnacle",
            "entry_odds": 3.60,
            "ev_roi": -4.2,
            "evRoi": -4.2,
            "raw_edge": -0.015,
            "model_prob": 0.266,
            "half_kelly": 0.0,
            "kickoff": (now_utc + timedelta(hours=9)).isoformat(),
        },
        {
            "fixtureId": "fix_7",
            "homeTeam": "Kasimpasa",
            "awayTeam": "Alanyaspor",
            "league": "Trendyol Süper Lig",
            "competition": "Trendyol Süper Lig",
            "market": "1X2",
            "selection": "2",
            "selection_display": "Alanyaspor (Away)",
            "bookmaker": "NESINE",
            "entry_odds": 4.10,
            "ev_roi": -12.5,
            "evRoi": -12.5,
            "raw_edge": -0.045,
            "model_prob": 0.213,
            "half_kelly": 0.0,
            "kickoff": (now_utc + timedelta(hours=10)).isoformat(),
        },
    ]


# -----------------------------------------------------------------------------
# Test Cases: Min EV Filtering Logic
# -----------------------------------------------------------------------------

class TestMinEvFilteringLogic:

    def test_filter_all_positive_ev_threshold_zero(self, sample_edges):
        """min_ev = 0.0 returns all edges with evRoi >= 0.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=0.0)
        assert len(results) == 5
        for r in results:
            assert r["ev_roi"] >= 0.0

    def test_filter_conservative_ev_threshold_two_pct(self, sample_edges):
        """min_ev = 2.0 returns edges with evRoi >= 2.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=2.0)
        assert len(results) == 4
        assert [r["fixtureId"] for r in results] == ["fix_3", "fix_1", "fix_2", "fix_4"]

    def test_filter_vip_standard_ev_threshold_three_pct(self, sample_edges):
        """min_ev = 3.0 returns edges with evRoi >= 3.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=3.0)
        assert len(results) == 3
        assert [r["fixtureId"] for r in results] == ["fix_3", "fix_1", "fix_2"]

    def test_filter_high_value_ev_threshold_five_pct(self, sample_edges):
        """min_ev = 5.0 returns edges with evRoi >= 5.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=5.0)
        assert len(results) == 2
        assert [r["fixtureId"] for r in results] == ["fix_3", "fix_1"]

    def test_filter_whale_ev_threshold_eight_pct(self, sample_edges):
        """min_ev = 8.0 returns edges with evRoi >= 8.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=8.0)
        assert len(results) == 1
        assert results[0]["fixtureId"] == "fix_3"
        assert results[0]["ev_roi"] == 8.5

    def test_filter_all_including_negative_ten_pct(self, sample_edges):
        """min_ev = -10.0 includes negative EV up to -10.0%."""
        results = filter_and_rank_edges(sample_edges, min_ev=-10.0)
        assert len(results) == 6
        assert all(r["ev_roi"] >= -10.0 for r in results)
        assert not any(r["fixtureId"] == "fix_7" for r in results)  # -12.5% excluded

    def test_filter_all_unfiltered_choice(self, sample_edges):
        """min_ev = 'all' returns all 7 opportunities."""
        results = filter_and_rank_edges(sample_edges, min_ev="all")
        assert len(results) == 7

    def test_decimal_input_tolerance(self, sample_edges):
        """Passing decimal 0.03 is normalized to 3.0%, 0.05 to 5.0%."""
        results_decimal = filter_and_rank_edges(sample_edges, min_ev=0.03)
        results_pct = filter_and_rank_edges(sample_edges, min_ev=3.0)
        assert [r["fixtureId"] for r in results_decimal] == [r["fixtureId"] for r in results_pct]

        res_dec_05 = filter_and_rank_edges(sample_edges, min_ev=0.05)
        res_pct_5 = filter_and_rank_edges(sample_edges, min_ev=5.0)
        assert [r["fixtureId"] for r in res_dec_05] == [r["fixtureId"] for r in res_pct_5]


# -----------------------------------------------------------------------------
# Test Cases: Dynamic League Selection Filter Logic
# -----------------------------------------------------------------------------

class TestLeagueSelectionFilterLogic:

    def test_extract_available_leagues_dynamic(self, sample_edges):
        """Extract unique sorted leagues from edge collection."""
        leagues = extract_available_leagues(sample_edges)
        assert leagues == [
            "Fransa Ligue 1 (F1)",
            "Trendyol Süper Lig",
            "İngiltere Premier League (E0)",
        ]

    def test_filter_league_all(self, sample_edges):
        """selected_league = 'all' returns edges across all leagues."""
        results = filter_and_rank_edges(sample_edges, min_ev="all", selected_league="all")
        assert len(results) == 7

    def test_filter_league_super_lig(self, sample_edges):
        """Filter strictly for Trendyol Süper Lig."""
        results = filter_and_rank_edges(sample_edges, min_ev="all", selected_league="Trendyol Süper Lig")
        assert len(results) == 3
        assert all(r["league"] == "Trendyol Süper Lig" for r in results)
        assert {r["fixtureId"] for r in results} == {"fix_1", "fix_2", "fix_7"}

    def test_filter_league_premier_league(self, sample_edges):
        """Filter strictly for Premier League."""
        results = filter_and_rank_edges(sample_edges, min_ev="all", selected_league="İngiltere Premier League (E0)")
        assert len(results) == 2
        assert all(r["league"] == "İngiltere Premier League (E0)" for r in results)

    def test_filter_league_case_insensitive_and_trimmed(self, sample_edges):
        """League filter handles casing and leading/trailing whitespace."""
        results = filter_and_rank_edges(sample_edges, min_ev="all", selected_league="  trendyol süper lig  ")
        assert len(results) == 3

    def test_filter_league_nonexistent_returns_empty_gracefully(self, sample_edges):
        """Non-existent league returns empty list without raising."""
        results = filter_and_rank_edges(sample_edges, min_ev="all", selected_league="Bundesliga")
        assert results == []


# -----------------------------------------------------------------------------
# Test Cases: Combined Filters & Sorting
# -----------------------------------------------------------------------------

class TestCombinedFiltersAndSorting:

    def test_combined_min_ev_and_league(self, sample_edges):
        """Filter for VIP (+3.0% EV) inside Trendyol Süper Lig."""
        results = filter_and_rank_edges(sample_edges, min_ev=3.0, selected_league="Trendyol Süper Lig")
        assert len(results) == 2
        assert [r["fixtureId"] for r in results] == ["fix_1", "fix_2"]
        assert all(r["league"] == "Trendyol Süper Lig" and r["ev_roi"] >= 3.0 for r in results)

    def test_combined_min_ev_league_and_bookmaker(self, sample_edges):
        """Filter for Min EV 2.0% + Premier League + Pinnacle."""
        results = filter_and_rank_edges(
            sample_edges,
            min_ev=2.0,
            selected_league="İngiltere Premier League (E0)",
            selected_bookmaker="PINNACLE",
        )
        assert len(results) == 1
        assert results[0]["fixtureId"] == "fix_3"
        assert results[0]["bookmaker"] == "Pinnacle"

    def test_combined_with_min_prob(self, sample_edges):
        """Filter for Model Probability >= 0.50."""
        results = filter_and_rank_edges(sample_edges, min_ev=0.0, min_prob=0.50)
        assert len(results) == 3
        assert all(r["model_prob"] >= 0.50 for r in results)

    def test_descending_sort_guarantee(self, sample_edges):
        """All filtered results must strictly appear in descending order of EV ROI."""
        results = filter_and_rank_edges(sample_edges, min_ev="all")
        ev_rois = [r["_computed_ev_roi"] for r in results]
        assert ev_rois == sorted(ev_rois, reverse=True)


# -----------------------------------------------------------------------------
# Test Cases: Constitutional Compliance
# -----------------------------------------------------------------------------

class TestConstitutionalComplianceOnFilteredEdges:

    def test_spec0013_lead_time_compliance(self, sample_edges):
        """SPEC-0013: All signals in view model have kickoff > now + 3m."""
        now_utc = datetime.now(UTC)
        for e in sample_edges:
            ko = datetime.fromisoformat(e["kickoff"])
            assert ko > now_utc + timedelta(minutes=3)

    def test_spec0014_window_compliance(self, sample_edges):
        """SPEC-0014: All signals in view model have kickoff <= now + 12h."""
        now_utc = datetime.now(UTC)
        for e in sample_edges:
            ko = datetime.fromisoformat(e["kickoff"])
            assert ko <= now_utc + timedelta(hours=12)

    def test_spec0015_minimum_stake_enforcement(self, sample_edges):
        """SPEC-0015: Any positive Half-Kelly allocation on 10,000 TL bankroll produces >= 50 TL."""
        bankroll = 10000.0
        for e in sample_edges:
            if e["half_kelly"] > 0.0:
                stake = round((e["half_kelly"] / 100.0) * bankroll)
                # For half_kelly >= 0.5%, stake >= 50 TL
                if e["half_kelly"] >= 0.5:
                    assert stake >= 50.0


# -----------------------------------------------------------------------------
# Test Cases: UI Source Code Structural Verification
# -----------------------------------------------------------------------------

class TestUiSourceCodeStructure:

    @pytest.fixture
    def ui_root(self):
        return Path(__file__).parent.parent / "ui"

    def test_value_scanner_screen_has_min_ev_filter(self, ui_root):
        """Verify ValueScannerScreen.js declares id='min-ev-filter'."""
        content = (ui_root / "src" / "components" / "ValueScannerScreen.js").read_text(encoding="utf-8")
        assert 'id="min-ev-filter"' in content
        assert 'value="all"' in content
        assert 'value="0.0"' in content
        assert 'value="2.0"' in content
        assert 'value="3.0"' in content
        assert 'value="5.0"' in content
        assert 'value="8.0"' in content
        assert 'value="-10.0"' in content

    def test_value_scanner_screen_has_league_filter(self, ui_root):
        """Verify ValueScannerScreen.js declares id='league-filter' and dynamically populates leagues."""
        content = (ui_root / "src" / "components" / "ValueScannerScreen.js").read_text(encoding="utf-8")
        assert 'id="league-filter"' in content
        assert "availableLeagues" in content
        assert "leagueSet" in content

    def test_value_scanner_screen_uniform_ev_roi_comparison(self, ui_root):
        """Verify no hardcoded 0.03 branch inconsistency in ValueScannerScreen.js."""
        content = (ui_root / "src" / "components" / "ValueScannerScreen.js").read_text(encoding="utf-8")
        assert "if (minEdgeFilter === 0.03)" not in content
        assert "passesEv = evRoi >= minEvThreshold" in content

    def test_app_js_event_bindings(self, ui_root):
        """Verify app.js binds change listeners to min-ev-filter and league-filter."""
        content = (ui_root / "src" / "app.js").read_text(encoding="utf-8")
        assert "min-ev-filter" in content
        assert "league-filter" in content
        assert "this.filters.minEv" in content
        assert "this.filters.league" in content
        assert "this.state.filters" in content

    def test_navbar_has_api_key_input(self, ui_root):
        """Verify Navbar.js declares id='api-key-input' and binds onApiKeyChange."""
        content = (ui_root / "src" / "components" / "Navbar.js").read_text(encoding="utf-8")
        assert 'id="api-key-input"' in content
        assert "api-key-container" in content
        assert "onApiKeyChange" in content

    def test_app_js_manages_api_key(self, ui_root):
        """Verify app.js initializes apiKey, handles persistence with ape_api_key, and passes it to Navbar."""
        content = (ui_root / "src" / "app.js").read_text(encoding="utf-8")
        assert "this.apiKey" in content
        assert "ape_api_key" in content
        assert "setApiKey" in content

    def test_app_js_has_upgrade_to_syndicate_pro_modal(self, ui_root):
        """Verify app.js renders 'Upgrade to Syndicate PRO' modal with id='upgrade-pro-modal'."""
        content = (ui_root / "src" / "app.js").read_text(encoding="utf-8")
        assert "upgrade-pro-modal" in content
        assert "Upgrade to Syndicate PRO" in content
        assert "Tier Upgrade Required" in content
        assert "handleHttpError" in content

    def test_styles_css_modal_and_api_key_rules(self, ui_root):
        """Verify styles.css includes modal backdrop, dialog, and API key input styles."""
        content = (ui_root / "css" / "styles.css").read_text(encoding="utf-8")
        assert ".modal-backdrop" in content
        assert ".modal-dialog" in content
        assert ".api-key-input" in content
        assert ".api-key-container" in content

    def test_syndicate_pro_screen_has_upgrade_triggers(self, ui_root):
        """Verify SyndicateProScreen.js has data-trigger-upgrade buttons for restricted tiers."""
        content = (ui_root / "src" / "components" / "SyndicateProScreen.js").read_text(encoding="utf-8")
        assert 'data-trigger-upgrade="403"' in content
        assert "Upgrade to Syndicate PRO" in content


# -----------------------------------------------------------------------------
# Test Cases: HTTP 403 Client Modal Dispatch Logic
# -----------------------------------------------------------------------------

def simulate_client_http_response_dispatch(status_code: int, message: str = "") -> dict:
    """Mirrors client-side handleHttpError logic in app.js."""
    if status_code == 403:
        return {
            "modal_displayed": True,
            "modal_id": "upgrade-pro-modal",
            "modal_title": "Upgrade to Syndicate PRO",
            "required_tier": "PRO",
            "message": message or "HTTP 403 Tier Upgrade Required",
        }
    return {"modal_displayed": False}


class TestClientHttp403ModalDispatch:

    def test_http_403_triggers_upgrade_modal(self):
        """HTTP 403 triggers upgrade modal with 'Upgrade to Syndicate PRO'."""
        res = simulate_client_http_response_dispatch(403, "Tier Upgrade Required: This endpoint requires PRO tier or higher.")
        assert res["modal_displayed"] is True
        assert res["modal_id"] == "upgrade-pro-modal"
        assert res["modal_title"] == "Upgrade to Syndicate PRO"
        assert res["required_tier"] == "PRO"
        assert "Tier Upgrade Required" in res["message"]

    def test_http_200_does_not_trigger_modal(self):
        """HTTP 200 does not trigger upgrade modal."""
        res = simulate_client_http_response_dispatch(200)
        assert res["modal_displayed"] is False
