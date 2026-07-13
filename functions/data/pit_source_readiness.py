"""Audit existing local artifacts before promoting them into formal PIT tables."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import ADJUSTMENT_FACTORS_PARQUET, CLEAN_DAILY_PARQUET, CORPORATE_ACTIONS_PARQUET, PROCESSED_DIR


def audit_existing_pit_sources() -> pd.DataFrame:
    specs = (
        (
            "trading_status_pit",
            Path(CLEAN_DAILY_PARQUET),
            {"date", "symbol", "is_trading", "is_st"},
            False,
            "daily derived status exists; ST/name provenance is not exchange-announcement PIT",
        ),
        (
            "index_membership_pit",
            Path(PROCESSED_DIR) / "index_constituents.parquet",
            {"index_code", "symbol", "asof_date"},
            False,
            "current snapshots exist; historical additions/removals and announcement timestamps are incomplete",
        ),
        (
            "corporate_action_pit",
            Path(CORPORATE_ACTIONS_PARQUET),
            {"symbol", "action_date", "action_type"},
            False,
            "action history exists; announcement/known-at timestamp is absent",
        ),
        (
            "adjustment_reference",
            Path(ADJUSTMENT_FACTORS_PARQUET),
            {"symbol", "action_date", "backward_factor"},
            False,
            "adjustment history is useful for reconciliation but is not a substitute for announcement PIT",
        ),
    )
    rows = []
    for target, path, required, formal_eligible, limitation in specs:
        columns, row_count, error = _parquet_metadata(path)
        missing = sorted(required - columns)
        rows.append(
            {
                "target_table": target,
                "source_path": str(path),
                "source_exists": path.exists(),
                "row_count": row_count,
                "required_columns_present": not missing and not error,
                "missing_columns": "|".join(missing),
                "formal_eligible": bool(path.exists() and not missing and not error and formal_eligible),
                "research_reusable": bool(path.exists() and not missing and not error),
                "limitation": limitation,
                "read_error": error,
            }
        )
    return pd.DataFrame(rows)


def _parquet_metadata(path: Path) -> tuple[set[str], int, str]:
    if not path.exists():
        return set(), 0, "missing"
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        return set(parquet.schema_arrow.names), int(parquet.metadata.num_rows), ""
    except Exception as exc:
        return set(), 0, str(exc)
