"""Quarantine defective orders and materialise the cleaned, strictly-typed database.

Design choice
-------------
An order is quarantined **as a whole** when any of its line items cannot be
trusted (negative price, orphan product, duplicated line) instead of dropping the
single line. Dropping one line would silently change the order total and leave a
payment mismatch behind, so whole-order quarantine keeps every surviving order
internally consistent and auditable. Quarantined orders are listed with a reason
and are excluded from every revenue metric.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from . import db
from .config import VALID_STATUSES, SQL_DIR

_STATUS_LIST = ", ".join(f"'{s}'" for s in VALID_STATUSES)

QUARANTINE_RULES: dict[str, str] = {
    "null_customer": "SELECT order_id FROM orders WHERE customer_id IS NULL OR TRIM(customer_id) = ''",
    "orphan_customer": """
        SELECT o.order_id FROM orders o
        LEFT JOIN users u ON u.customer_id = o.customer_id
        WHERE o.customer_id IS NOT NULL AND u.customer_id IS NULL
    """,
    "future_dated": "SELECT order_id FROM orders WHERE purchase_ts > :snapshot",
    "unpaid": f"""
        SELECT o.order_id FROM orders o
        WHERE o.order_status IN ({_STATUS_LIST})
          AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
    """,
    "bad_line_items": """
        SELECT DISTINCT i.order_id FROM order_items i
        LEFT JOIN products p ON p.product_id = i.product_id
        WHERE p.product_id IS NULL OR i.price < 0 OR i.freight_value < 0
        UNION
        SELECT order_id FROM order_items GROUP BY order_id, order_item_id HAVING COUNT(*) > 1
    """,
    "unreconciled_payment": """
        SELECT o.order_id FROM orders o
        WHERE EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
          AND ABS(
                (SELECT SUM(payment_value) FROM payments p WHERE p.order_id = o.order_id)
              - (SELECT SUM(price + freight_value) FROM order_items i WHERE i.order_id = o.order_id)
              ) > 0.01
    """,
    "refund_exceeds_payment": """
        SELECT r.order_id FROM refunds r
        GROUP BY r.order_id
        HAVING SUM(r.refund_value) > (
            SELECT COALESCE(SUM(p.payment_value), 0) FROM payments p WHERE p.order_id = r.order_id
        ) + 0.01
    """,
}


def quarantine_reasons(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    """Return ``order_id`` + ``reasons`` for every order that must be quarantined."""
    reasons: dict[str, list[str]] = {}
    for rule, sql in QUARANTINE_RULES.items():
        for row in conn.execute(sql, {"snapshot": snapshot}).fetchall():
            reasons.setdefault(str(row["order_id"]), []).append(rule)
    return pd.DataFrame(
        [{"order_id": oid, "reasons": ";".join(sorted(r))} for oid, r in sorted(reasons.items())],
        columns=["order_id", "reasons"],
    )


def clean_frames(
    tables: dict[str, pd.DataFrame],
    quarantined: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Apply the cleaning rules to in-memory frames and return the clean tables."""
    bad = set(quarantined["order_id"]) if not quarantined.empty else set()

    users = tables["users"].drop_duplicates(subset="customer_id", keep="first")
    users = users[users["customer_unique_id"].notna() & (users["customer_unique_id"].astype(str).str.strip() != "")]
    products = tables["products"].drop_duplicates(subset="product_id", keep="first")

    orders = tables["orders"][~tables["orders"]["order_id"].isin(bad)].copy()
    orders = orders[orders["customer_id"].isin(set(users["customer_id"]))]

    good_orders = set(orders["order_id"])
    items = tables["order_items"]
    items = items[items["order_id"].isin(good_orders)]
    items = items[items["product_id"].isin(set(products["product_id"]))]
    items = items[(items["price"] >= 0) & (items["freight_value"] >= 0)]
    items = items.drop_duplicates(subset=["order_id", "order_item_id"], keep="first")

    payments = tables["payments"]
    payments = payments[payments["order_id"].isin(good_orders)]
    payments = payments.drop_duplicates(subset=["order_id", "payment_seq"], keep="first")

    refunds = tables["refunds"]
    refunds = refunds[refunds["order_id"].isin(good_orders)]

    return {
        "users": users.reset_index(drop=True),
        "products": products.reset_index(drop=True),
        "orders": orders.reset_index(drop=True),
        "order_items": items.reset_index(drop=True),
        "payments": payments.reset_index(drop=True),
        "refunds": refunds.reset_index(drop=True),
    }


def build_clean_database(
    raw_db: Path,
    clean_db: Path,
    snapshot: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Read the raw database, clean it, write the strict database, return stats."""
    conn = db.connect(raw_db)
    try:
        tables = {name: pd.read_sql_query(f'SELECT * FROM "{name}"', conn) for name in db.table_names(conn)}
    finally:
        conn.close()

    reasons_conn = db.connect(raw_db)
    try:
        quarantined = quarantine_reasons(reasons_conn, snapshot)
    finally:
        reasons_conn.close()

    clean = clean_frames(tables, quarantined)
    db.build_database(clean, clean_db, SQL_DIR / "schema_clean.sql")

    stats = {
        "raw_orders": int(len(tables["orders"])),
        "quarantined_orders": int(len(quarantined)),
        "clean_orders": int(len(clean["orders"])),
        "clean_items": int(len(clean["order_items"])),
        "clean_payments": int(len(clean["payments"])),
        "clean_users": int(len(clean["users"])),
    }
    return clean, stats
