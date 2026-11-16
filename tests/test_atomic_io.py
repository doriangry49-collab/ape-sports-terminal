"""Unit tests for atomic file I/O operations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atomic_io import atomic_write_json, atomic_write_text


def test_atomic_write_json_roundtrip(tmp_path: Path):
    target = tmp_path / "test_data.json"
    data = {
        "status": "HEALTHY",
        "count": 42,
        "nested": {"items": [1, 2, 3], "enabled": True},
        "turkish_chars": "Şampiyon Fenerbahçe & Beşiktaş & Galatasaray",
    }

    atomic_write_json(target, data)
    assert target.exists()

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == data

    # Verify no temporary files remain in directory
    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0


def test_atomic_write_json_preserves_on_failure(tmp_path: Path):
    target = tmp_path / "state.json"
    initial_data = {"version": 1, "safe": True}
    atomic_write_json(target, initial_data)

    # Attempt to write an un-serializable object
    class NonSerializable:
        pass

    bad_data = {"version": 2, "bad": NonSerializable()}

    with pytest.raises(TypeError):
        atomic_write_json(target, bad_data)

    # Original file must remain untouched
    preserved = json.loads(target.read_text(encoding="utf-8"))
    assert preserved == initial_data

    # Temporary files should be cleaned up
    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0


def test_atomic_write_json_nested_directory_creation(tmp_path: Path):
    target = tmp_path / "nested" / "deeply" / "folder" / "ledger.json"
    data = {"ledger_id": "LDG-100", "balance": 150.0}

    atomic_write_json(target, data)
    assert target.exists()

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["balance"] == 150.0


def test_atomic_write_text(tmp_path: Path):
    target = tmp_path / "offset.txt"
    atomic_write_text(target, "10042")
    assert target.read_text(encoding="utf-8") == "10042"

    atomic_write_text(target, "10043")
    assert target.read_text(encoding="utf-8") == "10043"

    temp_files = list(tmp_path.glob(".*.tmp_*"))
    assert len(temp_files) == 0
