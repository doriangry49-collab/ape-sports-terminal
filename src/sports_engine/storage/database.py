"""DuckDB database interface and query execution manager."""

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from config.settings import get_settings


class DuckDBManager:
    """Manages DuckDB connections, querying, and Parquet table attachments."""

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        settings = get_settings()
        if db_path is None:
            self.db_path = settings.duckdb_path
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
        else:
            self.db_path = Path(db_path)

        # In-memory or file-backed
        if str(self.db_path) == ":memory:":
            self._connection = duckdb.connect(database=":memory:", read_only=False)
        else:
            if not read_only and self.db_path.parent:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(database=str(self.db_path), read_only=read_only)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return active DuckDB connection."""
        return self._connection

    def execute(
        self, query: str, parameters: list[Any] | tuple[Any, ...] | None = None
    ) -> duckdb.DuckDBPyConnection:
        """Execute raw SQL query."""
        if parameters:
            return self._connection.execute(query, parameters)
        return self._connection.execute(query)

    def query_df(
        self, query: str, parameters: list[Any] | tuple[Any, ...] | None = None
    ) -> pd.DataFrame:
        """Execute SQL query and return result as pandas DataFrame."""
        cursor = self.execute(query, parameters)
        return cursor.df()

    def register_parquet_view(self, view_name: str, parquet_path: str | Path) -> None:
        """Register a Parquet file as a DuckDB view."""
        path_str = str(parquet_path).replace("\\", "/")
        query = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_parquet('{path_str}');"
        self._connection.execute(query)

    def close(self) -> None:
        """Close connection."""
        if self._connection:
            self._connection.close()

    def __enter__(self) -> "DuckDBManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
