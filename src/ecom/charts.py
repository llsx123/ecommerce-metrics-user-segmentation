"""Charts for the analysis report.

All figures are produced from the actual pipeline output (no hand-written numbers)
and use English labels so that the PNG files render identically on any machine.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display is available in the pipeline

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

PALETTE = ["#2E5EAA", "#5B8DEF", "#8FB3F5", "#C2D5FA", "#E0E9FB", "#9AA5B1", "#D64545"]


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def monthly_trend(monthly: pd.DataFrame, path: Path) -> Path:
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.bar(monthly["month"], monthly["net_gmv"], color=PALETTE[0], alpha=0.85, label="Net GMV")
    ax1.set_ylabel("Net GMV")
    ax1.tick_params(axis="x", rotation=45)
    ax1.set_title("Monthly net GMV and average order value")

    ax2 = ax1.twinx()
    ax2.plot(monthly["month"], monthly["aov"], color=PALETTE[6], marker="o", linewidth=1.8, label="AOV")
    ax2.set_ylabel("AOV")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left", frameon=False)
    return _save(fig, path)


def category_pareto(category: pd.DataFrame, path: Path) -> Path:
    top = category.head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(top["category"], top["item_gmv"], color=PALETTE[1])
    ax.set_xlabel("Item GMV")
    ax.set_title("Top 12 categories by item GMV")
    for y, value in enumerate(top["item_gmv"]):
        ax.text(value, y, f" {value:,.0f}", va="center", fontsize=8)
    return _save(fig, path)


def rfm_segments(summary: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    positions = range(len(summary))
    ax.bar(positions, summary["users"], color=PALETTE[2], label="Customers")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(summary["segment"], rotation=25, ha="right")
    ax.set_ylabel("Customers")
    ax.set_title("RFM segments: customer count vs monetary share")

    ax2 = ax.twinx()
    ax2.plot(positions, summary["monetary_share"] * 100, color=PALETTE[6], marker="o", label="GMV share (%)")
    ax2.set_ylabel("Monetary share (%)")
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper right", frameon=False)
    return _save(fig, path)


def payment_mix(payment_mix_frame: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(payment_mix_frame["payment_type"], payment_mix_frame["payment_value"], color=PALETTE[3], edgecolor=PALETTE[0])
    ax.set_ylabel("Payment value")
    ax.set_title("Payment value by payment type")
    for x, value in enumerate(payment_mix_frame["payment_value"]):
        ax.text(x, value, f"{value:,.0f}", ha="center", va="bottom", fontsize=8)
    return _save(fig, path)
