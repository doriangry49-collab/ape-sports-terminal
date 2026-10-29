"""Configuration and runtime settings for Sports Intelligence Engine."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Automatically find and load .env if present
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings(BaseModel):
    """Application settings with zero mandatory external API keys."""

    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    default_timezone: str = Field(default_factory=lambda: os.getenv("DEFAULT_TIMEZONE", "UTC"))

    # Paths
    project_root: Path = Field(default=_PROJECT_ROOT)
    data_dir: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / os.getenv("SPORTS_ENGINE_DATA_DIR", "data")
    )
    bronze_dir: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / os.getenv("SPORTS_ENGINE_BRONZE_DIR", "data/bronze")
    )
    silver_dir: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / os.getenv("SPORTS_ENGINE_SILVER_DIR", "data/silver")
    )
    gold_dir: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / os.getenv("SPORTS_ENGINE_GOLD_DIR", "data/gold")
    )
    duckdb_path: Path = Field(
        default_factory=lambda: (
            _PROJECT_ROOT / os.getenv("SPORTS_ENGINE_DUCKDB_PATH", "data/sports_engine.duckdb")
        )
    )

    # Optional provider credentials (NOT required to run)
    api_football_key: str | None = Field(default_factory=lambda: os.getenv("API_FOOTBALL_KEY"))
    rapidapi_key: str | None = Field(default_factory=lambda: os.getenv("RAPIDAPI_KEY"))
    bzzoiro_key: str | None = Field(default_factory=lambda: os.getenv("BZZOIRO_KEY"))
    propline_key: str | None = Field(default_factory=lambda: os.getenv("PROPLINE_KEY"))
    xiddaa_key: str | None = Field(default_factory=lambda: os.getenv("XIDDAA_KEY"))

    def ensure_directories(self) -> None:
        """Ensure all storage layer directories exist."""
        for path in (self.data_dir, self.bronze_dir, self.silver_dir, self.gold_dir):
            path.mkdir(parents=True, exist_ok=True)
            if self.duckdb_path.parent:
                self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
