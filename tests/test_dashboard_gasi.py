"""Unit tests for GASI & Over 3.5 Goal Anomaly dashboard visualization."""

from __future__ import annotations

import json
import pytest
import sys
from pathlib import Path

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SPORTS_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT / "src"))

from build_dashboard import build_html, OUT_HTML, LIVE_JSON


def test_build_dashboard_with_gasi_badges(tmp_path, monkeypatch):
    """Verify build_dashboard renders GASI KPI, filter button, and Over 3.5 badges."""
    test_live_json = tmp_path / "live_stale_line_signals.json"
    test_out_html = tmp_path / "live_signals_dashboard.html"

    # Sample live bulletin with 1 Gold Tier match and 1 Standard match
    payload = {
        "captured_at_utc": "2026-11-12T10:00:00Z",
        "leagues_scanned": 12,
        "fixtures_with_pinnacle": 2,
        "nesine_total_football_bulletin": 2,
        "nesine_matched_fixtures": 2,
        "positive_ev_signals": [],
        "fixtures": [
            {
                "home": "Bayern Munich",
                "away": "Borussia Dortmund",
                "league": "Bundesliga",
                "kickoff": "19:30",
                "pinnacle_1x2": [1.70, 4.00, 4.50],
                "shin_fair_1x2": [1.75, 3.90, 4.20],
                "shin_probs_1x2": [0.57, 0.25, 0.18],
                "pinnacle_ou25": [1.30, 3.40],
                "shin_probs_ou25": [0.75, 0.25],
                "nesine_1x2": [1.65, 3.80, 4.20],
                "nesine_ou25": [1.28, 3.10],
                "nesine_code": "1001",
                "nesine_mbs": 1,
                "nesine_min_ev_home": 1.79,
                "nesine_min_ev_draw": 4.05,
                "nesine_min_ev_away": 4.35,
            },
            {
                "home": "Getafe",
                "away": "Leganes",
                "league": "La Liga",
                "kickoff": "21:00",
                "pinnacle_1x2": [2.40, 3.00, 3.20],
                "shin_fair_1x2": [2.45, 2.95, 3.15],
                "shin_probs_1x2": [0.40, 0.33, 0.27],
                "pinnacle_ou25": [2.35, 1.55],
                "shin_probs_ou25": [0.42, 0.58],
                "nesine_1x2": [2.30, 2.90, 3.00],
                "nesine_ou25": [2.25, 1.50],
                "nesine_code": "1002",
                "nesine_mbs": 2,
                "nesine_min_ev_home": 2.50,
                "nesine_min_ev_draw": 3.05,
                "nesine_min_ev_away": 3.25,
            },
        ],
    }

    test_live_json.write_text(json.dumps(payload), encoding="utf-8")

    # Patch paths and heavy portfolio builders for fast isolated unit test
    import build_dashboard
    monkeypatch.setattr(build_dashboard, "LIVE_JSON", test_live_json)
    monkeypatch.setattr(build_dashboard, "OUT_HTML", test_out_html)
    monkeypatch.setattr(build_dashboard, "REFEREE_PARQUET", tmp_path / "nonexistent.parquet")
    monkeypatch.setattr(build_dashboard, "build_recovery_portfolio", lambda *a, **kw: {})
    monkeypatch.setattr(build_dashboard, "generate_system_coupon", lambda *a, **kw: {})

    # Build
    build_html()

    assert test_out_html.exists()
    html_content = test_out_html.read_text(encoding="utf-8")

    # 1. Check KPI Card
    assert "Goal Anomaly (GASI &ge; 65)" in html_content
    assert "Over 3.5" in html_content

    # 2. Check Filter Button
    assert "gasiFilterBtn" in html_content
    assert "GASI Gol Anomalisi" in html_content

    # 3. Check Row Attributes and Badges
    assert 'data-gasi="1"' in html_content
    assert "🏆 GASI" in html_content
    assert "🎯 Over 3.5 (+EV)" in html_content
    assert "1 Numaralı Pazar: OVER 3.5" in html_content
