"""Verify governance windows end on observed sessions, not calendar holidays."""
from __future__ import annotations

import pandas as pd

from config import FEATURE_DAILY_PARQUET
from functions.data.trading_calendar import bounded_observed_feature_end


def main() -> None:
    unbounded = bounded_observed_feature_end(
        FEATURE_DAILY_PARQUET, "2025-01-01", "2026-05-31", None
    )
    assert unbounded == pd.Timestamp("2026-05-29"), unbounded

    oversized_limit = bounded_observed_feature_end(
        FEATURE_DAILY_PARQUET, "2026-05-25", "2026-05-31", 20
    )
    assert oversized_limit == pd.Timestamp("2026-05-29"), oversized_limit

    bounded = bounded_observed_feature_end(
        FEATURE_DAILY_PARQUET, "2025-01-01", "2026-05-31", 5
    )
    assert bounded == pd.Timestamp("2025-01-08"), bounded
    print("[PASS] governance end dates use the last observed trading session")


if __name__ == "__main__":
    main()
