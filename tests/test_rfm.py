"""RFM scoring, segment rules and summary arithmetic."""

from __future__ import annotations

import pandas as pd
import pytest

from ecom import rfm


def test_scores_are_bounded():
    frame = pd.DataFrame(
        {
            "customer_id": [f"c{i}" for i in range(10)],
            "recency_days": [1, 5, 10, 20, 30, 45, 60, 90, 120, 200],
            "frequency": [1, 1, 2, 2, 3, 4, 5, 7, 1, 10],
            "monetary": [10, 20, 30, 40, 50, 60, 70, 80, 5, 100],
        }
    )
    cuts = rfm.cutpoints(frame)
    scored = rfm.score_users(frame, cuts)
    for column in ("r_score", "f_score", "m_score"):
        assert scored[column].between(1, 5).all()
    assert scored["rfm_total"].between(3, 15).all()


def test_frequency_mapping_is_deterministic():
    frame = pd.DataFrame(
        {
            "customer_id": ["a", "b", "c", "d"],
            "recency_days": [1, 2, 3, 4],
            "frequency": [1, 3, 5, 12],
            "monetary": [10.0, 20.0, 30.0, 40.0],
        }
    )
    scored = rfm.score_users(frame, rfm.cutpoints(frame)).set_index("customer_id")
    assert scored.loc["a", "f_score"] == 1
    assert scored.loc["b", "f_score"] == 3
    assert scored.loc["c", "f_score"] == 5
    assert scored.loc["d", "f_score"] == 5


def test_recency_and_monetary_direction():
    frame = pd.DataFrame(
        {
            "customer_id": [f"c{i}" for i in range(20)],
            "recency_days": list(range(1, 21)),
            "frequency": [1] * 20,
            "monetary": [float(i) for i in range(1, 21)],
        }
    )
    scored = rfm.score_users(frame, rfm.cutpoints(frame))
    most_recent = scored.sort_values("recency_days").iloc[0]
    least_recent = scored.sort_values("recency_days").iloc[-1]
    assert most_recent["r_score"] > least_recent["r_score"]
    assert most_recent["m_score"] < least_recent["m_score"]


@pytest.mark.parametrize(
    "r,f,expected",
    [
        (5, 5, "champions"),
        (4, 4, "champions"),
        (5, 2, "new_promising"),
        (4, 3, "loyal"),
        (3, 4, "loyal"),
        (3, 2, "need_attention"),
        (2, 4, "at_risk"),
        (2, 2, "hibernating"),
        (1, 4, "at_risk"),
        (1, 2, "lost"),
    ],
)
def test_segment_rules(r, f, expected):
    assert rfm.assign_segment(r, f) == expected


def test_segment_summary_shares_sum_to_one():
    frame = pd.DataFrame(
        {
            "customer_id": [f"c{i}" for i in range(30)],
            "recency_days": list(range(30)),
            "frequency": [1] * 15 + [3] * 15,
            "monetary": [float(i + 1) * 10 for i in range(30)],
        }
    )
    scored = rfm.score_users(frame, rfm.cutpoints(frame))
    summary = rfm.segment_summary(scored)
    assert summary["users"].sum() == 30
    assert summary["user_share"].sum() == pytest.approx(1.0, abs=1e-3)
    assert summary["monetary_share"].sum() == pytest.approx(1.0, abs=1e-3)
    assert set(summary["segment"]).issubset(set(rfm.SEGMENT_ORDER))


def test_cutpoints_are_ordered():
    frame = pd.DataFrame(
        {
            "customer_id": [f"c{i}" for i in range(100)],
            "recency_days": list(range(100)),
            "frequency": [1] * 100,
            "monetary": [float(i) for i in range(100)],
        }
    )
    cuts = rfm.cutpoints(frame)
    assert cuts["r1"] <= cuts["r2"] <= cuts["r3"] <= cuts["r4"]
    assert cuts["m1"] <= cuts["m2"] <= cuts["m3"] <= cuts["m4"]
