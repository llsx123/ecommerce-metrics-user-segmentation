"""SQL vs Pandas cross-validation.

The two implementations share the definitions but not the code path: SQL runs
inside SQLite, Pandas runs vectorised Python. Every comparison below carries an
explicit tolerance matched to the precision of the metric (a cent for money).
"""

from __future__ import annotations

import pandas as pd

MONEY_TOLERANCE = 0.011
RATIO_TOLERANCE = 1e-4
DAYS_TOLERANCE = 0.02


def _rows(metric: str, sql_value, pandas_value, tolerance: float) -> dict:
    diff = abs(float(sql_value) - float(pandas_value))
    return {
        "metric": metric,
        "sql": round(float(sql_value), 6),
        "pandas": round(float(pandas_value), 6),
        "abs_diff": round(diff, 8),
        "tolerance": tolerance,
        "passed": diff <= tolerance,
    }


def compare_overall(sql: dict, pandas_result: dict) -> pd.DataFrame:
    money = {"gross_gmv", "refund_amount", "net_gmv", "aov", "arpu"}
    rows = []
    for key, sql_value in sql.items():
        if key not in pandas_result:
            continue
        tolerance = MONEY_TOLERANCE if key in money or key == "refund_rate" else 0.0
        if key == "repeat_rate":
            tolerance = RATIO_TOLERANCE
        rows.append(_rows(key, sql_value, pandas_result[key], tolerance))
    return pd.DataFrame(rows)


def _compare_keyed(
    sql_frame: pd.DataFrame,
    pandas_frame: pd.DataFrame,
    key: str,
    columns: dict[str, float],
) -> pd.DataFrame:
    """Compare shared numeric columns by key; report unmatched keys as problems too."""
    merged = sql_frame.merge(pandas_frame, on=key, suffixes=("_sql", "_pd"), how="outer", indicator=True)
    problems = []
    for column, tolerance in columns.items():
        left, right = f"{column}_sql", f"{column}_pd"
        diff = (merged[left] - merged[right]).abs()
        unmatched = merged["_merge"] != "both"
        bad = merged[(diff > tolerance) | unmatched]
        for idx, row in bad.iterrows():
            problems.append(
                {
                    key: row[key],
                    "metric": column,
                    "sql": row[left],
                    "pandas": row[right],
                    "abs_diff": round(float(diff.loc[idx]), 8) if pd.notna(diff.loc[idx]) else None,
                    "reason": "key missing on one side" if unmatched.loc[idx] else "value mismatch",
                }
            )
    return pd.DataFrame(problems, columns=[key, "metric", "sql", "pandas", "abs_diff", "reason"])


def compare_monthly(sql_frame: pd.DataFrame, pandas_frame: pd.DataFrame) -> pd.DataFrame:
    return _compare_keyed(
        sql_frame,
        pandas_frame,
        "month",
        {
            "net_gmv": MONEY_TOLERANCE,
            "gross_gmv": MONEY_TOLERANCE,
            "refund_amount": MONEY_TOLERANCE,
            "aov": MONEY_TOLERANCE,
            "paid_orders": 0.0,
            "paid_users": 0.0,
        },
    )


def compare_category(sql_frame: pd.DataFrame, pandas_frame: pd.DataFrame) -> pd.DataFrame:
    return _compare_keyed(
        sql_frame,
        pandas_frame,
        "category",
        {
            "item_gmv": MONEY_TOLERANCE,
            "freight_revenue": MONEY_TOLERANCE,
            "paid_orders": 0.0,
            "gmv_share": RATIO_TOLERANCE,
        },
    )


def compare_users(sql_frame: pd.DataFrame, pandas_frame: pd.DataFrame) -> pd.DataFrame:
    merged = sql_frame.merge(pandas_frame, on="customer_id", suffixes=("_sql", "_pd"), how="outer", indicator=True)
    checks = pd.DataFrame(
        {
            "customer_id": merged["customer_id"],
            "frequency_diff": (merged["frequency_sql"] - merged["frequency_pd"]).abs(),
            "monetary_diff": (merged["monetary_sql"] - merged["monetary_pd"]).abs(),
            "recency_diff": (merged["recency_days_sql"] - merged["recency_days_pd"]).abs(),
            "matched": merged["_merge"] == "both",
        }
    )
    bad = checks[
        (~checks["matched"])
        | (checks["frequency_diff"] > 0)
        | (checks["monetary_diff"] > MONEY_TOLERANCE)
        | (checks["recency_diff"] > 0)
    ]
    return bad.reset_index(drop=True)


def compare_repeat(sql: dict, pandas_result: dict) -> pd.DataFrame:
    rows = [
        _rows("avg_days_between_orders", sql["avg_days_between_orders"], pandas_result["avg_days_between_orders"], DAYS_TOLERANCE),
        _rows("repeat_intervals", sql["repeat_intervals"], pandas_result["repeat_intervals"], 0.0),
        _rows("repeat_customers", sql["repeat_customers"], pandas_result["repeat_customers"], 0.0),
    ]
    return pd.DataFrame(rows)


def compare_rfm(sql_frame: pd.DataFrame, scored_frame: pd.DataFrame) -> pd.DataFrame:
    merged = sql_frame.merge(
        scored_frame[["customer_id", "r_score", "f_score", "m_score"]],
        on="customer_id",
        suffixes=("_sql", "_pd"),
    )
    problems = []
    for column in ("r_score", "f_score", "m_score"):
        diff = (merged[f"{column}_sql"] - merged[f"{column}_pd"]).abs()
        for idx in merged.index[diff > 0]:
            problems.append(
                {
                    "customer_id": merged.loc[idx, "customer_id"],
                    "metric": column,
                    "sql": int(merged.loc[idx, f"{column}_sql"]),
                    "pandas": int(merged.loc[idx, f"{column}_pd"]),
                }
            )
    return pd.DataFrame(problems, columns=["customer_id", "metric", "sql", "pandas"])
