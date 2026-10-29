"""Parquet file read and write operations using DuckDB native parquet engine."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel


def records_to_dataframe(records: Sequence[BaseModel | dict[str, Any] | pd.Series]) -> pd.DataFrame:
    """Convert sequence of Pydantic models, dicts, or Series to a pandas DataFrame."""
    if isinstance(records, pd.DataFrame):
        return records

    rows: list[dict[str, Any]] = []
    for item in records:
        if isinstance(item, BaseModel):
            rows.append(item.model_dump(mode="python"))
        elif isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, pd.Series):
            rows.append(item.to_dict())
        else:
            raise TypeError(f"Unsupported record type: {type(item)}")

    return pd.DataFrame(rows)


def write_parquet(
    data: pd.DataFrame | Sequence[BaseModel | dict[str, Any]],
    destination_path: str | Path,
    partition_cols: list[str] | None = None,
) -> Path:
    """Write DataFrame or sequence of domain entities to Parquet file via DuckDB engine."""
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    df = data if isinstance(data, pd.DataFrame) else records_to_dataframe(data)
    dest_str = str(dest).replace("\\", "/")

    # Use DuckDB native parquet writing
    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("source_df", df)
        if partition_cols:
            cols_str = ", ".join(partition_cols)
            conn.execute(
                f"COPY source_df TO '{dest_str}' (FORMAT PARQUET, PARTITION_BY ({cols_str}))"
            )
        else:
            conn.execute(f"COPY source_df TO '{dest_str}' (FORMAT PARQUET)")
    finally:
        conn.close()

    return dest


def read_parquet(parquet_path: str | Path) -> pd.DataFrame:
    """Read a Parquet file into a pandas DataFrame using DuckDB."""
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    path_str = str(path).replace("\\", "/")
    conn = duckdb.connect(database=":memory:")
    try:
        return conn.execute(f"SELECT * FROM read_parquet('{path_str}')").df()
    finally:
        conn.close()
