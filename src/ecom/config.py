"""Project-wide configuration: paths, data-generation parameters, metric constants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SQL_DIR = PROJECT_ROOT / "sql"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
REPORT_DIR = PROJECT_ROOT / "reports"
FIG_DIR = REPORT_DIR / "figures"

RAW_DB = DATA_DIR / "ecommerce_raw.db"
CLEAN_DB = DATA_DIR / "ecommerce_clean.db"

#: Order statuses treated as revenue-generating (anything paid but not cancelled / unavailable).
VALID_STATUSES = ("approved", "invoiced", "processing", "shipped", "delivered")

#: Two float sums are considered reconciled when they differ by less than one cent.
MONEY_TOLERANCE = 0.011


@dataclass(frozen=True)
class DataConfig:
    """Parameters of the synthetic dataset. A fixed seed keeps every run reproducible."""

    seed: int = 20240101
    n_users: int = 12000
    n_products: int = 1200
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"

    @property
    def snapshot(self) -> str:
        """End-of-day analysis snapshot; recency is measured against it."""
        return f"{self.end_date} 23:59:59"


@dataclass(frozen=True)
class SmallDataConfig(DataConfig):
    """Small dataset used by the test-suite (fast, still contains injected anomalies)."""

    seed: int = 7
    n_users: int = 400
    n_products: int = 60
