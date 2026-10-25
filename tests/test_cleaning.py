"""Cleaning: whole-order quarantine, strict schema and reconciliation after cleaning."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from ecom import db, clean


@pytest.fixture(scope="module")
def clean_conn(small_env):
    connection = db.connect(small_env.clean)
    yield connection
    connection.close()


def test_quarantine_is_not_empty(small_env):
    assert small_env.stats["quarantined_orders"] > 0
    assert small_env.stats["clean_orders"] == small_env.stats["raw_orders"] - small_env.stats["quarantined_orders"]


def test_strict_schema_rejects_duplicate_users(clean_conn):
    existing = clean_conn.execute("SELECT customer_id FROM users LIMIT 1").fetchone()["customer_id"]
    with pytest.raises(sqlite3.IntegrityError):
        clean_conn.execute(
            "INSERT INTO users (customer_id, customer_unique_id) VALUES (?, 'x')", (existing,)
        )
    clean_conn.rollback()


def test_strict_schema_rejects_negative_price(clean_conn):
    order_id = clean_conn.execute("SELECT order_id FROM orders LIMIT 1").fetchone()["order_id"]
    product_id = clean_conn.execute("SELECT product_id FROM products LIMIT 1").fetchone()["product_id"]
    with pytest.raises(sqlite3.IntegrityError):
        clean_conn.execute(
            "INSERT INTO order_items (order_id, order_item_id, product_id, price, freight_value)"
            " VALUES (?, 999, ?, -1.0, 0.0)",
            (order_id, product_id),
        )
    clean_conn.rollback()


def test_all_payments_reconcile_after_cleaning(clean_conn):
    frame = pd.read_sql_query(
        """
        SELECT o.order_id,
               (SELECT SUM(payment_value) FROM payments p WHERE p.order_id = o.order_id) AS paid,
               (SELECT SUM(price + freight_value) FROM order_items i WHERE i.order_id = o.order_id) AS items
        FROM orders o
        WHERE EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
        """,
        clean_conn,
    )
    assert frame["paid"].notna().all()
    assert frame["items"].notna().all()
    assert ((frame["paid"] - frame["items"]).abs() <= 0.01).all()


def test_every_quarantined_order_has_a_reason(small_env):
    raw = db.connect(small_env.raw)
    try:
        reasons = clean.quarantine_reasons(raw, small_env.snapshot)
    finally:
        raw.close()
    assert len(reasons) == small_env.stats["quarantined_orders"]
    assert reasons["reasons"].str.len().gt(0).all()
    known_rules = set(clean.QUARANTINE_RULES)
    for value in reasons["reasons"]:
        assert set(value.split(";")) <= known_rules, value


def test_clean_tables_are_internally_consistent(small_env):
    conn = db.connect(small_env.clean)
    try:
        orphan_items = conn.execute(
            "SELECT COUNT(*) AS n FROM order_items i LEFT JOIN orders o ON o.order_id = i.order_id WHERE o.order_id IS NULL"
        ).fetchone()["n"]
        orphan_users = conn.execute(
            "SELECT COUNT(*) AS n FROM orders o LEFT JOIN users u ON u.customer_id = o.customer_id WHERE u.customer_id IS NULL"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert orphan_items == 0
    assert orphan_users == 0
