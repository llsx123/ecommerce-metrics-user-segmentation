"""Hand-computed expectations on a 5-customer, 6-order dataset.

These numbers are derived by hand (see the docstring in ``conftest.tiny_db``) and
are deliberately independent from the generator: they prove that the metric
definitions exclude the cancelled order, net out the partial refund, count a
repeat customer only once and use the right denominators.
"""

from __future__ import annotations

import pytest

from conftest import TINY_SNAPSHOT

from ecom import db, metrics, pandas_metrics

EXPECTED_GROSS = 435.00
EXPECTED_REFUND = 5.00
EXPECTED_NET = 430.00
EXPECTED_ORDERS = 5
EXPECTED_USERS = 4


@pytest.fixture(scope="module")
def conn(tiny_db):
    connection = db.connect(tiny_db)
    yield connection
    connection.close()


def test_overall_metrics_exact(conn):
    result = metrics.overall(conn, TINY_SNAPSHOT)
    assert result["gross_gmv"] == pytest.approx(EXPECTED_GROSS)
    assert result["refund_amount"] == pytest.approx(EXPECTED_REFUND)
    assert result["net_gmv"] == pytest.approx(EXPECTED_NET)
    assert int(result["paid_orders"]) == EXPECTED_ORDERS
    assert int(result["paid_users"]) == EXPECTED_USERS
    assert int(result["repeat_users"]) == 1
    assert result["repeat_rate"] == pytest.approx(0.25)
    assert result["aov"] == pytest.approx(86.0)
    assert result["arpu"] == pytest.approx(107.5)
    assert result["refund_rate"] == pytest.approx(5 / 435, abs=1e-4)


def test_pandas_matches_hand_computed_values(conn):
    result = pandas_metrics.overall(conn, TINY_SNAPSHOT)
    assert result["gross_gmv"] == pytest.approx(EXPECTED_GROSS)
    assert result["net_gmv"] == pytest.approx(EXPECTED_NET)
    assert result["paid_orders"] == EXPECTED_ORDERS
    assert result["paid_users"] == EXPECTED_USERS
    assert result["repeat_rate"] == pytest.approx(0.25)
    assert result["aov"] == pytest.approx(86.0)


def test_cancelled_order_is_excluded(conn):
    """o4 (30.00, cancelled) must not leak into revenue or order counts."""
    result = metrics.overall(conn, TINY_SNAPSHOT)
    assert result["gross_gmv"] == pytest.approx(EXPECTED_GROSS)
    assert int(result["paid_orders"]) == EXPECTED_ORDERS


def test_refund_is_netted_out(conn):
    """o5 paid 65.00 and refunded 5.00 -> contributes 60.00 of net revenue."""
    result = metrics.overall(conn, TINY_SNAPSHOT)
    assert result["net_gmv"] == pytest.approx(EXPECTED_GROSS - EXPECTED_REFUND)
    assert result["refund_amount"] == pytest.approx(EXPECTED_REFUND)


def test_user_level_metrics(conn):
    users = metrics.users(conn, TINY_SNAPSHOT).set_index("customer_id")
    assert set(users.index) == {"c1", "c2", "c4", "c5"}
    assert users.loc["c1", "frequency"] == 2
    assert users.loc["c1", "monetary"] == pytest.approx(210.0)
    assert users.loc["c1", "recency_days"] == 51
    assert users.loc["c2", "recency_days"] == 31
    assert users.loc["c5", "monetary"] == pytest.approx(40.0)


def test_monthly_split(conn):
    monthly = metrics.monthly(conn, TINY_SNAPSHOT).set_index("month")
    assert monthly.loc["2024-01", "net_gmv"] == pytest.approx(110.0)
    assert monthly.loc["2024-02", "net_gmv"] == pytest.approx(100.0)
    assert monthly.loc["2024-03", "net_gmv"] == pytest.approx(220.0)  # 120 + 60 + 40
    assert monthly.loc["2024-03", "paid_orders"] == 3


def test_category_gmv_and_orders(conn):
    category = metrics.category(conn, TINY_SNAPSHOT).set_index("category")
    assert category.loc["cat_a", "item_gmv"] == pytest.approx(260.0)  # 100 + 100 + 60
    assert category.loc["cat_b", "item_gmv"] == pytest.approx(140.0)  # 50 + 50 + 40
    assert category.loc["cat_a", "paid_orders"] == 3
    assert category.loc["cat_b", "gmv_rank"] == 2


def test_repeat_intervals(conn):
    result = metrics.repeat_intervals(conn, TINY_SNAPSHOT)
    assert int(result["repeat_intervals"]) == 1
    assert int(result["repeat_customers"]) == 1
    assert result["avg_days_between_orders"] == pytest.approx(31.0)


def test_snapshot_parameter_is_respected(conn):
    """Moving the snapshot forward drops no orders here, but recency must change."""
    early = metrics.users(conn, "2024-03-01 23:59:59").set_index("customer_id")
    late = metrics.users(conn, TINY_SNAPSHOT).set_index("customer_id")
    assert early.loc["c1", "recency_days"] == 20
    assert late.loc["c1", "recency_days"] == 51
