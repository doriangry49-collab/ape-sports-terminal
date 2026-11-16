"""Comprehensive automated test suite for the sports-engine Corner Model Pipeline.

Verifies end-to-end corner betting pipeline:
1. Nesine MTID 216 Corner Market Extraction & Closed Line Filtering
2. Negative Binomial Corner Mathematics (kappa=0.14, bounds, complementarity)
3. AdvancedCornerEngine Valuation, Empirical Profiles & Game-State Lead Decay
4. Live Monitor Daemon Integration (Date Parsing, MBS 3 Filtering, Queue Priority)
5. Telegram Formatting, Markdown Sanitization & Interactive Slash Commands
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from advanced_corner_model import (
    DEFAULT_KAPPA,
    LEAGUE_CORNER_BASELINES,
    AdvancedCornerEngine,
)
from live_stale_line_adapter import fetch_nesine_live_bulletin
from sports_engine.models.negative_binomial import (
    DEFAULT_CORNER_KAPPA,
    neg_binomial_corner_cdf,
    neg_binomial_corner_over_prob,
    neg_binomial_corner_pmf,
    neg_binomial_corner_under_prob,
)
from telegram_notifier import (
    escape_markdown,
    format_corner_alert,
    process_user_command,
)

# =====================================================================
# 1. MTID 216 EXTRACTION TESTS
# =====================================================================

class TestMTID216Extraction:
    """Systematically test Nesine MTID 216 corner line extraction, normalization, and filtering."""

    @staticmethod
    def _build_mock_nesine_payload(markets: list[dict[str, Any]]) -> dict[str, Any]:
        """Construct a simulated Nesine CDN response payload with specified markets."""
        return {
            "sg": {
                "EA": [
                    {
                        "TYPE": 1,
                        "C": 90123,
                        "HN": "Galatasaray",
                        "AN": "Fenerbahce",
                        "D": "02.11.2026",
                        "T": "20:00",
                        "EMBS": 1,
                        "MA": markets,
                    }
                ]
            }
        }

    def test_mtid_216_extraction_all_seven_lines(self):
        """Verify that all 7 supported MTID 216 lines (6.5 to 12.5) are correctly extracted with normalized keys."""
        supported_lines = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
        markets = [
            {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": "2.10"}, {"N": 2, "O": "3.20"}, {"N": 3, "O": "2.80"}]},
        ]
        for line in supported_lines:
            markets.append({
                "MTID": 216,
                "SOV": line,
                "OCA": [
                    {"N": 1, "O": "1.85"},
                    {"N": 2, "O": "1.85"},
                ],
            })

        mock_payload = self._build_mock_nesine_payload(markets)

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps(mock_payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            bulletin = fetch_nesine_live_bulletin()

        assert len(bulletin) == 1
        fixture = bulletin[0]
        assert fixture["home"] == "Galatasaray"
        assert fixture["away"] == "Fenerbahce"
        corners = fixture["nesine_corners"]
        assert isinstance(corners, dict)
        assert len(corners) == 7

        for line in supported_lines:
            key = f"{line}"
            assert key in corners, f"Missing expected corner line key: {key}"
            assert corners[key]["under"] == 1.85
            assert corners[key]["over"] == 1.85

    def test_mtid_216_closed_lines_filtered_out(self):
        """Verify that closed or inactive lines (odds <= 1.01) are strictly excluded from nesine_corners."""
        markets = [
            {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": "2.10"}, {"N": 2, "O": "3.20"}, {"N": 3, "O": "2.80"}]},
            # Line 7.5: Active both sides
            {"MTID": 216, "SOV": 7.5, "OCA": [{"N": 1, "O": "2.40"}, {"N": 2, "O": "1.50"}]},
            # Line 8.5: Under is closed (1.01)
            {"MTID": 216, "SOV": 8.5, "OCA": [{"N": 1, "O": "1.01"}, {"N": 2, "O": "2.50"}]},
            # Line 9.5: Over is closed (1.00)
            {"MTID": 216, "SOV": 9.5, "OCA": [{"N": 1, "O": "2.10"}, {"N": 2, "O": "1.00"}]},
            # Line 10.5: Both closed (1.01 and 1.00)
            {"MTID": 216, "SOV": 10.5, "OCA": [{"N": 1, "O": "1.01"}, {"N": 2, "O": "1.00"}]},
            # Line 11.5: Active both sides
            {"MTID": 216, "SOV": 11.5, "OCA": [{"N": 1, "O": "1.35"}, {"N": 2, "O": "2.90"}]},
        ]
        mock_payload = self._build_mock_nesine_payload(markets)

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps(mock_payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            bulletin = fetch_nesine_live_bulletin()

        corners = bulletin[0]["nesine_corners"]
        assert "7.5" in corners
        assert "11.5" in corners
        assert "8.5" not in corners, "Closed Under line 8.5 should be filtered"
        assert "9.5" not in corners, "Closed Over line 9.5 should be filtered"
        assert "10.5" not in corners, "Closed both-sides line 10.5 should be filtered"

    def test_mtid_216_sov_rounding_and_line_filtering(self):
        """Verify that floating point precision jitter is rounded and lines outside 6.5-12.5 are rejected."""
        markets = [
            {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": "2.00"}, {"N": 2, "O": "3.00"}, {"N": 3, "O": "3.00"}]},
            # Line with floating point representation jitter (9.50000000001)
            {"MTID": 216, "SOV": 9.50000000001, "OCA": [{"N": 1, "O": "1.90"}, {"N": 2, "O": "1.80"}]},
            # Line below range (5.5)
            {"MTID": 216, "SOV": 5.5, "OCA": [{"N": 1, "O": "3.50"}, {"N": 2, "O": "1.25"}]},
            # Line above range (13.5)
            {"MTID": 216, "SOV": 13.5, "OCA": [{"N": 1, "O": "1.15"}, {"N": 2, "O": "4.50"}]},
        ]
        mock_payload = self._build_mock_nesine_payload(markets)

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps(mock_payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            bulletin = fetch_nesine_live_bulletin()

        corners = bulletin[0]["nesine_corners"]
        assert "9.5" in corners
        assert "5.5" not in corners, "Line 5.5 should be excluded"
        assert "13.5" not in corners, "Line 13.5 should be excluded"
        assert corners["9.5"]["under"] == 1.90
        assert corners["9.5"]["over"] == 1.80

    def test_mtid_216_missing_or_empty_corners(self):
        """Verify that bulletin fixtures without corner markets have nesine_corners as None."""
        markets = [
            {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": "2.00"}, {"N": 2, "O": "3.00"}, {"N": 3, "O": "3.00"}]},
        ]
        mock_payload = self._build_mock_nesine_payload(markets)

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps(mock_payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            bulletin = fetch_nesine_live_bulletin()

        assert bulletin[0]["nesine_corners"] is None

    def test_mtid_216_malformed_payload_safety(self):
        """Verify that missing OCA arrays, invalid types, or corrupt SOV fields do not raise exceptions."""
        markets = [
            {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": "2.00"}, {"N": 2, "O": "3.00"}, {"N": 3, "O": "3.00"}]},
            {"MTID": 216, "SOV": None, "OCA": []},
            {"MTID": 216, "SOV": "invalid", "OCA": [{"N": "bad", "O": "none"}]},
            {"MTID": 216, "SOV": 8.5, "OCA": None},
        ]
        mock_payload = self._build_mock_nesine_payload(markets)

        class MockResponse:
            status = 200
            def read(self):
                return json.dumps(mock_payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            # Must complete cleanly without crashing
            bulletin = fetch_nesine_live_bulletin()

        assert len(bulletin) == 1
        assert bulletin[0]["nesine_corners"] is None


# =====================================================================
# 2. NEGATIVE BINOMIAL CORNER MATHEMATICS TESTS
# =====================================================================

class TestNegativeBinomialCornerMath:
    """Test dedicated negative binomial corner probability engine with kappa=0.14."""

    def test_corner_nb_default_kappa(self):
        """Verify that DEFAULT_CORNER_KAPPA is set to 0.14."""
        assert DEFAULT_CORNER_KAPPA == 0.14
        assert DEFAULT_KAPPA == 0.14

    def test_corner_nb_non_negativity_and_probability_bounds(self):
        """Verify non-negativity and [0, 1] bounds for PMF, CDF, Over, and Under probabilities."""
        test_mus = [6.5, 8.0, 9.85, 11.2, 13.5]
        test_ks = [0, 1, 5, 8, 10, 15, 25, 40]
        test_lines = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]

        for mu in test_mus:
            for k in test_ks:
                pmf = neg_binomial_corner_pmf(k, mu)
                cdf = neg_binomial_corner_cdf(k, mu)
                assert 0.0 <= pmf <= 1.0, f"PMF out of bounds: {pmf} for mu={mu}, k={k}"
                assert 0.0 <= cdf <= 1.0, f"CDF out of bounds: {cdf} for mu={mu}, k={k}"

            for line in test_lines:
                p_over = neg_binomial_corner_over_prob(line, mu)
                p_under = neg_binomial_corner_under_prob(line, mu)
                assert 0.0 <= p_over <= 1.0, f"Over prob out of bounds: {p_over} for line={line}"
                assert 0.0 <= p_under <= 1.0, f"Under prob out of bounds: {p_under} for line={line}"

    def test_corner_nb_exact_complementarity(self):
        """Verify mathematically exact complementarity: P(Over L) + P(Under L) == 1.0."""
        test_mus = [7.0, 8.5, 9.5, 10.2, 11.5, 13.0]
        test_lines = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]

        for mu in test_mus:
            for line in test_lines:
                p_over = neg_binomial_corner_over_prob(line, mu, kappa=0.14)
                p_under = neg_binomial_corner_under_prob(line, mu, kappa=0.14)
                total = p_over + p_under
                assert math.isclose(total, 1.0, abs_tol=1e-12), (
                    f"Complementarity violated for line={line}, mu={mu}: {p_over} + {p_under} = {total}"
                )

    def test_corner_nb_pmf_cdf_convergence_and_monotonicity(self):
        """Verify CDF monotonicity and convergence of total PMF to 1.0."""
        mu = 9.85
        total_pmf = sum(neg_binomial_corner_pmf(k, mu) for k in range(60))
        assert math.isclose(total_pmf, 1.0, rel_tol=1e-4), f"PMF does not sum to 1.0: {total_pmf}"

        # CDF Monotonicity: CDF(k) <= CDF(k+1)
        prev_cdf = 0.0
        for k in range(30):
            current_cdf = neg_binomial_corner_cdf(k, mu)
            assert current_cdf >= prev_cdf, f"CDF monotonicity violated at k={k}: {current_cdf} < {prev_cdf}"
            prev_cdf = current_cdf

        # Convergence at high k
        assert neg_binomial_corner_cdf(45, mu) > 0.9999

    def test_corner_nb_line_monotonicity(self):
        """Verify that Over probability strictly decreases and Under probability strictly increases with line L."""
        mu = 10.0
        lines = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]
        over_probs = [neg_binomial_corner_over_prob(L, mu) for L in lines]
        under_probs = [neg_binomial_corner_under_prob(L, mu) for L in lines]

        for i in range(len(lines) - 1):
            assert over_probs[i] > over_probs[i + 1], (
                f"Over probability should decrease: line {lines[i]} ({over_probs[i]}) vs {lines[i+1]} ({over_probs[i+1]})"
            )
            assert under_probs[i] < under_probs[i + 1], (
                f"Under probability should increase: line {lines[i]} ({under_probs[i]}) vs {lines[i+1]} ({under_probs[i+1]})"
            )

    def test_corner_nb_boundary_conditions(self):
        """Verify edge-case handling for negative k, zero mu, and extreme counts."""
        assert neg_binomial_corner_pmf(-1, 9.5) == 0.0
        assert neg_binomial_corner_pmf(0, 0.0) == 1.0
        assert neg_binomial_corner_pmf(1, 0.0) == 0.0
        assert neg_binomial_corner_cdf(0, 0.0) == 1.0
        # Extreme count
        assert neg_binomial_corner_pmf(200, 9.5) >= 0.0


# =====================================================================
# 3. ADVANCED CORNER ENGINE VALUATION & LEAD DECAY TESTS
# =====================================================================

class TestAdvancedCornerEngineValuation:
    """Test AdvancedCornerEngine valuation, empirical team profile weighting, and game-state lead decay."""

    @pytest.fixture
    def corner_engine(self):
        engine = AdvancedCornerEngine()
        # Seed test team profiles directly into lookup
        engine.team_lookup["team_heavy_corners"] = {
            "corners_for": 6.8,
            "corners_against": 5.2,
            "matches": 15,
        }
        engine.team_lookup["team_low_corners"] = {
            "corners_for": 3.4,
            "corners_against": 3.8,
            "matches": 12,
        }
        return engine

    def test_estimate_corner_mu_empirical_team_profiles(self, corner_engine):
        """Verify empirical profile weighting blends 50% team empirical data with 50% league baseline."""
        mu, diag = corner_engine.estimate_corner_mu(
            home_team="team_heavy_corners",
            away_team="team_low_corners",
            league_key="turkey_super_lig",
        )
        base_mu = LEAGUE_CORNER_BASELINES["turkey_super_lig"]
        assert diag["base_league_mu"] == base_mu

        # Home expectation = (6.8 / 5.0) * (3.8 / 5.0) * 5.2 = 5.37472
        # Away expectation = (3.4 / 4.8) * (5.2 / 4.8) * 4.65 = 3.5684
        # Combined = 8.943
        # team_adj = 8.943 / 9.85 = ~0.908
        assert diag["team_adj"] != 1.0
        assert 0.80 <= diag["team_adj"] <= 1.20

    def test_estimate_corner_mu_blowout_lead_decay(self, corner_engine):
        """Verify -12% corner decay (gamestate_adj = 0.88, blowout_risk = 0.40) when favorite odds < 1.35."""
        # Heavy home favorite (odds 1.22)
        mu_blowout, diag_blowout = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            league_key="turkey_super_lig",
            odds_1x2=(1.22, 6.50, 12.00),
        )
        assert diag_blowout["blowout_risk"] == 0.40
        assert diag_blowout["gamestate_adj"] == 0.88

        # Heavy away favorite (odds 1.28)
        mu_away_blowout, diag_away_blowout = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            league_key="turkey_super_lig",
            odds_1x2=(11.00, 5.80, 1.28),
        )
        assert diag_away_blowout["blowout_risk"] == 0.40
        assert diag_away_blowout["gamestate_adj"] == 0.88

    def test_estimate_corner_mu_moderate_favorite_decay(self, corner_engine):
        """Verify -6% corner decay (gamestate_adj = 0.94, blowout_risk = 0.25) when favorite odds in [1.35, 1.55)."""
        mu_mod, diag_mod = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            league_key="turkey_super_lig",
            odds_1x2=(1.45, 4.20, 7.50),
        )
        assert diag_mod["blowout_risk"] == 0.25
        assert diag_mod["gamestate_adj"] == 0.94

    def test_estimate_corner_mu_balanced_match_no_decay(self, corner_engine):
        """Verify no decay (gamestate_adj = 1.0, blowout_risk = 0.0) when favorite odds >= 1.55."""
        mu_bal, diag_bal = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            league_key="turkey_super_lig",
            odds_1x2=(2.20, 3.20, 2.90),
        )
        assert diag_bal["blowout_risk"] == 0.0
        assert diag_bal["gamestate_adj"] == 1.0

    def test_estimate_corner_mu_tempo_adjustment(self, corner_engine):
        """Verify goal tempo adjustment scales with Over 2.5 probability."""
        # High tempo (Over 2.5 is heavy favorite)
        _, diag_high_tempo = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            odds_ou25=(1.40, 2.90),  # Over favored
        )
        # Low tempo (Under 2.5 is heavy favorite)
        _, diag_low_tempo = corner_engine.estimate_corner_mu(
            home_team="Unknown Home",
            away_team="Unknown Away",
            odds_ou25=(2.80, 1.42),  # Under favored
        )
        assert diag_high_tempo["tempo_adj"] > 1.0
        assert diag_low_tempo["tempo_adj"] < 1.0
        assert diag_high_tempo["tempo_adj"] > diag_low_tempo["tempo_adj"]

    def test_estimate_corner_mu_range_clamping(self, corner_engine):
        """Verify final estimated mu is strictly bounded within [7.20, 13.50]."""
        # Trigger minimal possible mu
        corner_engine.team_lookup["tiny_h"] = {"corners_for": 1.0, "corners_against": 1.0, "matches": 10}
        corner_engine.team_lookup["tiny_a"] = {"corners_for": 1.0, "corners_against": 1.0, "matches": 10}
        mu_low, _ = corner_engine.estimate_corner_mu(
            home_team="tiny_h",
            away_team="tiny_a",
            odds_1x2=(1.10, 8.00, 20.00),
            odds_ou25=(3.50, 1.25),
        )
        assert mu_low >= 7.20

    def test_evaluate_live_fixture_schema_and_edge_filtering(self, corner_engine):
        """Verify evaluate_live_fixture returns structured signal dicts with all required fields and edge filter."""
        fixture = {
            "home": "Besiktas",
            "away": "Trabzonspor",
            "time_str": "19:00",
            "mbs": 2,
            "nesine_1x2": (2.10, 3.20, 3.10),
            "nesine_ou25": (1.80, 1.95),
            "nesine_corners": {
                "6.5": {"under": 5.50, "over": 1.18},
                "7.5": {"under": 3.40, "over": 1.35},
                "8.5": {"under": 2.20, "over": 1.55},
                "9.5": {"under": 1.85, "over": 1.85},
                "10.5": {"under": 2.10, "over": 1.60},
                "11.5": {"under": 1.38, "over": 3.20},
                "12.5": {"under": 1.15, "over": 5.80},
            },
        }

        signals = corner_engine.evaluate_live_fixture(fixture, min_edge_pct=4.0)
        assert isinstance(signals, list)

        # Ensure all signals meet min_edge_pct and conform to contract
        required_fields = {
            "match", "home", "away", "time", "mbs", "market", "selection",
            "outcome", "book_odd", "soft_odds", "fair_odd", "fair_odds",
            "prob", "edge_pct", "tier", "expected_corners", "distribution",
            "line", "side", "is_corner", "diagnostics",
        }

        for s in signals:
            assert s["edge_pct"] >= 4.0, f"Signal below min_edge_pct: {s['edge_pct']}"
            assert s["is_corner"] is True
            assert s["distribution"] == "NegativeBinomial"
            assert s["match"] == "Besiktas vs Trabzonspor"
            assert s["mbs"] == 2
            assert s["side"] in ("ÜST", "ALT")
            missing = required_fields - set(s.keys())
            assert not missing, f"Signal missing required contract fields: {missing}"

    def test_evaluate_live_fixture_tier_assignment(self, corner_engine):
        """Verify that signals with prob >= 0.68 are assigned TIER_1_SHIELD, else TIER_2_VALUE."""
        fixture = {
            "home": "Team A",
            "away": "Team B",
            "time_str": "20:00",
            "nesine_corners": {
                # Line 9.5 has prob ~ 0.52 (< 0.68), producing TIER_2_VALUE
                "9.5": {"under": 2.50, "over": 1.50},
                # Line 12.5 has under prob ~ 0.81 (>= 0.68), producing TIER_1_SHIELD
                "12.5": {"under": 2.00, "over": 1.80},
            },
        }
        signals = corner_engine.evaluate_live_fixture(fixture, min_edge_pct=0.0)
        assert len(signals) >= 2
        tiers = {s["tier"] for s in signals}
        assert "TIER_1_SHIELD" in tiers
        assert "TIER_2_VALUE" in tiers

        for s in signals:
            if s["prob"] >= 0.68:
                assert s["tier"] == "TIER_1_SHIELD"
            else:
                assert s["tier"] == "TIER_2_VALUE"

    def test_evaluate_live_fixture_empty_corners(self, corner_engine):
        """Verify evaluate_live_fixture returns empty list when nesine_corners is empty or None."""
        assert corner_engine.evaluate_live_fixture({"nesine_corners": None}) == []
        assert corner_engine.evaluate_live_fixture({"nesine_corners": {}}) == []
        assert corner_engine.evaluate_live_fixture({}) == []

    def test_price_lines_seven_supported_lines_bounds_and_monotonicity(self, corner_engine):
        """Verify price_lines evaluates all 7 supported lines (6.5 to 12.5) with strictly monotonic probabilities."""
        res = corner_engine.price_lines(mu=9.5, kappa=0.14)
        lines_dict = res["lines"]
        expected_lines = ["6.5", "7.5", "8.5", "9.5", "10.5", "11.5", "12.5"]
        assert list(lines_dict.keys()) == expected_lines, f"Expected 7 lines, got {list(lines_dict.keys())}"

        # Probability bounds and Over/Under complementarity for extreme lines
        p_under_prev = -1.0
        p_over_prev = 2.0
        for l_key in expected_lines:
            entry = lines_dict[l_key]
            p_u = entry["p_under"]
            p_o = entry["p_over"]
            assert 0.0 < p_u < 1.0
            assert 0.0 < p_o < 1.0
            assert abs(p_u + p_o - 1.0) < 1e-4, f"Complementarity violated at line {l_key}: {p_u + p_o}"
            # Strict monotonicity across ascending lines
            assert p_u > p_under_prev, f"Under prob must strictly increase with line: {p_u} <= {p_under_prev}"
            assert p_o < p_over_prev, f"Over prob must strictly decrease with line: {p_o} >= {p_over_prev}"
            p_under_prev = p_u
            p_over_prev = p_o

        # Line 6.5 (Over favored) and Line 12.5 (Under favored) fair odds
        assert lines_dict["6.5"]["fair_over"] < lines_dict["6.5"]["fair_under"]
        assert lines_dict["12.5"]["fair_under"] < lines_dict["12.5"]["fair_over"]

    def test_evaluate_live_fixture_line_6_5_extreme_valuation(self, corner_engine):
        """Verify evaluate_live_fixture detects +EV opportunities on extreme low line 6.5."""
        fixture = {
            "home": "High Corner Team",
            "away": "High Corner Away",
            "time_str": "20:00",
            "nesine_corners": {
                # Huge value on Over 6.5: book offers 1.45 when fair is ~ 1.20
                "6.5": {"under": 4.50, "over": 1.45},
            },
        }
        signals = corner_engine.evaluate_live_fixture(fixture, min_edge_pct=4.0)
        assert len(signals) >= 1
        s65 = next((s for s in signals if str(s["line"]) == "6.5" and s["side"] == "ÜST"), None)
        assert s65 is not None, "Signal on line 6.5 ÜST must be produced"
        assert s65["market"] == "Korner 6.5"
        assert s65["side"] == "ÜST"
        assert s65["book_odd"] == 1.45
        assert s65["edge_pct"] >= 4.0
        assert s65["is_corner"] is True

    def test_evaluate_live_fixture_line_12_5_extreme_valuation(self, corner_engine):
        """Verify evaluate_live_fixture detects +EV opportunities on extreme high line 12.5 with TIER_1_SHIELD."""
        fixture = {
            "home": "Low Corner Team",
            "away": "Low Corner Away",
            "time_str": "21:00",
            "nesine_corners": {
                # Huge value on Under 12.5: book offers 1.60 when fair is ~ 1.35 (prob ~ 0.74 >= 0.68)
                "12.5": {"under": 1.60, "over": 3.00},
            },
        }
        signals = corner_engine.evaluate_live_fixture(fixture, min_edge_pct=4.0)
        assert len(signals) >= 1
        s125 = next((s for s in signals if str(s["line"]) == "12.5" and s["side"] == "ALT"), None)
        assert s125 is not None, "Signal on line 12.5 ALT must be produced"
        assert s125["market"] == "Korner 12.5"
        assert s125["side"] == "ALT"
        assert s125["book_odd"] == 1.60
        assert s125["prob"] >= 0.68, "Under 12.5 should exceed 68% probability threshold"
        assert s125["tier"] == "TIER_1_SHIELD"

    def test_advanced_corner_model_neg_binomial_boundary_guards(self):
        """Verify advanced_corner_model neg_binomial_pmf and cdf safely handle negative k and zero mu."""
        from advanced_corner_model import neg_binomial_cdf as adv_cdf
        from advanced_corner_model import neg_binomial_pmf as adv_pmf
        assert adv_pmf(-1, 9.5) == 0.0
        assert adv_pmf(-5, 9.5) == 0.0
        assert adv_cdf(-1, 9.5) == 0.0
        assert adv_cdf(-5, 9.5) == 0.0
        assert adv_pmf(0, 0.0) == 1.0
        assert adv_pmf(1, 0.0) == 0.0


# =====================================================================
# 4. LIVE MONITOR DAEMON CORNER INTEGRATION TESTS
# =====================================================================

class TestLiveMonitorDaemonCornerIntegration:
    """Test date parsing resilience, MBS 3 corner threshold relaxation, and queue prioritization."""

    def test_date_parsing_standard_and_iso_formats(self):
        """Verify production parse_match_kickoff parses European (%d.%m.%Y) and ISO (%Y-%m-%d) formats."""
        from live_monitor_daemon import TRT_TZ, parse_match_kickoff

        now_trt = datetime.now(TRT_TZ)
        future_match = now_trt + timedelta(hours=3)

        d_euro = future_match.strftime("%d.%m.%Y")
        d_iso = future_match.strftime("%Y-%m-%d")
        t_str = future_match.strftime("%H:%M")

        test_cases = [
            (d_euro, t_str, "Standard Euro format"),
            (d_iso, t_str, "ISO YYYY-MM-DD format"),
            (d_iso, f"T{t_str}", "ISO YYYY-MM-DDTHH:MM format"),
        ]

        for d_in, t_in, label in test_cases:
            match_dt, kickoff_iso = parse_match_kickoff(d_in, t_in, now_trt=now_trt)
            assert match_dt is not None, f"Production parse_match_kickoff failed for {label}: '{d_in} {t_in}'"
            assert kickoff_iso is not None
            assert kickoff_iso.endswith("Z"), f"kickoff_iso must be formatted in UTC ending in Z: {kickoff_iso}"
            assert match_dt > now_trt + timedelta(minutes=3), f"Match incorrectly flagged as started: {label}"

    def test_kickoff_validation_fail_closed_spec0013(self):
        """Verify SPEC-0013: production parse_match_kickoff returns (None, None) for <= 3m or past fixtures."""
        from live_monitor_daemon import TRT_TZ, parse_match_kickoff

        now_trt = datetime.now(TRT_TZ)

        # Match in past
        past_match = now_trt - timedelta(minutes=15)
        dt_p, iso_p = parse_match_kickoff(past_match.strftime("%d.%m.%Y"), past_match.strftime("%H:%M"), now_trt=now_trt)
        assert dt_p is None and iso_p is None, "Past match must return (None, None) fail-closed"

        # Match starting in 2 minutes (too close to kickoff)
        soon_match = now_trt + timedelta(minutes=2)
        dt_s, iso_s = parse_match_kickoff(soon_match.strftime("%d.%m.%Y"), soon_match.strftime("%H:%M"), now_trt=now_trt)
        assert dt_s is None and iso_s is None, "Match within 2 minutes must return (None, None)"

        # Boundary match starting in exactly 3 minutes
        bnd_match = now_trt + timedelta(minutes=3)
        dt_b, iso_b = parse_match_kickoff(bnd_match.strftime("%d.%m.%Y"), bnd_match.strftime("%H:%M"), now_trt=now_trt)
        assert dt_b is None and iso_b is None, "Match at boundary (<= 3 min) must return (None, None)"

        # Match starting in 4 minutes (> 3 min cutoff) -> MUST PASS
        val_match = now_trt + timedelta(minutes=4)
        dt_v, iso_v = parse_match_kickoff(val_match.strftime("%d.%m.%Y"), val_match.strftime("%H:%M"), now_trt=now_trt)
        assert dt_v is not None and iso_v is not None, "Match in 4 minutes must pass parse_match_kickoff"

        # Missing inputs -> fail-closed
        assert parse_match_kickoff(None, "20:00", now_trt=now_trt) == (None, None)
        assert parse_match_kickoff("02.11.2026", None, now_trt=now_trt) == (None, None)
        assert parse_match_kickoff("bad_date", "bad_time", now_trt=now_trt) == (None, None)

    def test_mbs3_corner_filtering_vs_non_corner(self):
        """Verify production filter_mbs_signals allows corner edges >= 4.0% while requiring >= 15.0% for non-corners."""
        from live_monitor_daemon import filter_mbs_signals

        test_signals = [
            # 1. Corner with MBS 3 and 7.5% edge -> MUST PASS (hurdle is 4.0%)
            {"id": "c1", "market": "Korner 9.5", "mbs": 3, "edge_pct": 7.5, "is_corner": True},
            # 2. Non-corner with MBS 3 and 7.5% edge -> MUST BE FILTERED (hurdle is 15.0%)
            {"id": "nc1", "market": "1X2", "mbs": 3, "edge_pct": 7.5, "is_corner": False},
            # 3. Non-corner with MBS 3 and 16.2% edge -> MUST PASS (>= 15.0%)
            {"id": "nc2", "market": "OU 2.5", "mbs": 3, "edge_pct": 16.2, "is_corner": False},
            # 4. Corner with MBS 3 and 3.2% edge -> MUST BE FILTERED (< 4.0%)
            {"id": "c2", "market": "Korner 10.5", "mbs": 3, "edge_pct": 3.2, "is_corner": True},
            # 5. Non-corner with MBS 1 and 5.0% edge -> MUST PASS (MBS <= 2)
            {"id": "nc3", "market": "1X2", "mbs": 1, "edge_pct": 5.0, "is_corner": False},
            # 6. Corner with MBS 2 and 4.5% edge -> MUST PASS (MBS <= 2)
            {"id": "c3", "market": "Korner 8.5", "mbs": 2, "edge_pct": 4.5, "is_corner": True},
        ]

        passed = filter_mbs_signals(test_signals)
        passed_ids = [s["id"] for s in passed]

        assert "c1" in passed_ids, "Corner MBS 3 with 7.5% edge should pass"
        assert "nc1" not in passed_ids, "Non-corner MBS 3 with 7.5% edge should be filtered out"
        assert "nc2" in passed_ids, "Non-corner MBS 3 with 16.2% edge should pass"
        assert "c2" not in passed_ids, "Corner MBS 3 with 3.2% edge should be filtered out"
        assert "nc3" in passed_ids, "MBS 1 non-corner should pass"
        assert "c3" in passed_ids, "MBS 2 corner should pass"

    def test_dispatch_queue_priority_corners_first(self):
        """Verify production prioritize_dispatch_queue places corners at the front of the queue."""
        from live_monitor_daemon import prioritize_dispatch_queue

        new_alerts = [
            {"id": "nc_high", "market": "1X2", "edge_pct": 24.5, "is_corner": False},
            {"id": "c_val1", "market": "Korner 9.5", "edge_pct": 8.5, "is_corner": True},
            {"id": "nc_mid", "market": "OU 2.5", "edge_pct": 18.0, "is_corner": False},
            {"id": "c_val2", "market": "Korner 10.5", "edge_pct": 6.2, "is_corner": True},
            {"id": "nc_low", "market": "HT/FT", "edge_pct": 15.5, "is_corner": False},
        ]

        dispatch_alerts = prioritize_dispatch_queue(new_alerts)

        # Top 3 alerts dispatched
        dispatched_top3 = dispatch_alerts[:3]
        dispatched_ids = [s["id"] for s in dispatched_top3]

        assert dispatched_ids[0] == "c_val1", "First alert must be corner"
        assert dispatched_ids[1] == "c_val2", "Second alert must be corner"
        assert dispatched_ids[2] == "nc_high", "Third alert must be top non-corner"
        assert len([s for s in dispatched_top3 if s["is_corner"]]) == 2

    def test_scan_quant_engine_signals_kickoff_filtering(self, tmp_path, monkeypatch):
        """Integration test verifying scan_quant_engine_signals executes production kickoff parsing and drops past fixtures."""
        import live_monitor_daemon
        from live_monitor_daemon import TRT_TZ, scan_quant_engine_signals

        monkeypatch.setattr(live_monitor_daemon, "NESINE_TIMESERIES_DB", tmp_path / "nesine_odds_timeseries.db")
        now_trt = datetime.now(TRT_TZ)
        future_dt = now_trt + timedelta(hours=2)
        past_dt = now_trt - timedelta(hours=2)

        mock_bulletin = [
            {
                "home": "Upcoming Team",
                "away": "Upcoming Away",
                "date_str": future_dt.strftime("%Y-%m-%d"),
                "time_str": future_dt.strftime("%H:%M"),
                "nesine_1x2": (1.80, 3.40, 4.00),
                "mbs": 1,
            },
            {
                "home": "Past Team",
                "away": "Past Away",
                "date_str": past_dt.strftime("%d.%m.%Y"),
                "time_str": past_dt.strftime("%H:%M"),
                "nesine_1x2": (1.80, 3.40, 4.00),
                "mbs": 1,
            },
        ]
        monkeypatch.setattr(live_monitor_daemon, "fetch_nesine_live_bulletin", lambda: mock_bulletin)

        class MockTeamStrengthEngine:
            def load_or_train(self):
                pass
            def evaluate_live_fixture(self, fixture, min_edge_pct=0.0):
                return [{
                    "market": "1X2",
                    "selection": "1",
                    "outcome": "MS 1",
                    "soft_odds": 2.0,
                    "fair_odds": 1.5,
                    "edge_pct": 10.0,
                    "prob": 0.6,
                    "mbs": 1,
                    "is_corner": False,
                }]

        monkeypatch.setattr(live_monitor_daemon, "TeamStrengthEngine", MockTeamStrengthEngine)
        monkeypatch.setattr(live_monitor_daemon, "AdvancedCornerEngine", lambda: None)

        signals = scan_quant_engine_signals(min_edge_pct=4.0)
        homes = [s["home"] for s in signals]
        assert "Upcoming Team" in homes, "Upcoming fixture with ISO date must pass scan"
        assert "Past Team" not in homes, "Past fixture must be filtered out per SPEC-0013"

    def test_run_single_scan_cycle_corner_alert_flow(self, tmp_path, monkeypatch):
        """End-to-end integration test of run_single_scan_cycle dispatching corner alerts to Telegram."""
        import live_monitor_daemon
        from live_monitor_daemon import run_single_scan_cycle

        # Isolate daemon files
        alerts_file = tmp_path / "active_alerts.json"
        heartbeat_file = tmp_path / "daemon_heartbeat.json"
        alerts_log = tmp_path / "alerts_history.log"
        ledger_file = tmp_path / "paper_trading_ledger.csv"
        monkeypatch.setattr(live_monitor_daemon, "ALERTS_JSON", alerts_file)
        monkeypatch.setattr(live_monitor_daemon, "HEARTBEAT_JSON", heartbeat_file)
        monkeypatch.setattr(live_monitor_daemon, "ALERTS_LOG", alerts_log)
        monkeypatch.setattr(live_monitor_daemon, "LEDGER_CSV", ledger_file)
        monkeypatch.setattr(live_monitor_daemon, "build_html", lambda: None)
        monkeypatch.setattr(live_monitor_daemon, "send_windows_toast", lambda t, b: None)

        future_iso = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_signals = [
            # Corner signal (MBS 3, 7.5% edge) -> SHOULD PASS
            {
                "home": "Arsenal",
                "away": "Chelsea",
                "market": "Korner 9.5",
                "selection": "Korner 9.5 ÜST",
                "outcome": "Korner 9.5 ÜST",
                "soft_book": "nesine",
                "soft_odds": 1.95,
                "fair_odds": 1.72,
                "prob": 0.58,
                "edge_pct": 7.5,
                "mbs": 3,
                "time": "20:00",
                "kickoff": future_iso,
                "is_corner": True,
                "expected_corners": 10.42,
                "tier": "TIER_2_VALUE",
            },
            # Non-corner signal (MBS 3, 7.5% edge) -> SHOULD BE FILTERED
            {
                "home": "Liverpool",
                "away": "Everton",
                "market": "1X2",
                "selection": "MS 1",
                "outcome": "MS 1",
                "soft_book": "nesine",
                "soft_odds": 1.50,
                "fair_odds": 1.40,
                "prob": 0.71,
                "edge_pct": 7.5,
                "mbs": 3,
                "time": "20:00",
                "kickoff": future_iso,
                "is_corner": False,
                "tier": "TIER_1_SHIELD",
            },
        ]

        monkeypatch.setattr(
            live_monitor_daemon,
            "fetch_and_scan_live_propline",
            lambda settle_espn=False: {
                "leagues_scanned": 1,
                "fixtures_with_pinnacle": 2,
                "nesine_matched_fixtures": 2,
                "steam_confirmed_signals_count": 0,
                "signals": mock_signals,
            },
        )

        sent_telegram_messages = []
        monkeypatch.setattr(
            live_monitor_daemon,
            "send_telegram_message",
            lambda msg: sent_telegram_messages.append(msg),
        )

        res = run_single_scan_cycle(settle_espn=False, enable_telegram=True, scan_quant=False)

        assert res["fixtures_with_pinnacle"] == 2
        # Only the corner alert should have passed MBS 3 filter
        assert len(sent_telegram_messages) == 1
        msg = sent_telegram_messages[0]
        assert "🚩 *[KORNER DEĞER FIRSATI]*" in msg
        assert "Arsenal vs Chelsea" in msg
        assert "Korner 9.5" in msg
        assert "+%7.5%" in msg


# =====================================================================
# 5. TELEGRAM FORMATTING & MARKDOWN SANITIZATION TESTS
# =====================================================================

class TestTelegramFormattingAndSanitization:
    """Test format_corner_alert layout, Markdown character escaping, and slash commands."""

    def test_format_corner_alert_layout_and_fields(self):
        """Verify format_corner_alert includes header badge, expected corners, odds, prob, and edge."""
        signal = {
            "home": "Galatasaray",
            "away": "Fenerbahce",
            "time": "20:00",
            "mbs": 1,
            "market": "Korner 9.5",
            "selection": "Korner 9.5 ÜST",
            "soft_odds": 1.95,
            "fair_odds": 1.72,
            "prob": 0.581,
            "edge_pct": 13.37,
            "expected_corners": 10.42,
            "tier": "TIER_2_VALUE",
            "is_corner": True,
        }

        alert_text = format_corner_alert(signal)

        assert "🚩 *[KORNER DEĞER FIRSATI]*" in alert_text
        assert "⏰ *20:00* | ⚽ *Galatasaray vs Fenerbahce* (MBS 1)" in alert_text
        assert "👉 *Piyasa:* Korner 9.5 ➔ *Korner 9.5 ÜST*" in alert_text
        assert "📊 *Nesine Oranı:* `1.95` (Adil Oran: `1.72`)" in alert_text
        assert "📐 *Model:* Negatif Binom (κ=0.14) | μ: `10.42` korner" in alert_text
        assert "📈 *Kazanma Olasılığı:* `%58.1` | *Edge (EV):* `+%13.4%`" in alert_text
        assert "💡 _Tavsiye: Kasa yönetimi doğrultusunda %1.5 - %3.0 stake._" in alert_text

    def test_format_corner_alert_tier1_badge(self):
        """Verify format_corner_alert displays TIER 1 KASA KALKANI when tier is TIER_1_SHIELD."""
        signal = {
            "home": "Real Madrid",
            "away": "Barcelona",
            "time": "22:00",
            "mbs": 1,
            "market": "Korner 8.5",
            "selection": "Korner 8.5 ÜST",
            "soft_odds": 1.55,
            "fair_odds": 1.38,
            "prob": 0.725,
            "edge_pct": 12.38,
            "expected_corners": 11.20,
            "tier": "TIER_1_SHIELD",
            "is_corner": True,
        }

        alert_text = format_corner_alert(signal)
        assert "🛡️ *Kategori:* TIER 1 KASA KALKANI" in alert_text

    def test_markdown_sanitization_underscores_and_special_chars(self):
        """Verify team names and market keys with underscores do not produce unescaped Markdown syntax."""
        signal = {
            "home": "Real_Madrid_Castilla",
            "away": "Atletico_Madrid_B",
            "time": "18:00",
            "mbs": 2,
            "market": "Korner_9.5",
            "selection": "Korner_9.5_ÜST",
            "soft_odds": 2.05,
            "fair_odds": 1.82,
            "prob": 0.55,
            "edge_pct": 12.64,
            "expected_corners": 9.90,
            "tier": "TIER_2_VALUE",
            "is_corner": True,
        }

        alert_text = format_corner_alert(signal)

        # Underscores in team names and markets should be replaced with spaces
        assert "Real Madrid Castilla" in alert_text
        assert "Atletico Madrid B" in alert_text
        assert "Korner 9.5" in alert_text
        assert "Korner 9.5 ÜST" in alert_text
        assert "Real_Madrid_Castilla" not in alert_text

    def test_escape_markdown_utility(self):
        """Verify escape_markdown handles Telegram special tokens safely."""
        raw_text = "test_case *bold* `code` [link]"
        escaped = escape_markdown(raw_text)
        assert escaped == r"test\_case \*bold\* \`code\` \[link\]"
        assert escape_markdown("") == ""
        assert escape_markdown(None) == ""

    def test_interactive_korner_command_and_aliases(self):
        """Verify /korner, /corners, and /corner interactive bot commands return complete model info."""
        commands = ["/korner", "/corners", "/corner"]
        for cmd in commands:
            reply = process_user_command(cmd)
            assert "🚩 *KORNER MODELİ & PİYASA ANALİZİ*" in reply
            assert "Negatif Binom Dağılımı (κ=0.14)" in reply
            assert "6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5" in reply
            assert "+4.0% EV" in reply
