"""Test DuckDB connectivity, memory engine, and file database creation."""

from pathlib import Path

from sports_engine.storage.database import DuckDBManager


def test_duckdb_memory_connection():
    with DuckDBManager(db_path=":memory:") as db:
        res = db.execute("SELECT 42 AS num, 'superlig' AS league").fetchall()
        assert res == [(42, "superlig")]


def test_duckdb_query_df():
    with DuckDBManager(db_path=":memory:") as db:
        db.execute("CREATE TABLE teams (id VARCHAR, name VARCHAR)")
        db.execute("INSERT INTO teams VALUES ('gs', 'Galatasaray'), ('fb', 'Fenerbahçe')")
        df = db.query_df("SELECT * FROM teams ORDER BY id")
        assert len(df) == 2
        assert list(df["id"]) == ["fb", "gs"]


def test_duckdb_file_database(tmp_path: Path):
    db_file = tmp_path / "test_sports.duckdb"
    with DuckDBManager(db_path=db_file) as db:
        db.execute("CREATE TABLE test_tab (val INT)")
        db.execute("INSERT INTO test_tab VALUES (100)")
        res = db.execute("SELECT val FROM test_tab").fetchone()
        assert res == (100,)
    assert db_file.exists()
