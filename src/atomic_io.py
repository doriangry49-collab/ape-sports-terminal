"""Atomic File I/O utilities for preventing partial writes and file corruption."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(
    target_path: Path | str,
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Atomically write JSON data to target_path using temp file + atomic rename.

    Guarantees that readers never observe zero-byte, partial, or corrupted files
    even if the process is killed or interrupted mid-write.
    Fully compatible with Windows (closes file handle before os.replace) and POSIX.
    """
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Use same directory to ensure temp file and target reside on the same filesystem volume
    temp_fd, temp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.tmp_",
        dir=path.parent,
    )
    temp_path = Path(temp_path_str)

    try:
        with open(temp_fd, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())
        # Context manager exited: file descriptor closed, safe for Windows atomic replace
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(
    target_path: Path | str,
    text: str,
    encoding: str = "utf-8",
) -> None:
    """Atomically write string content to target_path using temp file + atomic rename."""
    path = Path(target_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.tmp_",
        dir=path.parent,
    )
    temp_path = Path(temp_path_str)

    try:
        with open(temp_fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
