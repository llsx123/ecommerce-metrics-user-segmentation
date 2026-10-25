"""SQLite helpers: connections, schema creation, bulk loading and query helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .config import CLEAN_DB, RAW_DB, SQL_DIR


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys enabled and rows as ``sqlite3.Row``."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection, schema_path: Path | None = None) -> None:
    path = schema_path or SQL_DIR / "schema.sql"
    conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()


def load_tables(conn: sqlite3.Connection, tables: dict[str, pd.DataFrame]) -> None:
    """Bulk-load dataframes into the tables of the same name."""
    for name, frame in tables.items():
        if frame.empty:
            continue
        frame.to_sql(name, conn, if_exists="append", index=False)
    conn.commit()


def build_database(
    tables: dict[str, pd.DataFrame],
    db_path: Path | str = RAW_DB,
    schema_path: Path | None = None,
) -> Path:
    """Create ``db_path`` from scratch and load ``tables`` into it."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = connect(path)
    try:
        create_schema(conn, schema_path)
        load_tables(conn, tables)
    finally:
        conn.close()
    return path


def read_sql(conn: sqlite3.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params or {})


def read_sql_file(conn: sqlite3.Connection, filename: str, params: dict | None = None) -> pd.DataFrame:
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    return read_sql(conn, sql, params)


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {name: conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()["n"] for name in table_names(conn)}


def default_clean_db() -> Path:
    return CLEAN_DB
