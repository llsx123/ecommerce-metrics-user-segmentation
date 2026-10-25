"""SQL implementations of the metric layer (thin wrappers around ``sql/*.sql``)."""

from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd

from . import db


def overall(conn: sqlite3.Connection, snapshot: str) -> dict[str, Any]:
    frame = db.read_sql_file(conn, "overall_metrics.sql", {"snapshot": snapshot})
    return frame.iloc[0].to_dict()


def monthly(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    return db.read_sql_file(conn, "monthly_metrics.sql", {"snapshot": snapshot})


def category(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    return db.read_sql_file(conn, "category_metrics.sql", {"snapshot": snapshot})


def users(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    return db.read_sql_file(conn, "user_metrics.sql", {"snapshot": snapshot})


def repeat_intervals(conn: sqlite3.Connection, snapshot: str) -> dict[str, Any]:
    frame = db.read_sql_file(conn, "repeat_intervals.sql", {"snapshot": snapshot})
    return frame.iloc[0].to_dict()


def rfm(conn: sqlite3.Connection, snapshot: str, cuts: dict[str, float]) -> pd.DataFrame:
    params = {"snapshot": snapshot, **cuts}
    return db.read_sql_file(conn, "user_rfm.sql", params)
