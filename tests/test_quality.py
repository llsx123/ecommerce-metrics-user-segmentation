"""Data-quality checks must detect exactly the defects the generator injected."""

from __future__ import annotations

import pytest

from ecom import db, quality


@pytest.fixture(scope="module")
def raw_conn(small_env):
    connection = db.connect(small_env.raw)
    yield connection
    connection.close()


def test_every_injected_defect_is_detected(raw_conn, small_env):
    findings, details = quality.run_checks(raw_conn, small_env.snapshot)
    detected = quality.findings_by_check(findings)
    for check, expected in small_env.manifest.items():
        assert detected[check] == expected, f"{check}: expected {expected}, detected {detected[check]}"


def test_findings_carry_offending_keys(raw_conn, small_env):
    findings, details = quality.run_checks(raw_conn, small_env.snapshot)
    for check, expected in small_env.manifest.items():
        if expected:
            assert len(details[check]) == expected


def test_clean_dataset_has_no_violations(small_env):
    conn = db.connect(small_env.clean)
    try:
        findings, _ = quality.run_checks(conn, small_env.snapshot)
    finally:
        conn.close()
    violations = findings[findings["rows"] > 0]
    assert violations.empty, violations[["check", "rows"]].to_dict("records")


def test_manifest_is_stable_for_a_fixed_seed():
    from ecom import generate
    from ecom.config import SmallDataConfig

    first, manifest_first = generate.generate_dataset(SmallDataConfig())
    second, manifest_second = generate.generate_dataset(SmallDataConfig())
    assert manifest_first == manifest_second
    for name in first:
        assert first[name].equals(second[name]), f"{name} differs between runs"
