"""Test Medallion storage paths (Bronze, Silver, Gold)."""

from pathlib import Path

from sports_engine.storage.paths import StoragePaths


def test_storage_paths_creation(tmp_path: Path):
    storage = StoragePaths(base_data_dir=tmp_path)
    layers = storage.get_layer_paths()

    assert layers["bronze"].exists()
    assert layers["silver"].exists()
    assert layers["gold"].exists()

    # Test Bronze Path
    b_path = storage.bronze_path(
        source="livescore_json",
        entity_type="fixtures",
        date_str="20261028",
        filename="match_123.json",
    )
    assert "bronze" in str(b_path)
    assert "livescore_json" in str(b_path)
    assert b_path.name == "match_123.json"

    # Test Silver Path
    s_path = storage.silver_path("fixtures", partition="2026")
    assert "silver" in str(s_path)
    assert s_path.name == "2026.parquet"

    # Test Gold Path
    g_path = storage.gold_path("predictions", "superlig_matchday_10.parquet")
    assert "gold" in str(g_path)
    assert g_path.name == "superlig_matchday_10.parquet"
