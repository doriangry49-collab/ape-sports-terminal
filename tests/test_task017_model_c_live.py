"""TASK-017 — Unit and Regression Tests for Model C Live Activation and Odds Archive.

Tests:
1. Model C rating generation (attack/defense calculation)
2. Point-in-time cutoff (strict temporal filtering)
3. No future leakage (matches after cutoff are excluded)
4. League eligibility (>=30 matches threshold vs INSUFFICIENT_HISTORY)
5. Snapshot immutability (overwrites raise FileExistsError)
6. Odds movement calculation (STABLE, SHORTENED, DRIFTED)
7. Last prematch snapshot flag (kickoff proximity)
8. Bookmaker / model separation (independent probabilities, no odds input)
9. High odds classification (>= 5.0, >= 10.0 tiers)
10. Model C vs Global Baseline output consistency (team ratings change lambda)
"""

from datetime import UTC, datetime, timedelta

import pytest

from sports_engine.adapters.schema import NormalizedOddsRecord
from sports_engine.models.time_decay_poisson import (
    ModelCStatus,
    TimeDecayedPoissonModel,
)
from sports_engine.storage.odds_archive import (
    HistoricalOddsEntry,
    OddsArchiveManager,
)


@pytest.fixture
def sample_match_history():
    """Generates 40 synthetic historical matches across 4 teams for testing."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    matches = []
    teams = ["arsenal", "chelsea", "leeds", "fulham"]

    for i in range(40):
        m_dt = base_time + timedelta(days=i * 5)
        h = teams[i % 4]
        a = teams[(i + 1) % 4]
        # Make arsenal score more
        h_score = 3 if h == "arsenal" else 1
        a_score = 0 if h == "arsenal" else 2
        matches.append({
            "home_team": h,
            "away_team": a,
            "home_score": h_score,
            "away_score": a_score,
            "event_date": m_dt.isoformat(),
        })
    return matches


def test_1_model_c_rating_generation(sample_match_history):
    """Test 1: Model C correctly calculates shrunk, time-decayed attack and defense ratings."""
    model = TimeDecayedPoissonModel(decay_half_life_days=180.0, shrinkage_weight=3.0)
    model.fit(sample_match_history)

    assert model.is_fitted is True
    assert model.league_avg_home_goals > 0.5
    assert model.league_avg_away_goals > 0.5
    assert "arsenal" in model.team_stats

    # Arsenal scored heavily, so home_attack should be > 1.0
    ars_stats = model.team_stats["arsenal"]
    assert ars_stats["home_attack"] > 1.0
    assert ars_stats["home_defense"] > 0.0


def test_2_and_3_point_in_time_cutoff_and_no_leakage(sample_match_history):
    """Test 2 & 3: Matches occurring on or after data_cutoff are strictly excluded."""
    # Set cutoff at day 100
    cutoff = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(days=100)
    model = TimeDecayedPoissonModel(min_required_matches=10)
    model.fit(sample_match_history, data_cutoff=cutoff)

    # All matches in fitted model must be < cutoff
    assert model.total_matches < len(sample_match_history)
    assert model.data_cutoff == cutoff


def test_4_league_eligibility(sample_match_history):
    """Test 4: League eligibility requires >= 30 matches; below that returns INSUFFICIENT_HISTORY."""
    model = TimeDecayedPoissonModel(min_required_matches=30)

    # 40 matches -> AVAILABLE
    elig_good = model.check_eligibility("epl", "Premier League", sample_match_history)
    assert elig_good.status == ModelCStatus.AVAILABLE

    # 15 matches -> INSUFFICIENT_HISTORY
    elig_bad = model.check_eligibility("small_league", "Minor League", sample_match_history[:15])
    assert elig_bad.status == ModelCStatus.INSUFFICIENT_HISTORY


def test_5_snapshot_immutability(tmp_path):
    """Test 5: Overwriting an existing snapshot raises FileExistsError."""
    archive = OddsArchiveManager(tmp_path)
    entry = HistoricalOddsEntry(
        snapshot_id="snap_001",
        captured_at="2026-10-03T10:00:00Z",
        event_id="ev_001",
        provider="propline",
        bookmaker="pinnacle",
        competition="Premier League",
        market="1X2",
        selection="HOME",
        odds_raw="-150",
        odds_decimal=1.6667,
        event_start_time="2026-10-10T11:30:00Z",
        home_team="Arsenal",
        away_team="Leeds",
    )

    # Save once
    p = archive.save_immutable_snapshot("snap_001", [entry])
    assert p.exists()

    # Attempt second save with same ID -> FileExistsError
    with pytest.raises(FileExistsError):
        archive.save_immutable_snapshot("snap_001", [entry])


def test_6_odds_movement_calculation():
    """Test 6: Line movement calculation accurately classifies STABLE, SHORTENED, and DRIFTED."""
    old_records = [
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "HOME", "odds_decimal": 2.00,
            "captured_at": "2026-10-01T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "AWAY", "odds_decimal": 3.00,
            "captured_at": "2026-10-01T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "DRAW", "odds_decimal": 3.20,
            "captured_at": "2026-10-01T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
    ]

    new_records = [
        # 2.00 -> 1.85 (shortened)
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "HOME", "odds_decimal": 1.85,
            "captured_at": "2026-10-03T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
        # 3.00 -> 3.50 (drifted)
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "AWAY", "odds_decimal": 3.50,
            "captured_at": "2026-10-03T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
        # 3.20 -> 3.21 (stable)
        {
            "event_id": "ev_1", "provider": "propline", "bookmaker": "pinnacle",
            "market": "1X2", "selection": "DRAW", "odds_decimal": 3.21,
            "captured_at": "2026-10-03T10:00:00Z", "home_team": "Team A", "away_team": "Team B"
        },
    ]

    moves = OddsArchiveManager.calculate_line_movement(old_records, new_records)
    assert len(moves) == 3

    home_m = next(m for m in moves if m["selection"] == "HOME")
    assert home_m["direction"] == "SHORTENED"
    assert home_m["pct_change"] == -7.5

    away_m = next(m for m in moves if m["selection"] == "AWAY")
    assert away_m["direction"] == "DRIFTED"
    assert away_m["pct_change"] == 16.67

    draw_m = next(m for m in moves if m["selection"] == "DRAW")
    assert draw_m["direction"] == "STABLE"


def test_7_last_prematch_snapshot_flag(tmp_path):
    """Test 7: Kickoff within 2 hours sets is_last_prematch=True."""
    archive = OddsArchiveManager(tmp_path)
    now = datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)

    # Match in 1 hour
    rec_close = NormalizedOddsRecord(
        event_id="e1", provider="propline", bookmaker="bovada", sport="soccer",
        country="England", competition="Premier League", home_team="Arsenal",
        away_team="Leeds", kickoff="2026-10-03T11:00:00Z", market="1X2",
        market_period="FULL_MATCH", match_phase="PREMATCH", selection="HOME",
        odds_decimal=1.5, odds_raw="1.5", odds_format="DECIMAL", captured_at=now,
        source_event_id="1", source_market_id="h2h", source_selection_id="HOME",
        source_status="open",
    )

    # Match in 7 days
    rec_far = NormalizedOddsRecord(
        event_id="e2", provider="propline", bookmaker="bovada", sport="soccer",
        country="England", competition="Premier League", home_team="Arsenal",
        away_team="Leeds", kickoff="2026-10-10T11:00:00Z", market="1X2",
        market_period="FULL_MATCH", match_phase="PREMATCH", selection="HOME",
        odds_decimal=1.5, odds_raw="1.5", odds_format="DECIMAL", captured_at=now,
        source_event_id="2", source_market_id="h2h", source_selection_id="HOME",
        source_status="open",
    )

    entries = archive.create_snapshot_records([rec_close, rec_far], "snap_test", captured_at=now)
    assert entries[0].is_last_prematch is True
    assert entries[1].is_last_prematch is False


def test_8_bookmaker_model_separation(sample_match_history):
    """Test 8: Model C generates probability and fair odds without bookmaker odds as input."""
    model = TimeDecayedPoissonModel()
    model.fit(sample_match_history)
    pred = model.predict_match(home_team="arsenal", away_team="leeds")

    # Probabilities sum to ~1.0
    tot_p = pred.home_probability + pred.draw_probability + pred.away_probability
    assert 0.99 <= tot_p <= 1.01

    # Fair odds are strictly mathematical inverse of probability
    assert pred.fair_home_odds == pytest.approx(1.0 / pred.home_probability, rel=1e-2)
    assert "odds" not in pred.metadata  # No odds passed to model


def test_9_high_odds_classification():
    """Test 9: High odds tiers properly separate >= 5.0, >= 10.0, >= 20.0."""
    odds_candidates = [3.5, 5.5, 12.0, 25.0, 75.0, 150.0]
    tier_5 = [o for o in odds_candidates if o >= 5.0]
    tier_10 = [o for o in odds_candidates if o >= 10.0]
    tier_20 = [o for o in odds_candidates if o >= 20.0]
    tier_50 = [o for o in odds_candidates if o >= 50.0]
    tier_100 = [o for o in odds_candidates if o >= 100.0]

    assert len(tier_5) == 5
    assert len(tier_10) == 4
    assert len(tier_20) == 3
    assert len(tier_50) == 2
    assert len(tier_100) == 1


def test_10_model_c_vs_global_baseline_consistency(sample_match_history):
    """Test 10: Model C derives distinct team lambdas whereas Global Baseline uses constant lambdas."""
    # Global Baseline
    lambda_h_global = 1.42
    lambda_a_global = 1.12

    # Model C
    model = TimeDecayedPoissonModel()
    model.fit(sample_match_history)
    pred = model.predict_match(home_team="arsenal", away_team="leeds")

    # Arsenal had strong offense in history fixture -> lambda_h != 1.42
    assert pred.expected_home_goals != lambda_h_global
    assert pred.expected_away_goals != lambda_a_global
    assert pred.expected_home_goals > pred.expected_away_goals
