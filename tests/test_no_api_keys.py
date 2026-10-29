"""Test that the engine operates completely locally with no API keys configured."""

import os
from unittest.mock import patch

from config.settings import Settings
from sports_engine.storage.database import DuckDBManager
from sports_engine.storage.paths import StoragePaths


def test_no_api_keys_operation(tmp_path):
    # Simulate an environment where all API keys are unset or empty
    clean_env = {
        "API_FOOTBALL_KEY": "",
        "RAPIDAPI_KEY": "",
        "SPORTS_ENGINE_DATA_DIR": str(tmp_path / "data"),
    }
    with patch.dict(os.environ, clean_env, clear=False):
        settings = Settings(
            data_dir=tmp_path / "data",
            bronze_dir=tmp_path / "data" / "bronze",
            silver_dir=tmp_path / "data" / "silver",
            gold_dir=tmp_path / "data" / "gold",
            duckdb_path=tmp_path / "data" / "test.duckdb",
        )
        settings.ensure_directories()

        assert settings.api_football_key is None or settings.api_football_key == ""
        assert settings.rapidapi_key is None or settings.rapidapi_key == ""

        # Storage paths initialize cleanly
        paths = StoragePaths(base_data_dir=tmp_path / "data")
        assert paths.bronze_dir.exists()
        assert paths.silver_dir.exists()
        assert paths.gold_dir.exists()

        # Database initializes cleanly
        with DuckDBManager(db_path=settings.duckdb_path) as db:
            res = db.execute("SELECT 'offline_ready' AS status").fetchall()
            assert res == [("offline_ready",)]
