"""Read-only integrity checks for a short factor-cabinet governance window."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


RUN_ID = "pruned_run20260706_183553_702097_20260710_202906"
START_DATE = "2021-01-04"
END_DATE = "2021-01-08"


def main() -> int:
    from config import FEATURE_DAILY_PARQUET
    from functions.decision_council.factor_cabinet_feature_cache import (
        _factor_cabinet_raw_columns,
        find_factor_cabinet_feature_cache,
        load_factor_cabinet_feature_cache,
    )
    from functions.decision_council.factor_source import resolve_factor_source

    spec = resolve_factor_source(
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id=RUN_ID,
    )
    raw_columns = list(_factor_cabinet_raw_columns(spec))
    assert spec.factor_count == 74, spec.factor_count
    assert len(raw_columns) == 74, len(raw_columns)

    found, status = find_factor_cabinet_feature_cache(
        spec,
        START_DATE,
        END_DATE,
        feature_path=Path(FEATURE_DAILY_PARQUET),
    )
    assert found is not None, status
    cache_path, manifest = found
    assert manifest["factor_cabinet_run_id"] == RUN_ID
    assert set(manifest["raw_columns"]) >= set(raw_columns)
    assert manifest["requested_date_min"] <= START_DATE
    assert manifest["requested_date_max"] >= END_DATE

    base = pd.read_parquet(
        FEATURE_DAILY_PARQUET,
        columns=["date", "symbol", "instrument_type", "open", "close", "amount", "volatility_20"],
        filters=[
            ("date", ">=", pd.Timestamp(START_DATE)),
            ("date", "<=", pd.Timestamp(END_DATE)),
            ("instrument_type", "in", ["stock", "etf_fund"]),
        ],
    )
    cache = load_factor_cabinet_feature_cache(
        spec,
        START_DATE,
        END_DATE,
        feature_path=Path(FEATURE_DAILY_PARQUET),
    )
    key_columns = ["date", "symbol"]
    assert not base.empty, "base feature window is empty"
    assert not cache.empty, "factor cache window is empty"
    assert not base.duplicated(key_columns).any(), "base feature keys are not unique"
    assert not cache.duplicated(key_columns).any(), "factor cache keys are not unique"
    assert set(raw_columns).issubset(cache.columns), "cache is missing cabinet raw columns"
    assert not cache[raw_columns].isna().all(axis=0).any(), "one or more factor columns are entirely null"

    merged = base.merge(cache, on=key_columns, how="left", validate="one_to_one")
    assert len(merged) == len(base), "cache merge changed base row count"
    assert merged[key_columns].notna().all().all(), "merged keys contain nulls"
    coverage = float(merged[raw_columns].notna().any(axis=1).mean())
    assert coverage > 0.99, f"factor cache row coverage too low: {coverage:.4%}"

    print(
        "[PASS] short-window data integrity | "
        f"base_rows={len(base)}, cache_rows={len(cache)}, factors={len(raw_columns)}, "
        f"factor_row_coverage={coverage:.2%}, cache={cache_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
