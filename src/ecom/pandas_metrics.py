"""Pandas re-implementation of the metric layer, used to cross-validate the SQL.

Both layers read the *same* cleaned database and apply the *same* definitions, so
any divergence is a real bug in one of the two implementations rather than a data
difference. Comparisons live in :mod:`ecom.reconcile`.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .config import VALID_STATUSES


def load_orders(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM orders", conn)


def load_payments(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT order_id, SUM(payment_value) AS gross FROM payments GROUP BY order_id", conn)


def load_refunds(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT order_id, SUM(refund_value) AS refunded FROM refunds GROUP BY order_id", conn)


def order_econ(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    """Order-level revenue frame: gross, refunded and net revenue per valid order."""
    orders = load_orders(conn)
    payments = load_payments(conn)
    refunds = load_refunds(conn)

    valid = orders[orders["order_status"].isin(VALID_STATUSES)]
    valid = valid[valid["purchase_ts"] <= snapshot]
    valid = valid[valid["order_id"].isin(set(payments["order_id"]))]

    econ = valid.merge(payments, on="order_id", how="inner").merge(refunds, on="order_id", how="left")
    econ["refunded"] = econ["refunded"].fillna(0.0)
    econ["net"] = econ["gross"] - econ["refunded"]
    return econ.reset_index(drop=True)


def overall(conn: sqlite3.Connection, snapshot: str) -> dict[str, float]:
    econ = order_econ(conn, snapshot)
    per_user = econ.groupby("customer_id")["order_id"].count()
    paid_orders = int(len(econ))
    paid_users = int(per_user.size)
    gross = float(econ["gross"].sum())
    refunded = float(econ["refunded"].sum())
    net = float(econ["net"].sum())
    repeat_users = int((per_user >= 2).sum())
    return {
        "gross_gmv": round(gross, 2),
        "refund_amount": round(refunded, 2),
        "net_gmv": round(net, 2),
        "paid_orders": paid_orders,
        "paid_users": paid_users,
        "repeat_users": repeat_users,
        "repeat_rate": round(repeat_users / paid_users, 4),
        "aov": round(net / paid_orders, 2),
        "arpu": round(net / paid_users, 2),
        "refund_rate": round(refunded / gross, 4),
    }


def monthly(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    econ = order_econ(conn, snapshot)
    econ["month"] = econ["purchase_ts"].str.slice(0, 7)
    grouped = econ.groupby("month").agg(
        paid_orders=("order_id", "count"),
        paid_users=("customer_id", "nunique"),
        gross_gmv=("gross", "sum"),
        refund_amount=("refunded", "sum"),
        net_gmv=("net", "sum"),
    )
    grouped["aov"] = grouped["net_gmv"] / grouped["paid_orders"]
    grouped["arpu"] = grouped["net_gmv"] / grouped["paid_users"]
    grouped["refund_rate"] = grouped["refund_amount"] / grouped["gross_gmv"]
    grouped["prev_net_gmv"] = grouped["net_gmv"].shift(1)
    grouped["mom_growth"] = (grouped["net_gmv"] - grouped["prev_net_gmv"]) / grouped["prev_net_gmv"]

    grouped = grouped.reset_index()
    for col in ("gross_gmv", "refund_amount", "net_gmv", "prev_net_gmv"):
        grouped[col] = grouped[col].round(2)
    grouped["aov"] = grouped["aov"].round(2)
    grouped["arpu"] = grouped["arpu"].round(2)
    grouped["refund_rate"] = grouped["refund_rate"].round(4)
    grouped["mom_growth"] = grouped["mom_growth"].round(4)
    return grouped


def category(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    items = pd.read_sql_query(
        """
        SELECT i.order_id, i.price, i.freight_value, p.category
        FROM order_items i JOIN products p ON p.product_id = i.product_id
        """,
        conn,
    )
    econ = order_econ(conn, snapshot)[["order_id"]]
    items = items[items["order_id"].isin(set(econ["order_id"]))]

    grouped = items.groupby("category").agg(
        item_gmv=("price", "sum"),
        freight_revenue=("freight_value", "sum"),
        paid_orders=("order_id", "nunique"),
    )
    grouped = grouped.sort_values("item_gmv", ascending=False).reset_index()
    grouped["category_aov"] = (grouped["item_gmv"] / grouped["paid_orders"]).round(2)
    grouped["gmv_rank"] = range(1, len(grouped) + 1)
    grouped["gmv_share"] = (grouped["item_gmv"] / grouped["item_gmv"].sum()).round(4)
    grouped["cumulative_share"] = (grouped["item_gmv"].cumsum() / grouped["item_gmv"].sum()).round(4)
    grouped["item_gmv"] = grouped["item_gmv"].round(2)
    grouped["freight_revenue"] = grouped["freight_revenue"].round(2)
    return grouped


def users(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    econ = order_econ(conn, snapshot)
    grouped = econ.groupby("customer_id").agg(
        last_purchase_ts=("purchase_ts", "max"),
        frequency=("order_id", "count"),
        monetary=("net", "sum"),
    )
    grouped["monetary"] = grouped["monetary"].round(2)
    snapshot_ts = pd.Timestamp(snapshot)
    grouped["recency_days"] = (snapshot_ts - pd.to_datetime(grouped["last_purchase_ts"])).dt.days
    grouped = grouped.reset_index()
    return grouped.sort_values("monetary", ascending=False).reset_index(drop=True)


def payment_mix(conn: sqlite3.Connection, snapshot: str) -> pd.DataFrame:
    """Payment value by payment type, restricted to valid orders."""
    econ = order_econ(conn, snapshot)[["order_id"]]
    payments = pd.read_sql_query(
        "SELECT order_id, payment_type, payment_value FROM payments", conn
    )
    payments = payments[payments["order_id"].isin(set(econ["order_id"]))]
    grouped = payments.groupby("payment_type")["payment_value"].sum().round(2).reset_index()
    return grouped.sort_values("payment_value", ascending=False).reset_index(drop=True)


def repeat_intervals(conn: sqlite3.Connection, snapshot: str) -> dict[str, float]:
    econ = order_econ(conn, snapshot)
    ordered = econ.sort_values(["customer_id", "purchase_ts", "order_id"])
    previous = ordered.groupby("customer_id")["purchase_ts"].shift(1)
    delta_days = (pd.to_datetime(ordered["purchase_ts"]) - pd.to_datetime(previous)).dt.total_seconds() / 86400.0
    intervals = delta_days.dropna()
    if intervals.empty:
        return {
            "avg_days_between_orders": float("nan"),
            "repeat_intervals": 0,
            "repeat_customers": 0,
            "min_days": float("nan"),
            "max_days": float("nan"),
        }
    return {
        "avg_days_between_orders": float(np.round(intervals.mean(), 3)),
        "repeat_intervals": int(intervals.size),
        "repeat_customers": int(ordered.loc[intervals.index, "customer_id"].nunique()),
        "min_days": float(np.round(intervals.min(), 3)),
        "max_days": float(np.round(intervals.max(), 3)),
    }
