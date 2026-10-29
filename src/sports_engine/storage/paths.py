"""Storage path management for Medallion architecture (Bronze, Silver, Gold)."""

from pathlib import Path

from config.settings import get_settings


class StoragePaths:
    """Manages directory hierarchy and file locations across data layers."""

    def __init__(self, base_data_dir: Path | None = None):
        settings = get_settings()
        self.data_dir = Path(base_data_dir) if base_data_dir else settings.data_dir
        self.bronze_dir = self.data_dir / "bronze"
        self.silver_dir = self.data_dir / "silver"
        self.gold_dir = self.data_dir / "gold"
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        """Create bronze, silver, and gold layer directories if they do not exist."""
        for d in (self.bronze_dir, self.silver_dir, self.gold_dir):
            d.mkdir(parents=True, exist_ok=True)

    def bronze_path(self, source: str, entity_type: str, date_str: str, filename: str) -> Path:
        """Get path for immutable raw bronze file: data/bronze/{source}/{entity_type}/{date_str}/{filename}."""
        target_dir = self.bronze_dir / source / entity_type / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    def silver_path(self, entity_name: str, partition: str | None = None) -> Path:
        """Get path for canonical silver parquet: data/silver/{entity_name}/{partition}.parquet."""
        if partition:
            target_dir = self.silver_dir / entity_name
            target_dir.mkdir(parents=True, exist_ok=True)
            return target_dir / f"{partition}.parquet"
        return self.silver_dir / f"{entity_name}.parquet"

    def gold_path(self, dataset_name: str, filename: str) -> Path:
        """Get path for gold feature or prediction dataset: data/gold/{dataset_name}/{filename}."""
        target_dir = self.gold_dir / dataset_name
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    def get_layer_paths(self) -> dict[str, Path]:
        """Return root paths for all three architectural layers."""
        return {
            "bronze": self.bronze_dir,
            "silver": self.silver_dir,
            "gold": self.gold_dir,
        }
