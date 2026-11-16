"""Unit tests for sports-engine/scripts/update_historical_data.py."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SRC_DIR = PROJECT_ROOT / "src"
for p in (SCRIPTS_DIR, SRC_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import update_historical_data as uhd  # noqa: E402

from team_normalizer import TeamNormalizer  # noqa: E402


def test_resolve_canonical_team_name_exact_accent_and_unknown() -> None:
    normalizer = TeamNormalizer()
    candidates = {
        "Fenerbahce",
        "Galatasaray",
        "Leeds",
        "Man United",
        "Paris FC",
        "Paris SG",
        "Istanbulspor",
        "Buyuksehyr",
        "Forest Green",
        "Nott'm Forest",
        "Club Brugge",
        "Cercle Brugge",
    }

    assert uhd.resolve_canonical_team_name("Galatasaray", candidates, normalizer) == "Galatasaray"
    assert uhd.resolve_canonical_team_name("Fenerbahçe", candidates, normalizer) == "Fenerbahce"
    assert uhd.resolve_canonical_team_name("Leeds United", candidates, normalizer) == "Leeds"
    assert uhd.resolve_canonical_team_name("Paris Saint-Germain", candidates, normalizer) == "Paris SG"
    assert uhd.resolve_canonical_team_name("Istanbul Basaksehir", candidates, normalizer) == "Buyuksehyr"
    assert uhd.resolve_canonical_team_name("Nottingham Forest", candidates, normalizer) == "Nott'm Forest"
    assert uhd.resolve_canonical_team_name("Cercle Brugge KSV", candidates, normalizer) == "Cercle Brugge"
    assert uhd.resolve_canonical_team_name("Completely Unrelated FC", candidates, normalizer) == "Completely Unrelated FC"


def test_parse_espn_scoreboard_events_filters_and_maps_stats() -> None:
    normalizer = TeamNormalizer()
    candidates = {"Fenerbahce", "Besiktas", "Trabzonspor"}

    payload: dict[str, Any] = {
        "events": [
            {
                "date": "2026-11-08T17:00Z",
                "competitions": [
                    {
                        "date": "2026-11-08T17:00Z",
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "2",
                                "team": {"displayName": "Fenerbahçe"},
                                "statistics": [
                                    {"name": "totalShots", "displayValue": "15"},
                                    {"name": "shotsOnTarget", "displayValue": "6"},
                                    {"name": "foulsCommitted", "displayValue": "11"},
                                    {"name": "wonCorners", "displayValue": "7"},
                                ],
                            },
                            {
                                "homeAway": "away",
                                "score": "1",
                                "team": {"displayName": "Beşiktaş"},
                                "statistics": [
                                    {"name": "totalShots", "displayValue": "9"},
                                    {"name": "shotsOnTarget", "displayValue": "3"},
                                    {"name": "foulsCommitted", "displayValue": "14"},
                                    {"name": "wonCorners", "displayValue": "4"},
                                ],
                            },
                        ],
                    }
                ],
            },
            # Incomplete match -> must be skipped
            {
                "date": "2026-11-09T17:00Z",
                "competitions": [
                    {
                        "date": "2026-11-09T17:00Z",
                        "status": {"type": {"completed": False}},
                        "competitors": [
                            {"homeAway": "home", "score": "0", "team": {"displayName": "Trabzonspor"}},
                            {"homeAway": "away", "score": "0", "team": {"displayName": "Fenerbahçe"}},
                        ],
                    }
                ],
            },
            # Beyond cutoff -> must be skipped
            {
                "date": "2026-11-20T17:00Z",
                "competitions": [
                    {
                        "date": "2026-11-20T17:00Z",
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"homeAway": "home", "score": "1", "team": {"displayName": "Trabzonspor"}},
                            {"homeAway": "away", "score": "1", "team": {"displayName": "Fenerbahçe"}},
                        ],
                    }
                ],
            },
        ]
    }

    rows = uhd._parse_espn_scoreboard_events(
        data=payload,
        div_code="T1",
        cutoff_ymd="2026-11-14",
        canonical_names=candidates,
        normalizer=normalizer,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["Div"] == "T1"
    assert row["Date"] == "08/11/2026"
    assert row["HomeTeam"] == "Fenerbahce"
    assert row["AwayTeam"] == "Besiktas"
    assert row["FTHG"] == 2
    assert row["FTAG"] == 1
    assert row["FTR"] == "H"
    assert row["HS"] == 15 and row["AS"] == 9
    assert row["HST"] == 6 and row["AST"] == 3
    assert row["HF"] == 11 and row["AF"] == 14
    assert row["HC"] == 7 and row["AC"] == 4


def test_fetch_2627_division_csv_falls_back_to_espn_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    normalizer = TeamNormalizer()
    candidates = {"Arsenal", "Chelsea", "Liverpool"}

    def fake_http_get(url: str, timeout: float = 8.0) -> str:
        if "football-data.co.uk" in url:
            raise TimeoutError("timed out")
        if url.endswith("/scoreboard"):
            return json.dumps({
                "leagues": [{
                    "calendar": [
                        "2026-11-08T00:00Z",
                        "2026-11-01T00:00Z",
                        "2026-11-25T00:00Z",  # > cutoff, skipped
                    ]
                }]
            })
        if "dates=20261101" in url:
            return json.dumps({
                "events": [{
                    "date": "2026-11-01T15:00Z",
                    "competitions": [{
                        "date": "2026-11-01T15:00Z",
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"homeAway": "home", "score": "1", "team": {"displayName": "Arsenal"}, "statistics": []},
                            {"homeAway": "away", "score": "1", "team": {"displayName": "Chelsea"}, "statistics": []},
                        ],
                    }],
                }]
            })
        if "dates=20261108" in url:
            return json.dumps({
                "events": [{
                    "date": "2026-11-08T16:30Z",
                    "competitions": [{
                        "date": "2026-11-08T16:30Z",
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"homeAway": "home", "score": "0", "team": {"displayName": "Chelsea"}, "statistics": []},
                            {"homeAway": "away", "score": "2", "team": {"displayName": "Liverpool"}, "statistics": []},
                        ],
                    }],
                }]
            })
        return json.dumps({"events": []})

    monkeypatch.setattr(uhd, "_http_get_text", fake_http_get)

    source, rows = uhd.fetch_2627_division_csv(
        div_code="E0",
        espn_slug="eng.1",
        cutoff_ymd="2026-11-14",
        canonical_names=candidates,
        normalizer=normalizer,
    )
    assert source == "espn:eng.1"
    assert isinstance(rows, list)
    assert [r["Date"] for r in rows] == ["01/11/2026", "08/11/2026"]
    assert rows[0]["FTR"] == "D"
    assert rows[1]["FTR"] == "A"


def test_fetch_2627_division_csv_prefers_football_data_when_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    csv_body = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,15/08/2026,Arsenal,Chelsea,2,0,H\n"

    def fake_http_get(url: str, timeout: float = 8.0) -> str:
        assert "football-data.co.uk" in url
        return csv_body

    monkeypatch.setattr(uhd, "_http_get_text", fake_http_get)
    source, payload = uhd.fetch_2627_division_csv(
        div_code="E0",
        espn_slug="eng.1",
        cutoff_ymd="2026-11-14",
        canonical_names={"Arsenal", "Chelsea"},
        normalizer=TeamNormalizer(),
    )
    assert source == "football-data.co.uk"
    assert payload == csv_body


def test_update_extra_league_csvs_mirror_fallback_and_row_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Existing BRA has 5 rows (smaller than mirror's 120), USA has 150 rows (larger -> kept_existing)
    (tmp_path / "BRA.csv").write_text("Country,League\n" + "Brazil,Serie A\n" * 5, encoding="utf-8")
    (tmp_path / "USA.csv").write_text("Country,League\n" + "USA,MLS\n" * 150, encoding="utf-8")

    mirror_csv = "Country,League,Season,Date,Home,Away,HG,AG,Res\n" + "".join(
        f"Brazil,Serie A,2026,06/11/2026,TeamA{i},TeamB{i},1,0,H\n" for i in range(120)
    )

    def fake_http_get(url: str, timeout: float = 8.0) -> str:
        if "football-data.co.uk" in url:
            raise TimeoutError("blocked")
        if "brazil" in url or "usa" in url:
            return mirror_csv
        raise RuntimeError(f"unexpected {url}")

    monkeypatch.setattr(uhd, "_http_get_text", fake_http_get)

    res = uhd.update_extra_league_csvs(raw_dir=tmp_path)
    assert res["BRA.csv"]["status"] == "updated"
    assert res["BRA.csv"]["rows"] == 120
    assert res["BRA.csv"]["delta_rows"] == 115
    assert "huhao930422-debug/football-odds-mirror" in res["BRA.csv"]["source"]

    assert res["USA.csv"]["status"] == "kept_existing"
    assert res["USA.csv"]["rows"] == 150

    manifest_path = tmp_path / "extra_leagues_manifest.csv"
    assert manifest_path.exists()
    with open(manifest_path, encoding="utf-8") as f:
        manifest_rows = list(csv.DictReader(f))
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["file"] == "BRA.csv"


def test_http_get_text_strips_utf8_bom(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        status = 200

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"\xef\xbb\xbfCountry,League\nBrazil,Serie A\n"

    monkeypatch.setattr(uhd.urllib.request, "urlopen", lambda req, timeout=8.0: FakeResp())
    txt = uhd._http_get_text("https://example.com/bra.csv")
    assert txt.startswith("Country,League")

