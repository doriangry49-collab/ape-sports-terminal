"""Bootstrap verification script for sports-engine.

Checks directory structure, DuckDB readiness, and Parquet IO.
Can run locally on Windows without any external API keys or cloud dependencies.
"""

import sys
from pathlib import Path

# Add src to sys.path if not installed in editable mode
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from config.settings import get_settings  # noqa: E402
from sports_engine.storage.database import DuckDBManager  # noqa: E402
from sports_engine.storage.parquet_io import read_parquet, write_parquet  # noqa: E402
from sports_engine.storage.paths import StoragePaths  # noqa: E402


def run_bootstrap():
    print("=" * 60)
    print("Sports Intelligence Engine — Local Bootstrap Check")
    print("=" * 60)

    # 1. Settings & Directories
    settings = get_settings()
    print(f"[1] Environment: {settings.environment}")
    print(f"    Project Root: {settings.project_root}")
    print(f"    Data Root: {settings.data_dir}")
    print(f"    Bronze: {settings.bronze_dir}")
    print(f"    Silver: {settings.silver_dir}")
    print(f"    Gold: {settings.gold_dir}")

    # Check API keys (explicitly confirming none are required)
    has_api_keys = bool(settings.api_football_key or settings.rapidapi_key)
    print(
        f"    API Keys Configured: {'YES' if has_api_keys else 'NO (running locally without keys)'}"
    )

    # 2. Paths Manager
    paths = StoragePaths(settings.data_dir)
    layer_paths = paths.get_layer_paths()
    for _layer, p in layer_paths.items():
        assert p.exists(), f"Layer directory missing: {p}"
    print("[2] Storage layer directories verified: Bronze, Silver, Gold OK.")

    # 3. DuckDB In-Memory & File connectivity
    with DuckDBManager(db_path=":memory:") as db:
        res = db.execute("SELECT 1 AS status").fetchall()
        assert res == [(1,)], "DuckDB query failed"
    print("[3] DuckDB memory engine verified OK.")

    # 4. Parquet Roundtrip
    test_parquet = paths.silver_path("test_bootstrap_ping")
    write_parquet([{"id": 1, "test": "ping"}], test_parquet)
    df_read = read_parquet(test_parquet)
    assert len(df_read) == 1 and df_read.iloc[0]["test"] == "ping"
    if test_parquet.exists():
        test_parquet.unlink()
    print("[4] Parquet IO write/read roundtrip verified OK.")

    print("=" * 60)
    print("ALL BOOTSTRAP CHECKS PASSED SUCCESSFULLY.")
    print("=" * 60)


if __name__ == "__main__":
    run_bootstrap()
