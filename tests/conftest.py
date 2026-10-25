"""Shared fixtures: a hand-crafted tiny dataset and a generated small dataset."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ecom import clean, config, db, generate  # noqa: E402
from ecom.config import SmallDataConfig  # noqa: E402

TINY_SNAPSHOT = "2024-04-01 23:59:59"


@pytest.fixture(scope="session")
def tiny_db(tmp_path_factory) -> Path:
    """A 5-user, 6-order dataset with hand-computable expected metrics.

    o4 is cancelled (must be excluded), o5 is partially refunded (5.00), o1/o2
    belong to the same customer (one repeat customer).
    """
    tables = {
        "users": pd.DataFrame(
            {
                "customer_id": ["c1", "c2", "c3", "c4", "c5"],
                "customer_unique_id": ["u1", "u2", "u3", "u4", "u5"],
                "zip_code_prefix": ["01000"] * 5,
                "city": ["x"] * 5,
                "state": ["SP"] * 5,
                "signup_date": ["2023-01-01"] * 5,
            }
        ),
        "products": pd.DataFrame(
            {
                "product_id": ["p1", "p2"],
                "category": ["cat_a", "cat_b"],
                "price": [10.0, 20.0],
                "weight_g": [100, 200],
            }
        ),
        "orders": pd.DataFrame(
            {
                "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
                "customer_id": ["c1", "c1", "c2", "c3", "c4", "c5"],
                "order_status": ["delivered", "delivered", "delivered", "canceled", "delivered", "delivered"],
                "purchase_ts": [
                    "2024-01-10 10:00:00",
                    "2024-02-10 10:00:00",
                    "2024-03-01 10:00:00",
                    "2024-03-05 10:00:00",
                    "2024-03-10 10:00:00",
                    "2024-03-20 10:00:00",
                ],
                "delivered_ts": [
                    "2024-01-15 10:00:00",
                    "2024-02-15 10:00:00",
                    "2024-03-06 10:00:00",
                    None,
                    "2024-03-15 10:00:00",
                    "2024-03-25 10:00:00",
                ],
                "estimated_ts": ["2024-01-20 10:00:00"] * 6,
            }
        ),
        "order_items": pd.DataFrame(
            {
                "order_id": ["o1", "o2", "o3", "o3", "o4", "o5", "o6"],
                "order_item_id": [1, 1, 1, 2, 1, 1, 1],
                "product_id": ["p1", "p1", "p2", "p2", "p1", "p1", "p2"],
                "price": [100.0, 100.0, 50.0, 50.0, 30.0, 60.0, 40.0],
                "freight_value": [10.0, 0.0, 20.0, 0.0, 0.0, 5.0, 0.0],
            }
        ),
        "payments": pd.DataFrame(
            {
                "order_id": ["o1", "o2", "o3", "o4", "o5", "o5", "o6"],
                "payment_seq": [1, 1, 1, 1, 1, 2, 1],
                "payment_type": ["credit_card"] * 7,
                "payment_value": [110.0, 100.0, 120.0, 30.0, 50.0, 15.0, 40.0],
            }
        ),
        "refunds": pd.DataFrame(
            {
                "order_id": ["o5"],
                "refund_ts": ["2024-03-12 10:00:00"],
                "refund_value": [5.0],
                "reason": ["return"],
            }
        ),
    }

    path = tmp_path_factory.mktemp("tiny") / "tiny.db"
    raw = db.build_database(tables, path.parent / "tiny_raw.db", config.SQL_DIR / "schema.sql")
    clean_db = path.parent / "tiny_clean.db"
    clean.build_clean_database(raw, clean_db, TINY_SNAPSHOT)
    return clean_db


@pytest.fixture(scope="session")
def small_env(tmp_path_factory) -> SimpleNamespace:
    """Generated dataset (400 users) pushed through the real cleaning pipeline."""
    cfg = SmallDataConfig()
    tables, manifest = generate.generate_dataset(cfg)
    base = tmp_path_factory.mktemp("small")
    raw = db.build_database(tables, base / "raw.db", config.SQL_DIR / "schema.sql")
    clean_db = base / "clean.db"
    _, stats = clean.build_clean_database(raw, clean_db, cfg.snapshot)
    return SimpleNamespace(
        cfg=cfg,
        snapshot=cfg.snapshot,
        raw=raw,
        clean=clean_db,
        manifest=manifest,
        tables=tables,
        stats=stats,
    )
