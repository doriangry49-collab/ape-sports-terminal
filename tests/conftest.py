"""Pytest configuration and shared fixtures for sports-engine test suite."""

import sys
from pathlib import Path

import pytest

# Ensure src and project root are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Provides an isolated temporary data directory with bronze/silver/gold subfolders."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
