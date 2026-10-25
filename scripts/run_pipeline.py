#!/usr/bin/env python
"""End-to-end pipeline for the e-commerce metrics project.

    python scripts/run_pipeline.py

Steps: generate -> data quality -> clean -> SQL metrics -> Pandas cross-check ->
RFM -> charts -> Markdown report -> summary JSON.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402
import numpy as np  # noqa: E402

from ecom import (  # noqa: E402
    charts,
    clean,
    config,
    db,
    generate,
    metrics,
    pandas_metrics,
    quality,
    reconcile,
    report,
    rfm,
)

STRUCTURAL_CHECKS = (
    "duplicate_users",
    "duplicate_order_items",
    "missing_customer_id",
    "orphan_order_customer",
    "orphan_item_product",
    "negative_item_price",
    "payment_mismatch_orders",
    "refund_exceeds_payment",
    "future_dated_orders",
    "orders_without_payment",
)


def _status(frame: pd.DataFrame, label: str, total: int) -> str:
    passed = int(frame["passed"].sum()) if "passed" in frame.columns else 0
    return f"{label}: {passed}/{total} passed"


def _jsonable(value):
    """Convert numpy scalars so that ``json.dumps`` never chokes on them."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def main() -> int:
    started = time.time()
    for directory in (config.DATA_DIR, config.OUTPUT_DIR, config.REPORT_DIR, config.FIG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    cfg = config.DataConfig()
    snapshot = cfg.snapshot

    print(f"[1/8] generate synthetic data (seed={cfg.seed}, users={cfg.n_users}, products={cfg.n_products})")
    tables, manifest = generate.generate_dataset(cfg)
    raw_db = db.build_database(tables, config.RAW_DB)
    print(f"      raw database: {raw_db} ({len(tables['orders']):,} orders)")

    print("[2/8] data-quality checks on the raw layer")
    raw_conn = db.connect(raw_db)
    try:
        findings, _ = quality.run_checks(raw_conn, snapshot)
    finally:
        raw_conn.close()
    findings.to_csv(config.OUTPUT_DIR / "dq_findings.csv", index=False)
    detected = quality.findings_by_check(findings)
    mismatched = {k: (detected.get(k), v) for k, v in manifest.items() if detected.get(k) != v}
    if mismatched:
        raise SystemExit(f"data-quality checks do not match the injected manifest: {mismatched}")
    print(f"      all {len(manifest)} injected defect types detected exactly (manifest verified)")

    print("[3/8] quarantine defective orders and build the cleaned database")
    clean_tables, stats = clean.build_clean_database(raw_db, config.CLEAN_DB, snapshot)
    print(
        f"      raw orders {stats['raw_orders']:,} -> quarantined {stats['quarantined_orders']:,}"
        f" -> clean orders {stats['clean_orders']:,}"
    )

    print("[4/8] post-clean verification (strict schema, no residual defects)")
    clean_conn = db.connect(config.CLEAN_DB)
    try:
        post_findings, _ = quality.run_checks(clean_conn, snapshot)
    finally:
        clean_conn.close()
    residual = {row["check"]: int(row["rows"]) for _, row in post_findings.iterrows() if row["rows"] > 0}
    if residual:
        raise SystemExit(f"cleaned database still violates: {residual}")
    print("      all checks are clean (0 violations)")

    print("[5/8] SQL metrics")
    conn = db.connect(config.CLEAN_DB)
    try:
        overall_sql = metrics.overall(conn, snapshot)
        monthly_sql = metrics.monthly(conn, snapshot)
        category_sql = metrics.category(conn, snapshot)
        users_sql = metrics.users(conn, snapshot)
        repeat_sql = metrics.repeat_intervals(conn, snapshot)

        overall_pd = pandas_metrics.overall(conn, snapshot)
        monthly_pd = pandas_metrics.monthly(conn, snapshot)
        category_pd = pandas_metrics.category(conn, snapshot)
        users_pd = pandas_metrics.users(conn, snapshot)
        repeat_pd = pandas_metrics.repeat_intervals(conn, snapshot)
        payment_mix = pandas_metrics.payment_mix(conn, snapshot)

        cuts = rfm.cutpoints(users_pd)
        rfm_sql = metrics.rfm(conn, snapshot, cuts)
    finally:
        conn.close()

    monthly_sql.to_csv(config.OUTPUT_DIR / "monthly_metrics.csv", index=False)
    category_sql.to_csv(config.OUTPUT_DIR / "category_metrics.csv", index=False)
    users_sql.to_csv(config.OUTPUT_DIR / "user_metrics.csv", index=False)

    print("[6/8] SQL vs Pandas cross-validation")
    overall_cmp = reconcile.compare_overall(overall_sql, overall_pd)
    monthly_cmp = reconcile.compare_monthly(monthly_sql, monthly_pd)
    category_cmp = reconcile.compare_category(category_sql, category_pd)
    users_cmp = reconcile.compare_users(users_sql, users_pd)
    repeat_cmp = reconcile.compare_repeat(repeat_sql, repeat_pd)

    scored = rfm.score_users(users_pd, cuts)
    rfm_cmp = reconcile.compare_rfm(rfm_sql, scored)
    scored.to_csv(config.OUTPUT_DIR / "rfm_users.csv", index=False)
    rfm_summary = rfm.segment_summary(scored)
    rfm_summary.to_csv(config.OUTPUT_DIR / "rfm_segments.csv", index=False)

    overall_cmp.to_csv(config.OUTPUT_DIR / "reconcile_overall.csv", index=False)
    monthly_cmp.to_csv(config.OUTPUT_DIR / "reconcile_monthly.csv", index=False)
    category_cmp.to_csv(config.OUTPUT_DIR / "reconcile_category.csv", index=False)
    users_cmp.to_csv(config.OUTPUT_DIR / "reconcile_users.csv", index=False)
    repeat_cmp.to_csv(config.OUTPUT_DIR / "reconcile_repeat.csv", index=False)
    rfm_cmp.to_csv(config.OUTPUT_DIR / "reconcile_rfm.csv", index=False)

    reconcile_summary = {
        "overall": _status(overall_cmp, "core metrics", len(overall_cmp)),
        "monthly": "PASS" if monthly_cmp.empty else f"FAIL ({len(monthly_cmp)} cells)",
        "category": "PASS" if category_cmp.empty else f"FAIL ({len(category_cmp)} cells)",
        "users": "PASS" if users_cmp.empty else f"FAIL ({len(users_cmp)} users)",
        "repeat": _status(repeat_cmp, "repeat intervals", len(repeat_cmp)),
        "rfm": "PASS" if rfm_cmp.empty else f"FAIL ({len(rfm_cmp)} scores)",
    }
    failures = [key for key, text in reconcile_summary.items() if "FAIL" in text]
    for key, text in reconcile_summary.items():
        print(f"      {key:<9} {text}")
    if failures:
        raise SystemExit(f"SQL/Pandas reconciliation failed for: {failures}")

    print("[7/8] charts and report")
    fig_monthly = charts.monthly_trend(monthly_sql, config.FIG_DIR / "monthly_trend.png")
    fig_category = charts.category_pareto(category_sql, config.FIG_DIR / "category_pareto.png")
    fig_rfm = charts.rfm_segments(rfm_summary, config.FIG_DIR / "rfm_segments.png")
    fig_payment = charts.payment_mix(payment_mix, config.FIG_DIR / "payment_mix.png")
    figures = [str(p) for p in (fig_monthly, fig_category, fig_rfm, fig_payment)]

    report_path = report.build_report(
        overall=overall_sql,
        monthly=monthly_sql,
        category=category_sql,
        rfm_summary=rfm_summary,
        dq_findings=findings,
        stats=stats,
        reconcile_summary=reconcile_summary,
        sample_users=cfg.n_users,
        seed=cfg.seed,
    )

    print("[8/8] writing summary")
    summary = {
        "config": {
            "seed": cfg.seed,
            "n_users": cfg.n_users,
            "n_products": cfg.n_products,
            "start_date": cfg.start_date,
            "end_date": cfg.end_date,
            "snapshot": snapshot,
        },
        "cleaning": stats,
        "data_quality": {"injected": manifest, "detected": detected},
        "metrics": {k: _jsonable(v) for k, v in overall_sql.items()},
        "repeat": {k: _jsonable(v) for k, v in repeat_sql.items()},
        "reconciliation": reconcile_summary,
        "rfm_segments": rfm_summary.to_dict(orient="records"),
        "artifacts": {
            "report": str(report_path),
            "figures": figures,
            "raw_db": str(raw_db),
            "clean_db": str(config.CLEAN_DB),
        },
        "runtime_seconds": round(time.time() - started, 2),
    }
    (config.OUTPUT_DIR / "pipeline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\nDone in {summary['runtime_seconds']}s | "
        f"net GMV {overall_sql['net_gmv']:,.2f} | orders {int(overall_sql['paid_orders']):,} | "
        f"users {int(overall_sql['paid_users']):,} | repeat rate {overall_sql['repeat_rate']:.2%}"
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
