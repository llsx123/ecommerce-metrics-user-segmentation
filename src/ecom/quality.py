"""Data-quality checks executed against the raw (staging) database.

Every check returns the rows that violate one rule. The injected-defect manifest
produced by :mod:`ecom.generate` is asserted against these counts in the
test-suite, so a check that silently stops working breaks the build.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from .config import VALID_STATUSES


@dataclass(frozen=True)
class Check:
    name: str
    table: str
    severity: str
    description: str
    sql: str


_STATUS_LIST = ", ".join(f"'{s}'" for s in VALID_STATUSES)

CHECKS: tuple[Check, ...] = (
    Check(
        "duplicate_users",
        "users",
        "high",
        "customer_id must be unique (duplicate rows in the customer master).",
        "SELECT customer_id AS key FROM users GROUP BY customer_id HAVING COUNT(*) > 1",
    ),
    Check(
        "duplicate_order_items",
        "order_items",
        "high",
        "(order_id, order_item_id) must be unique (duplicated line items double-count revenue).",
        """
        SELECT order_id || '#' || order_item_id AS key
        FROM order_items
        GROUP BY order_id, order_item_id
        HAVING COUNT(*) > 1
        """,
    ),
    Check(
        "missing_customer_id",
        "orders",
        "high",
        "Every order must reference a customer.",
        "SELECT order_id AS key FROM orders WHERE customer_id IS NULL OR TRIM(customer_id) = ''",
    ),
    Check(
        "orphan_order_customer",
        "orders",
        "high",
        "order.customer_id must exist in the customer master.",
        """
        SELECT o.order_id AS key
        FROM orders o
        LEFT JOIN users u ON u.customer_id = o.customer_id
        WHERE o.customer_id IS NOT NULL AND u.customer_id IS NULL
        """,
    ),
    Check(
        "orphan_item_product",
        "order_items",
        "high",
        "order_items.product_id must exist in the product master.",
        """
        SELECT i.order_id || '#' || i.order_item_id AS key
        FROM order_items i
        LEFT JOIN products p ON p.product_id = i.product_id
        WHERE p.product_id IS NULL
        """,
    ),
    Check(
        "negative_item_price",
        "order_items",
        "high",
        "Line-item price and freight must be non-negative.",
        "SELECT order_id || '#' || order_item_id AS key FROM order_items WHERE price < 0 OR freight_value < 0",
    ),
    Check(
        "payment_mismatch_orders",
        "payments",
        "medium",
        "Payments must reconcile with item + freight totals (orders with corrupted line items excluded).",
        """
        WITH item_totals AS (
            SELECT i.order_id, SUM(i.price + i.freight_value) AS item_total
            FROM order_items i
            GROUP BY i.order_id
            HAVING SUM(CASE WHEN i.price < 0 THEN 1 ELSE 0 END) = 0
        ),
        pay_totals AS (
            SELECT order_id, SUM(payment_value) AS pay_total
            FROM payments
            GROUP BY order_id
        )
        SELECT o.order_id AS key
        FROM orders o
        JOIN item_totals it ON it.order_id = o.order_id
        JOIN pay_totals pt ON pt.order_id = o.order_id
        WHERE ABS(pt.pay_total - it.item_total) > 0.01
          AND o.order_id NOT IN (
              SELECT order_id FROM order_items
              GROUP BY order_id, order_item_id HAVING COUNT(*) > 1
          )
        """,
    ),
    Check(
        "refund_exceeds_payment",
        "refunds",
        "high",
        "A refund can never exceed the amount actually paid for the order.",
        """
        WITH pay AS (SELECT order_id, SUM(payment_value) AS paid FROM payments GROUP BY order_id),
             ref AS (SELECT order_id, SUM(refund_value) AS refunded FROM refunds GROUP BY order_id)
        SELECT ref.order_id AS key
        FROM ref JOIN pay ON pay.order_id = ref.order_id
        WHERE ref.refunded - pay.paid > 0.01
        """,
    ),
    Check(
        "future_dated_orders",
        "orders",
        "high",
        "purchase_ts must not be later than the analysis snapshot.",
        "SELECT order_id AS key FROM orders WHERE purchase_ts > :snapshot",
    ),
    Check(
        "orders_without_payment",
        "orders",
        "high",
        "A revenue-generating order must have at least one payment row.",
        f"""
        SELECT o.order_id AS key
        FROM orders o
        WHERE o.order_status IN ({_STATUS_LIST})
          AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
        """,
    ),
)


def run_checks(conn: sqlite3.Connection, snapshot: str) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Run every check; return a findings table and the offending keys per check."""
    findings: list[dict] = []
    details: dict[str, list[str]] = {}
    for check in CHECKS:
        rows = conn.execute(check.sql, {"snapshot": snapshot}).fetchall()
        keys = [str(r["key"]) for r in rows]
        details[check.name] = keys
        findings.append(
            {
                "check": check.name,
                "table": check.table,
                "severity": check.severity,
                "rows": len(keys),
                "description": check.description,
            }
        )
    return pd.DataFrame(findings), details


def findings_by_check(findings: pd.DataFrame) -> dict[str, int]:
    return dict(zip(findings["check"], findings["rows"].astype(int)))
