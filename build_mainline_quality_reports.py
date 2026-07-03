"""Build missing mainline quality reports from existing parquet artifacts.

This script is intentionally narrower than the full pipeline. It does not
recompute features or strategies; it only rebuilds the reports verified by
verify_mainline_outputs.py.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" build_mainline_quality_reports.py
"""
from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

from config import (
    ADJUSTMENT_PTI_QUALITY_CSV,
    CLEAN_DAILY_PARQUET,
    DATA_CONTINUITY_REPORT_CSV,
    FEATURE_DAILY_PARQUET,
    FEATURE_DOWNCAST_FLOATS,
    FEATURE_MEMORY_REPORT_CSV,
    FEATURE_STORAGE_MODE,
)
from functions.data_sources.adjustment_factors import save_adjustment_pti_coverage_report
from functions.quality_checks import build_data_continuity_report


def build_feature_memory_report() -> pd.DataFrame:
    parquet_file = pq.ParquetFile(FEATURE_DAILY_PARQUET)
    schema = parquet_file.schema_arrow
    file_size_bytes = int(FEATURE_DAILY_PARQUET.stat().st_size)
    return pd.DataFrame(
        [
            {
                "feature_storage_mode": str(FEATURE_STORAGE_MODE),
                "feature_downcast_floats": bool(FEATURE_DOWNCAST_FLOATS),
                "rows_before": int(parquet_file.metadata.num_rows),
                "columns_before": int(len(schema.names)),
                "memory_before_bytes": file_size_bytes,
                "rows_after": int(parquet_file.metadata.num_rows),
                "columns_after": int(len(schema.names)),
                "memory_after_bytes": file_size_bytes,
                "memory_saved_bytes": 0,
                "memory_saved_ratio": 0.0,
                "report_source": "existing_feature_parquet_metadata",
            }
        ]
    )


def _read_existing_columns(path, wanted: list[str]) -> pd.DataFrame:
    available = set(pq.read_schema(path).names)
    columns = [column for column in wanted if column in available]
    missing_required = sorted(set(wanted[:2]) - set(columns))
    if missing_required:
        raise ValueError(f"{path} missing required columns: {missing_required}")
    return pd.read_parquet(path, columns=columns)


def main() -> None:
    FEATURE_MEMORY_REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)

    memory = build_feature_memory_report()
    memory.to_csv(FEATURE_MEMORY_REPORT_CSV, index=False, encoding="utf-8-sig")
    print("Saved feature memory report:", FEATURE_MEMORY_REPORT_CSV)

    clean = _read_existing_columns(CLEAN_DAILY_PARQUET, ["date", "symbol"])
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce")
    continuity = build_data_continuity_report(clean.dropna(subset=["date", "symbol"]), group_col="symbol")
    continuity.to_csv(DATA_CONTINUITY_REPORT_CSV, index=False, encoding="utf-8-sig")
    print("Saved data continuity report:", DATA_CONTINUITY_REPORT_CSV)

    feature = _read_existing_columns(
        FEATURE_DAILY_PARQUET,
        ["date", "symbol", "adj_factor_available", "feature_price_source"],
    )
    feature["date"] = pd.to_datetime(feature["date"], errors="coerce")
    saved = save_adjustment_pti_coverage_report(feature.dropna(subset=["date", "symbol"]), ADJUSTMENT_PTI_QUALITY_CSV)
    print("Saved adjustment PTI coverage report:", saved)


if __name__ == "__main__":
    main()
