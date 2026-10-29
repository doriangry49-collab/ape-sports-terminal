"""Test Parquet file read and write operations."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from sports_engine.domain.schemas import Team
from sports_engine.storage.parquet_io import read_parquet, write_parquet


def test_parquet_dataframe_roundtrip(tmp_path: Path):
    parquet_path = tmp_path / "df_test.parquet"
    df_orig = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "team": ["Galatasaray", "Fenerbahce", "Besiktas"],
            "points": [85.5, 82.0, 70.0],
        }
    )
    write_parquet(df_orig, parquet_path)
    assert parquet_path.exists()

    df_read = read_parquet(parquet_path)
    assert len(df_read) == 3
    assert list(df_read["team"]) == ["Galatasaray", "Fenerbahce", "Besiktas"]
    assert df_read.iloc[0]["points"] == 85.5


def test_parquet_domain_records_roundtrip(tmp_path: Path):
    parquet_path = tmp_path / "teams.parquet"
    now_utc = datetime.now(UTC)
    teams = [
        Team(
            canonical_team_id="galatasaray",
            canonical_league_id="tr_super_lig",
            name="Galatasaray",
            short_name="GS",
            created_at=now_utc,
        ),
        Team(
            canonical_team_id="fenerbahce",
            canonical_league_id="tr_super_lig",
            name="Fenerbahçe",
            short_name="FB",
            created_at=now_utc,
        ),
    ]

    write_parquet(teams, parquet_path)
    assert parquet_path.exists()

    df_read = read_parquet(parquet_path)
    assert len(df_read) == 2
    assert "galatasaray" in df_read["canonical_team_id"].values
    assert "fenerbahce" in df_read["canonical_team_id"].values
