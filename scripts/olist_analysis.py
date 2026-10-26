#!/usr/bin/env python
"""Validate the metric layer on the real Kaggle Olist dataset.

Download the nine CSVs from
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
and put at least these files in ``data/olist/``:

    olist_orders_dataset.csv
    olist_customers_dataset.csv
    olist_order_items_dataset.csv
    olist_order_payments_dataset.csv
    olist_products_dataset.csv
    product_category_name_translation.csv

Then run::

    python scripts/olist_analysis.py --data-dir data/olist

It prints the headline metrics and writes ``reports/olist_summary.json``.
The public dataset is unchanged by this script; nothing is downloaded automatically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

VALID_STATUS = ["approved", "invoiced", "processing", "shipped", "delivered"]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "olist_orders_dataset.csv",
    "olist_customers_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_products_dataset.csv",
    "product_category_name_translation.csv",
)


def segment_for(r: int, f: int) -> str:
    if r >= 4 and f >= 4:
        return "champions"
    if r >= 3 and f >= 3:
        return "loyal"
    if r >= 4:
        return "new_promising"
    if r == 3:
        return "need_attention"
    if r == 2 and f >= 3:
        return "at_risk"
    if r == 2:
        return "hibernating"
    if f >= 3:
        return "at_risk"
    return "lost"


def analyze(data_dir: Path) -> dict:
    missing = [name for name in REQUIRED if not (data_dir / name).exists()]
    if missing:
        raise SystemExit(f"missing files in {data_dir}: {missing}")

    orders = pd.read_csv(data_dir / "olist_orders_dataset.csv")
    customers = pd.read_csv(data_dir / "olist_customers_dataset.csv")
    items = pd.read_csv(data_dir / "olist_order_items_dataset.csv")
    payments = pd.read_csv(data_dir / "olist_order_payments_dataset.csv")
    products = pd.read_csv(data_dir / "olist_products_dataset.csv")
    translation = pd.read_csv(data_dir / "product_category_name_translation.csv")

    pay = payments.groupby("order_id", as_index=False)["payment_value"].sum()
    item_total = items.groupby("order_id", as_index=False).agg(
        item_value=("price", "sum"), freight=("freight_value", "sum")
    )
    item_total["order_total"] = item_total["item_value"] + item_total["freight"]

    frame = (
        orders.merge(customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left")
        .merge(pay, on="order_id", how="left")
        .merge(item_total[["order_id", "order_total"]], on="order_id", how="left")
    )
    frame["purchase_ts"] = pd.to_datetime(frame["order_purchase_timestamp"])
    snapshot = frame["purchase_ts"].max()

    dq = {
        "duplicate_orders": int(orders["order_id"].duplicated().sum()),
        "duplicate_order_items": int(items.duplicated(subset=["order_id", "order_item_id"]).sum()),
        "null_customer": int(orders["customer_id"].isna().sum()),
        "orphan_customer": int(frame["customer_unique_id"].isna().sum()),
        "orphan_product_rows": int((~items["product_id"].isin(set(products["product_id"]))).sum()),
        "negative_price_rows": int(((items["price"] < 0) | (items["freight_value"] < 0)).sum()),
        "orders_without_payment": int(frame["payment_value"].isna().sum()),
        "payment_mismatch_orders": int(
            (frame["payment_value"].notna() & frame["order_total"].notna()
             & ((frame["payment_value"] - frame["order_total"]).abs() > 0.01)).sum()
        ),
        "future_dated_orders": int((frame["purchase_ts"] > snapshot).sum()),
    }

    bad: set[str] = set()
    bad |= set(frame.loc[frame["customer_unique_id"].isna(), "order_id"])
    bad |= set(frame.loc[frame["payment_value"].isna(), "order_id"])
    bad |= set(frame.loc[(frame["payment_value"] - frame["order_total"]).abs() > 0.01, "order_id"])
    bad |= set(items.loc[items["price"] < 0, "order_id"])
    bad |= set(items.loc[~items["product_id"].isin(set(products["product_id"])), "order_id"])
    bad |= set(items.loc[items.duplicated(subset=["order_id", "order_item_id"], keep=False), "order_id"])

    frame["valid"] = (
        frame["order_status"].isin(VALID_STATUS)
        & (frame["purchase_ts"] <= snapshot)
        & (~frame["order_id"].isin(bad))
    )
    clean = frame[frame["valid"]].copy()

    per_user = clean.groupby("customer_unique_id").agg(
        orders=("order_id", "count"), last_ts=("purchase_ts", "max"), monetary=("payment_value", "sum")
    )
    paid_users = int(per_user.shape[0])
    repeat_users = int((per_user["orders"] >= 2).sum())

    metrics = {
        "gross_gmv": round(float(clean["payment_value"].sum()), 2),
        "paid_orders": int(clean.shape[0]),
        "paid_users": paid_users,
        "repeat_users": repeat_users,
        "repeat_rate": round(repeat_users / paid_users, 4),
        "aov": round(float(clean["payment_value"].mean()), 2),
        "arpu": round(float(clean["payment_value"].sum() / paid_users), 2),
        "quarantined_orders": len(bad),
        "quarantine_share": round(len(bad) / len(orders), 4),
        "raw_orders": int(len(orders)),
        "raw_order_items": int(len(items)),
    }

    cat = (
        items[items["order_id"].isin(set(clean["order_id"]))]
        .merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
        .merge(translation, on="product_category_name", how="left")
    )
    cat["category"] = cat["product_category_name_english"].fillna(cat["product_category_name"]).fillna("unknown")
    cat_gmv = cat.groupby("category")["price"].sum().sort_values(ascending=False)

    per_user["recency_days"] = (snapshot - per_user["last_ts"]).dt.days
    r_cuts = np.quantile(per_user["recency_days"], [0.2, 0.4, 0.6, 0.8])
    m_cuts = np.quantile(per_user["monetary"], [0.2, 0.4, 0.6, 0.8])
    r_score = np.clip(5 - np.searchsorted(r_cuts, per_user["recency_days"], side="left"), 1, 5)
    m_score = np.clip(np.searchsorted(m_cuts, per_user["monetary"], side="right") + 1, 1, 5)
    f_score = np.minimum(per_user["orders"], 5)
    per_user["segment"] = [segment_for(int(r), int(f)) for r, f in zip(r_score, f_score)]
    segments = (
        per_user.groupby("segment").agg(users=("orders", "size"), gmv=("monetary", "sum"))
        .sort_values("users", ascending=False)
    )
    segments["user_share"] = (segments["users"] / segments["users"].sum()).round(4)

    return {
        "dataset": {
            "source": "Kaggle Brazilian E-Commerce Public Dataset by Olist",
            "snapshot": str(snapshot),
            "date_range": [str(frame["purchase_ts"].min()), str(frame["purchase_ts"].max())],
            "raw_orders": int(len(orders)),
            "raw_order_items": int(len(items)),
            "raw_payments": int(len(payments)),
            "unique_customers": int(customers["customer_unique_id"].nunique()),
            "categories": int(cat_gmv.shape[0]),
        },
        "data_quality": dq,
        "metrics": metrics,
        "top_categories": [{"category": k, "gmv": round(float(v), 2)} for k, v in cat_gmv.head(5).items()],
        "segments": segments.reset_index().round(4).to_dict(orient="records"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "olist")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "olist_summary.json")
    args = parser.parse_args()

    summary = analyze(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2))
    print("written:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
