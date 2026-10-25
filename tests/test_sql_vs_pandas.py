"""SQL vs Pandas must agree on every metric, within the documented tolerances."""

from __future__ import annotations

import pytest

from ecom import db, metrics, pandas_metrics, reconcile, rfm


@pytest.fixture(scope="module")
def conn(small_env):
    connection = db.connect(small_env.clean)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def snapshot(small_env):
    return small_env.snapshot


def test_overall_reconciles(conn, snapshot):
    comparison = reconcile.compare_overall(
        metrics.overall(conn, snapshot), pandas_metrics.overall(conn, snapshot)
    )
    assert comparison["passed"].all(), comparison.to_dict("records")
    assert len(comparison) >= 10


def test_monthly_reconciles(conn, snapshot):
    comparison = reconcile.compare_monthly(
        metrics.monthly(conn, snapshot), pandas_metrics.monthly(conn, snapshot)
    )
    assert comparison.empty, comparison.head(10).to_dict("records")


def test_category_reconciles(conn, snapshot):
    comparison = reconcile.compare_category(
        metrics.category(conn, snapshot), pandas_metrics.category(conn, snapshot)
    )
    assert comparison.empty, comparison.head(10).to_dict("records")


def test_users_reconcile(conn, snapshot):
    comparison = reconcile.compare_users(
        metrics.users(conn, snapshot), pandas_metrics.users(conn, snapshot)
    )
    assert comparison.empty, comparison.head(10).to_dict("records")


def test_repeat_intervals_reconcile(conn, snapshot):
    comparison = reconcile.compare_repeat(
        metrics.repeat_intervals(conn, snapshot), pandas_metrics.repeat_intervals(conn, snapshot)
    )
    assert comparison["passed"].all(), comparison.to_dict("records")


def test_rfm_scores_reconcile(conn, snapshot):
    users_pandas = pandas_metrics.users(conn, snapshot)
    cuts = rfm.cutpoints(users_pandas)
    sql_frame = metrics.rfm(conn, snapshot, cuts)
    scored = rfm.score_users(users_pandas, cuts)
    comparison = reconcile.compare_rfm(sql_frame, scored)
    assert comparison.empty, comparison.head(10).to_dict("records")
    assert len(sql_frame) == len(users_pandas)


def test_reconciliation_detects_a_planted_mismatch():
    """Guard-rail: the comparison must not silently pass wrong numbers."""
    sql = {"gross_gmv": 100.0, "paid_orders": 4, "repeat_rate": 0.5}
    pandas_result = {"gross_gmv": 105.0, "paid_orders": 4, "repeat_rate": 0.5}
    comparison = reconcile.compare_overall(sql, pandas_result)
    assert not comparison.loc[comparison["metric"] == "gross_gmv", "passed"].iloc[0]
    assert comparison.loc[comparison["metric"] == "paid_orders", "passed"].iloc[0]
