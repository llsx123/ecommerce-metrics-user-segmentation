"""RFM scoring and rule-based customer segmentation.

Why not ``NTILE``?
------------------
Frequency is extremely tied (about half of the customers place exactly one order).
``NTILE(5)`` would split those ties arbitrarily, so two runs over the same data
could produce different scores and the SQL result could not be reproduced in
Pandas. Instead the quintile *cut points* are computed once and applied with a
deterministic rule in both layers; frequency keeps a fixed business mapping
(1 order -> 1, ..., 5+ orders -> 5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENT_ORDER = (
    "champions",
    "loyal",
    "new_promising",
    "need_attention",
    "at_risk",
    "hibernating",
    "lost",
)

SEGMENT_LABELS = {
    "champions": "Champions",
    "loyal": "Loyal customers",
    "new_promising": "New / promising",
    "need_attention": "Need attention",
    "at_risk": "At risk",
    "hibernating": "Hibernating",
    "lost": "Lost",
}


def cutpoints(user_frame: pd.DataFrame) -> dict[str, float]:
    """Global quintile cut points for recency (days) and monetary value."""
    recency = np.quantile(user_frame["recency_days"].to_numpy(dtype=float), [0.2, 0.4, 0.6, 0.8])
    monetary = np.quantile(user_frame["monetary"].to_numpy(dtype=float), [0.2, 0.4, 0.6, 0.8])
    return {
        "r1": round(float(recency[0]), 4),
        "r2": round(float(recency[1]), 4),
        "r3": round(float(recency[2]), 4),
        "r4": round(float(recency[3]), 4),
        "m1": round(float(monetary[0]), 4),
        "m2": round(float(monetary[1]), 4),
        "m3": round(float(monetary[2]), 4),
        "m4": round(float(monetary[3]), 4),
    }


def _recency_score(days: pd.Series, cuts: dict[str, float]) -> pd.Series:
    edges = np.array([cuts["r1"], cuts["r2"], cuts["r3"], cuts["r4"]], dtype=float)
    values = days.to_numpy(dtype=float)
    # recency: fewer days is better -> score 5 for the most recent quintile.
    # number of cut points strictly below the value gives 0..4, so 5 - that is 5..1.
    return pd.Series(np.clip(5 - np.searchsorted(edges, values, side="left"), 1, 5), index=days.index)


def _monetary_score(monetary: pd.Series, cuts: dict[str, float]) -> pd.Series:
    edges = np.array([cuts["m1"], cuts["m2"], cuts["m3"], cuts["m4"]], dtype=float)
    values = monetary.to_numpy(dtype=float)
    # number of cut points at or below the value -> 1..5, higher monetary is better
    return pd.Series(np.clip(np.searchsorted(edges, values, side="right") + 1, 1, 5), index=monetary.index)


def assign_segment(recency_score: int, frequency_score: int) -> str:
    """Deterministic business rules on the R and F scores (M is summed into RFM total)."""
    r, f = int(recency_score), int(frequency_score)
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


def score_users(user_frame: pd.DataFrame, cuts: dict[str, float]) -> pd.DataFrame:
    scored = user_frame.copy()
    scored["r_score"] = _recency_score(scored["recency_days"], cuts).astype(int)
    scored["f_score"] = np.minimum(scored["frequency"], 5).astype(int)
    scored["m_score"] = _monetary_score(scored["monetary"], cuts).astype(int)
    scored["rfm_total"] = scored["r_score"] + scored["f_score"] + scored["m_score"]
    scored["segment"] = [
        assign_segment(r, f) for r, f in zip(scored["r_score"], scored["f_score"])
    ]
    return scored


def segment_summary(scored: pd.DataFrame) -> pd.DataFrame:
    total_users = len(scored)
    total_monetary = float(scored["monetary"].sum())
    grouped = scored.groupby("segment").agg(
        users=("customer_id", "count"),
        avg_recency_days=("recency_days", "mean"),
        avg_frequency=("frequency", "mean"),
        avg_monetary=("monetary", "mean"),
        total_monetary=("monetary", "sum"),
    )
    grouped["user_share"] = grouped["users"] / total_users
    grouped["monetary_share"] = grouped["total_monetary"] / total_monetary
    grouped = grouped.reindex([s for s in SEGMENT_ORDER if s in grouped.index])
    for col in ("avg_recency_days", "avg_frequency", "avg_monetary", "total_monetary"):
        grouped[col] = grouped[col].round(2)
    grouped["user_share"] = grouped["user_share"].round(4)
    grouped["monetary_share"] = grouped["monetary_share"].round(4)
    return grouped.reset_index()
