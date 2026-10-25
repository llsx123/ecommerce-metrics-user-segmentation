"""Synthetic e-commerce dataset generator.

The dataset follows the shape of the public Olist Brazilian e-commerce schema but
contains **no real customer data**: every identifier, timestamp and amount is
sampled from a seeded RNG. Generated anomalies are injected on purpose so that the
data-quality layer has something real to detect; the injected counts are returned
as a manifest and asserted by the test-suite.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import DataConfig

CATEGORY_WEIGHTS: dict[str, float] = {
    "bed_bath_table": 0.12,
    "health_beauty": 0.10,
    "sports_leisure": 0.09,
    "furniture_decor": 0.09,
    "computers_accessories": 0.08,
    "housewares": 0.07,
    "watches_gifts": 0.06,
    "telephony": 0.05,
    "garden_tools": 0.05,
    "auto": 0.04,
    "toys": 0.04,
    "cool_stuff": 0.04,
    "perfumery": 0.03,
    "baby": 0.03,
    "electronics": 0.03,
    "stationery": 0.02,
    "fashion_bags_accessories": 0.02,
    "pet_shop": 0.02,
    "office_furniture": 0.01,
    "books_general_interest": 0.01,
}

STATE_WEIGHTS: dict[str, float] = {
    "SP": 0.42, "RJ": 0.13, "MG": 0.12, "RS": 0.05, "PR": 0.05, "SC": 0.04,
    "BA": 0.04, "DF": 0.02, "GO": 0.02, "ES": 0.02, "PE": 0.02, "CE": 0.02,
    "other": 0.03,
}

STATUSES = ("delivered", "shipped", "canceled", "unavailable")
STATUS_PROBS = (0.92, 0.04, 0.025, 0.015)
PAYMENT_TYPES = ("credit_card", "boleto", "voucher", "debit_card")
PAYMENT_PROBS = (0.72, 0.18, 0.07, 0.03)

MONTH_SEASONALITY = (0.95, 0.90, 0.95, 0.95, 1.00, 1.00, 1.00, 1.05, 1.05, 1.10, 1.80, 1.45)


def _users(cfg: DataConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_users
    customer_ids = [f"C{i:06d}" for i in range(1, n + 1)]
    unique_ids = [f"U{i:06d}" for i in rng.permutation(n)]
    states = list(STATE_WEIGHTS)
    state_probs = np.array([STATE_WEIGHTS[s] for s in states], dtype=float)
    state_probs = state_probs / state_probs.sum()
    cities = [f"city_{i:02d}" for i in range(1, 41)]
    start = pd.Timestamp(cfg.start_date) - pd.Timedelta(days=365)
    signup = start + pd.to_timedelta(rng.integers(0, 365, size=n), unit="D")

    return pd.DataFrame(
        {
            "customer_id": customer_ids,
            "customer_unique_id": unique_ids,
            "zip_code_prefix": [f"{int(z):05d}" for z in rng.integers(1000, 99999, size=n)],
            "city": rng.choice(cities, size=n),
            "state": rng.choice(states, size=n, p=state_probs),
            "signup_date": signup.strftime("%Y-%m-%d"),
        }
    )


def _products(cfg: DataConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_products
    categories = list(CATEGORY_WEIGHTS)
    cat_probs = np.array([CATEGORY_WEIGHTS[c] for c in categories], dtype=float)
    cat_probs = cat_probs / cat_probs.sum()
    # Popularity within a category is heavy-tailed; price is log-normal per category.
    base_price = rng.lognormal(mean=4.3, sigma=0.55, size=n).round(2)

    return pd.DataFrame(
        {
            "product_id": [f"P{i:06d}" for i in range(1, n + 1)],
            "category": rng.choice(categories, size=n, p=cat_probs),
            "price": np.clip(base_price, 5.0, 4000.0).round(2),
            "weight_g": rng.integers(100, 30000, size=n),
        }
    )


def _order_dates(cfg: DataConfig, rng: np.random.Generator, size: int) -> np.ndarray:
    dates = pd.date_range(cfg.start_date, cfg.end_date, freq="D")
    month_w = np.array([MONTH_SEASONALITY[d.month - 1] for d in dates])
    weekend_w = np.where(dates.day_of_week >= 5, 1.15, 1.0)
    weights = (month_w * weekend_w) / (month_w * weekend_w).sum()
    return rng.choice(dates, size=size, p=weights)


def _orders(cfg: DataConfig, rng: np.random.Generator, users: pd.DataFrame) -> pd.DataFrame:
    n = len(users)
    orders_per_user = rng.choice([1, 2, 3, 4, 5, 7], size=n, p=[0.55, 0.22, 0.11, 0.06, 0.04, 0.02])
    user_pos = np.repeat(np.arange(n), orders_per_user)
    total = user_pos.size

    dates = _order_dates(cfg, rng, total)
    seconds = rng.integers(8 * 3600, 22 * 3600, size=total)
    purchase = pd.to_datetime(dates) + pd.to_timedelta(seconds, unit="s")

    status = rng.choice(STATUSES, size=total, p=STATUS_PROBS)
    is_delivered = status == "delivered"
    delivery_days = rng.integers(2, 13, size=total)
    delivered = np.where(is_delivered, (purchase + pd.to_timedelta(delivery_days, unit="D")).astype(str), None)
    estimated = (purchase + pd.to_timedelta(rng.integers(7, 26, size=total), unit="D")).astype(str)

    order_ids = [f"O{i:08d}" for i in range(1, total + 1)]
    # Shuffle so that order ids do not leak the generation order.
    order_ids = list(np.array(order_ids)[rng.permutation(total)])

    return pd.DataFrame(
        {
            "order_id": order_ids,
            "customer_id": users["customer_id"].to_numpy()[user_pos],
            "order_status": status,
            "purchase_ts": purchase.astype(str),
            "delivered_ts": delivered,
            "estimated_ts": estimated,
        }
    )


def _transactions(
    cfg: DataConfig,
    rng: np.random.Generator,
    orders: pd.DataFrame,
    products: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n_orders = len(orders)
    cat_pop = np.array([CATEGORY_WEIGHTS[c] for c in products["category"]], dtype=float)
    prod_weights = (cat_pop / cat_pop.sum()) * rng.uniform(0.5, 1.5, size=len(products))
    prod_weights = prod_weights / prod_weights.sum()

    prices = products["price"].to_numpy()
    product_ids = products["product_id"].to_numpy()

    item_rows: list[dict[str, Any]] = []
    payment_rows: list[dict[str, Any]] = []
    refund_rows: list[dict[str, Any]] = []
    items_per_order = rng.choice([1, 2, 3], size=n_orders, p=[0.72, 0.22, 0.06])
    order_totals = np.zeros(n_orders)

    for pos in range(n_orders):
        k = int(items_per_order[pos])
        picks = rng.choice(len(products), size=k, replace=False, p=prod_weights)
        order_id = orders["order_id"].iat[pos]
        order_total = 0.0
        for item_pos, prod_pos in enumerate(picks):
            unit = round(float(prices[prod_pos]) * float(rng.uniform(0.9, 1.1)), 2)
            freight = 0.0 if rng.random() < 0.35 else round(float(rng.uniform(5, 25)), 2)
            item_rows.append(
                {
                    "order_id": order_id,
                    "order_item_id": item_pos + 1,
                    "product_id": product_ids[prod_pos],
                    "price": unit,
                    "freight_value": freight,
                }
            )
            order_total += unit + freight
        order_total = round(order_total, 2)
        order_totals[pos] = order_total

        # One or two payment rows; the last one absorbs the rounding remainder so
        # that the base data always reconciles to the cent.
        splits = 1 if rng.random() < 0.8 else 2
        if splits == 1:
            amounts = [order_total]
            types = [str(rng.choice(PAYMENT_TYPES, p=PAYMENT_PROBS))]
        else:
            first = round(order_total * float(rng.uniform(0.3, 0.7)), 2)
            amounts = [first, round(order_total - first, 2)]
            types = [str(rng.choice(PAYMENT_TYPES, p=PAYMENT_PROBS)) for _ in range(2)]
        for seq, (amount, ptype) in enumerate(zip(amounts, types), start=1):
            payment_rows.append(
                {
                    "order_id": order_id,
                    "payment_seq": seq,
                    "payment_type": ptype,
                    "payment_value": round(float(amount), 2),
                }
            )

    pay_df = pd.DataFrame(payment_rows)
    order_by_id = orders.set_index("order_id")

    for pos in range(n_orders):
        if order_by_id["order_status"].iat[pos] != "delivered":
            continue
        if rng.random() >= 0.04:
            continue
        total = float(order_totals[pos])
        if total <= 0:
            continue
        share = 1.0 if rng.random() < 0.3 else float(rng.uniform(0.1, 0.8))
        refund_rows.append(
            {
                "order_id": orders["order_id"].iat[pos],
                "refund_ts": orders["purchase_ts"].iat[pos],
                "refund_value": round(total * share, 2),
                "reason": str(rng.choice(["return", "damaged", "late_delivery", "goodwill"])),
            }
        )

    return (
        pd.DataFrame(item_rows),
        pay_df,
        pd.DataFrame(refund_rows),
    )


def _inject_anomalies(
    tables: dict[str, pd.DataFrame],
    rng: np.random.Generator,
    snapshot: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Inject known, non-overlapping defects and return the exact injected counts.

    Every defect type uses its own set of orders/users so the detected counts must
    match the manifest one-for-one (asserted in ``tests/test_quality.py``).
    """
    users = tables["users"].copy()
    orders = tables["orders"].copy()
    items = tables["order_items"].copy()
    payments = tables["payments"].copy()
    refunds = tables["refunds"].copy()

    orders = orders.sample(frac=1.0, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)

    manifest = {
        "duplicate_users": 5,
        "duplicate_order_items": 6,
        "missing_customer_id": 3,
        "orphan_order_customer": 4,
        "orphan_item_product": 4,
        "negative_item_price": 5,
        "payment_mismatch_orders": 8,
        "refund_exceeds_payment": 3,
        "future_dated_orders": 4,
        "orders_without_payment": 4,
    }

    used_orders: set[str] = set()

    def take_orders(count: int) -> list[str]:
        picked: list[str] = []
        for order_id in orders["order_id"]:
            if len(picked) == count:
                break
            if order_id in used_orders:
                continue
            picked.append(order_id)
            used_orders.add(order_id)
        return picked

    # 1-2. duplicate business keys
    dup_users = users.sample(manifest["duplicate_users"], random_state=11)
    users = pd.concat([users, dup_users], ignore_index=True)

    dup_item_rows = items.sample(manifest["duplicate_order_items"], random_state=12)
    used_orders.update(dup_item_rows["order_id"].tolist())
    items = pd.concat([items, dup_item_rows], ignore_index=True)

    # 3. orders without a customer
    null_orders = take_orders(manifest["missing_customer_id"])
    orders.loc[orders["order_id"].isin(null_orders), "customer_id"] = None

    # 4. orders pointing at a non-existent customer
    orphan_orders = take_orders(manifest["orphan_order_customer"])
    orders.loc[orders["order_id"].isin(orphan_orders), "customer_id"] = "C_ORPHAN"

    # 5. items pointing at a non-existent product
    orphan_item_orders = take_orders(manifest["orphan_item_product"])
    for idx, order_id in enumerate(orphan_item_orders):
        mask = (items["order_id"] == order_id) & (items["order_item_id"] == 1)
        if mask.any():
            items.loc[mask, "product_id"] = f"P_ORPHAN_{idx}"
        else:
            items.loc[items["order_id"] == order_id, "product_id"] = f"P_ORPHAN_{idx}"

    # 6. negative item price
    negative_orders = take_orders(manifest["negative_item_price"])
    for idx, order_id in enumerate(negative_orders):
        mask = (items["order_id"] == order_id) & (items["order_item_id"] == 1)
        items.loc[mask, "price"] = -abs(float(items.loc[mask, "price"].iloc[0]))

    # 7. payment totals that do not reconcile with item totals
    mismatch_orders = take_orders(manifest["payment_mismatch_orders"])
    for order_id in mismatch_orders:
        mask = (payments["order_id"] == order_id) & (payments["payment_seq"] == 1)
        payments.loc[mask, "payment_value"] = (payments.loc[mask, "payment_value"] + 5.0).round(2)

    # 8. refund larger than the payment total
    refund_orders = take_orders(manifest["refund_exceeds_payment"])
    extra_refunds = []
    for order_id in refund_orders:
        paid = float(payments.loc[payments["order_id"] == order_id, "payment_value"].sum())
        extra_refunds.append(
            {
                "order_id": order_id,
                "refund_ts": str(snapshot),
                "refund_value": round(paid + 10.0, 2),
                "reason": "chargeback",
            }
        )
    refunds = pd.concat([refunds, pd.DataFrame(extra_refunds)], ignore_index=True)

    # 9. purchases dated after the snapshot
    future_orders = take_orders(manifest["future_dated_orders"])
    future_ts = (snapshot + pd.Timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    orders.loc[orders["order_id"].isin(future_orders), "purchase_ts"] = future_ts

    # 10. orders without any payment row
    unpaid_orders = take_orders(manifest["orders_without_payment"])
    payments = payments[~payments["order_id"].isin(unpaid_orders)]

    tables = {
        "users": users,
        "products": tables["products"],
        "orders": orders,
        "order_items": items,
        "payments": payments,
        "refunds": refunds,
    }
    return tables, manifest


def generate_dataset(cfg: DataConfig | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Generate the synthetic dataset and the manifest of injected defects."""
    cfg = cfg or DataConfig()
    rng = np.random.default_rng(cfg.seed)

    users = _users(cfg, rng)
    products = _products(cfg, rng)
    orders = _orders(cfg, rng, users)
    items, payments, refunds = _transactions(cfg, rng, orders, products)

    snapshot = pd.to_datetime(orders["purchase_ts"]).max()
    tables, manifest = _inject_anomalies(
        {"users": users, "products": products, "orders": orders,
         "order_items": items, "payments": payments, "refunds": refunds},
        rng,
        snapshot,
    )
    return tables, manifest
