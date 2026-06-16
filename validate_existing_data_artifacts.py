# -*- coding: utf-8 -*-
"""Validate published data artifacts before deciding whether to rebuild them."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    CLEAN_DAILY_PARQUET,
    CORPORATE_ACTIONS_PARQUET,
    FEATURE_DAILY_PARQUET,
    MARKET_CAP_PARQUET,
    RAW_DAILY_PARQUET,
    REPORT_DIR,
    ARTIFACT_VALIDATION_ROW_GROUP_SAMPLE_SIZE,
    ARTIFACT_VALIDATION_ROWS_PER_GROUP,
    ARTIFACT_VALIDATION_SYMBOL_SAMPLE_SIZE,
    assert_valid_configuration,
)
from functions.data_sources.adjustment_factors import REQUIRED_ADJUSTMENT_FACTOR_COLUMNS
from functions.data_sources.corporate_actions import REQUIRED_CORPORATE_ACTION_COLUMNS
from functions.data_sources.market_cap_data import REQUIRED_MARKET_CAP_COLUMNS


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["tdx-daily", "baostock", "market-cap", "features"], required=True)
    parser.add_argument("--symbol-sample-size", type=int, default=ARTIFACT_VALIDATION_SYMBOL_SAMPLE_SIZE)
    parser.add_argument("--row-group-sample-size", type=int, default=ARTIFACT_VALIDATION_ROW_GROUP_SAMPLE_SIZE)
    parser.add_argument("--rows-per-group", type=int, default=ARTIFACT_VALIDATION_ROWS_PER_GROUP)
    return parser.parse_args()


def main():
    assert_valid_configuration()
    args = parse_args()
    if args.dataset == "tdx-daily":
        checks = validate_tdx_daily_artifacts(
            row_group_sample_size=args.row_group_sample_size,
            rows_per_group=args.rows_per_group,
        )
    elif args.dataset == "baostock":
        checks = validate_baostock_artifacts(symbol_sample_size=args.symbol_sample_size)
    elif args.dataset == "market-cap":
        checks = validate_market_cap_artifact(
            row_group_sample_size=args.row_group_sample_size,
            rows_per_group=args.rows_per_group,
        )
    else:
        checks = validate_feature_artifact(
            row_group_sample_size=args.row_group_sample_size,
            rows_per_group=args.rows_per_group,
        )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"existing_{args.dataset.replace('-', '_')}_artifact_spot_check.csv"
    pd.DataFrame(checks).to_csv(report_path, index=False, encoding="utf-8-sig")
    failed = [row for row in checks if row["status"] != "passed"]
    print(f"Existing artifact spot check: dataset={args.dataset}, checks={len(checks)}, failed={len(failed)}")
    print("Spot-check report:", report_path)
    for row in checks:
        print(f"  [{row['status'].upper()}] {row['check']}: {row['detail']}")
    if failed:
        raise RuntimeError(f"Existing {args.dataset} artifact spot check failed")


def validate_baostock_artifacts(symbol_sample_size=24):
    checks = []
    factors = _read_required_parquet(
        ADJUSTMENT_FACTORS_PARQUET,
        REQUIRED_ADJUSTMENT_FACTOR_COLUMNS,
        "adjustment_factors",
        checks,
    )
    actions = _read_required_parquet(
        CORPORATE_ACTIONS_PARQUET,
        REQUIRED_CORPORATE_ACTION_COLUMNS,
        "corporate_actions",
        checks,
    )
    if factors is None or actions is None:
        return checks

    factor_symbols = sorted(factors["symbol"].dropna().astype(str).unique())
    sampled_symbols = _even_sample(factor_symbols, symbol_sample_size)
    factor_sample = factors[factors["symbol"].isin(sampled_symbols)].copy()
    action_sample = actions[actions["symbol"].isin(sampled_symbols)].copy()
    checks.extend(
        [
            _check(
                "adjustment_factor_symbol_sample",
                len(sampled_symbols) >= min(symbol_sample_size, len(factor_symbols)),
                f"sampled_symbols={len(sampled_symbols)} total_symbols={len(factor_symbols)}",
            ),
            _check(
                "adjustment_factor_sample_source",
                factor_sample["source_name"].eq("baostock_adjust_factor").all(),
                f"sample_rows={len(factor_sample)}",
            ),
            _check(
                "adjustment_factor_sample_valid",
                (
                    factor_sample["symbol"].notna()
                    & pd.to_datetime(factor_sample["action_date"], errors="coerce").notna()
                    & pd.to_numeric(factor_sample["backward_factor"], errors="coerce").gt(0)
                    & factor_sample["factor_source_validated"].fillna(False)
                ).all(),
                f"sample_rows={len(factor_sample)}",
            ),
            _check(
                "corporate_action_source",
                actions["source_name"].eq("baostock_dividend").all(),
                f"rows={len(actions)} sampled_rows={len(action_sample)}",
            ),
            _check(
                "corporate_action_sample_valid",
                action_sample.empty
                or (
                    action_sample["symbol"].notna()
                    & pd.to_datetime(action_sample["action_date"], errors="coerce").notna()
                    & action_sample["action_type"].astype(str).str.strip().ne("")
                ).all(),
                f"sampled_symbols={len(sampled_symbols)} sampled_rows={len(action_sample)}",
            ),
        ]
    )
    return checks


def validate_tdx_daily_artifacts(row_group_sample_size=12, rows_per_group=200):
    checks = []
    required_raw = [
        "date",
        "market",
        "code",
        "symbol",
        "instrument_type",
        "open",
        "high",
        "low",
        "close",
        "amount",
        "volume",
    ]
    required_clean = required_raw + ["valid_price", "valid_volume", "is_trading"]
    raw_sample, raw_metadata = _sample_parquet_row_groups(
        RAW_DAILY_PARQUET,
        required_raw,
        row_group_sample_size,
        rows_per_group,
        "tdx_daily_raw",
        checks,
    )
    clean_sample, clean_metadata = _sample_parquet_row_groups(
        CLEAN_DAILY_PARQUET,
        required_clean,
        row_group_sample_size,
        rows_per_group,
        "tdx_daily_clean",
        checks,
    )
    if raw_sample is None or clean_sample is None:
        return checks
    checks.extend(
        [
            _check(
                "tdx_raw_sample_keys",
                raw_sample["symbol"].notna().all()
                and pd.to_datetime(raw_sample["date"], errors="coerce").notna().all(),
                raw_metadata,
            ),
            _check(
                "tdx_raw_sample_prices",
                pd.to_numeric(raw_sample["close"], errors="coerce").gt(0).all(),
                f"sample_rows={len(raw_sample)}",
            ),
            _check(
                "tdx_clean_sample_keys",
                clean_sample["symbol"].notna().all()
                and pd.to_datetime(clean_sample["date"], errors="coerce").notna().all(),
                clean_metadata,
            ),
            _check(
                "tdx_clean_sample_prices",
                pd.to_numeric(clean_sample["close"], errors="coerce").gt(0).all()
                and clean_sample["valid_price"].fillna(False).all(),
                f"sample_rows={len(clean_sample)}",
            ),
        ]
    )
    return checks


def validate_market_cap_artifact(row_group_sample_size=12, rows_per_group=200):
    checks = []
    sample, metadata = _sample_parquet_row_groups(
        MARKET_CAP_PARQUET,
        REQUIRED_MARKET_CAP_COLUMNS,
        row_group_sample_size,
        rows_per_group,
        "market_cap_history",
        checks,
    )
    if sample is None:
        return checks
    total_cap = pd.to_numeric(sample["total_cap"], errors="coerce")
    float_cap = pd.to_numeric(sample["float_cap"], errors="coerce")
    coverage_ratio = min(float(total_cap.notna().mean()), float(float_cap.notna().mean()))
    checks.extend(
        [
            _check(
                "market_cap_sample_source",
                sample["source_name"].eq("tdx_finance_gpcw").all(),
                metadata,
            ),
            _check(
                "market_cap_sample_keys",
                sample["symbol"].notna().all()
                and pd.to_datetime(sample["date"], errors="coerce").notna().all(),
                f"sample_rows={len(sample)}",
            ),
            _check(
                "market_cap_sample_coverage",
                coverage_ratio >= 0.95,
                f"coverage_ratio={coverage_ratio:.4f} sample_rows={len(sample)} threshold=0.95",
            ),
            _check(
                "market_cap_sample_non_null_values",
                total_cap.dropna().gt(0).all() and float_cap.dropna().gt(0).all(),
                f"non_null_total={int(total_cap.notna().sum())} non_null_float={int(float_cap.notna().sum())}",
            ),
        ]
    )
    return checks


def validate_feature_artifact(row_group_sample_size=12, rows_per_group=200):
    required = [
        "date",
        "symbol",
        "close_nominal",
        "close_adj_pti",
        "formal_price_eligible",
        "backward_factor",
        "total_cap",
    ]
    checks = []
    sample, metadata = _sample_parquet_row_groups(
        FEATURE_DAILY_PARQUET,
        required,
        row_group_sample_size,
        rows_per_group,
        "tdx_daily_features",
        checks,
    )
    if sample is None:
        return checks
    eligible = sample["formal_price_eligible"].fillna(False)
    eligible_sample = sample[eligible]
    checks.extend(
        [
            _check(
                "feature_sample_keys",
                sample["symbol"].notna().all()
                and pd.to_datetime(sample["date"], errors="coerce").notna().all(),
                metadata,
            ),
            _check(
                "feature_sample_nominal_price",
                pd.to_numeric(sample["close_nominal"], errors="coerce").gt(0).all(),
                f"sample_rows={len(sample)}",
            ),
            _check(
                "feature_sample_adjusted_price",
                not eligible_sample.empty
                and pd.to_numeric(eligible_sample["close_adj_pti"], errors="coerce").gt(0).all()
                and pd.to_numeric(eligible_sample["backward_factor"], errors="coerce").gt(0).all(),
                f"eligible_sample_rows={len(eligible_sample)} sample_rows={len(sample)}",
            ),
        ]
    )
    return checks


def _read_required_parquet(path, required_columns, label, checks):
    path = Path(path)
    if not path.exists():
        checks.append(_check(f"{label}_exists", False, str(path)))
        return None
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema_arrow.names)
    missing = sorted(set(required_columns) - available)
    checks.append(_check(f"{label}_schema", not missing, f"rows={parquet.metadata.num_rows} missing={missing}"))
    if missing or parquet.metadata.num_rows == 0:
        checks.append(_check(f"{label}_non_empty", False, f"rows={parquet.metadata.num_rows}"))
        return None
    checks.append(_check(f"{label}_non_empty", True, f"rows={parquet.metadata.num_rows}"))
    return pd.read_parquet(path, columns=required_columns)


def _sample_parquet_row_groups(path, required_columns, group_count, rows_per_group, label, checks):
    path = Path(path)
    if not path.exists():
        checks.append(_check(f"{label}_exists", False, str(path)))
        return None, ""
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema_arrow.names)
    missing = sorted(set(required_columns) - available)
    checks.append(_check(f"{label}_schema", not missing, f"rows={parquet.metadata.num_rows} missing={missing}"))
    if missing or parquet.metadata.num_rows == 0 or parquet.num_row_groups == 0:
        return None, ""
    group_indexes = _even_sample(list(range(parquet.num_row_groups)), group_count)
    frames = [
        parquet.read_row_group(index, columns=required_columns).to_pandas().head(max(rows_per_group, 1))
        for index in group_indexes
    ]
    sample = pd.concat(frames, ignore_index=True)
    metadata = (
        f"total_rows={parquet.metadata.num_rows} row_groups={parquet.num_row_groups} "
        f"sampled_groups={len(group_indexes)} sample_rows={len(sample)}"
    )
    checks.append(_check(f"{label}_distributed_sample", not sample.empty, metadata))
    return sample, metadata


def _even_sample(values, sample_size):
    values = list(values)
    sample_size = min(max(int(sample_size), 1), len(values))
    if not values or sample_size == 0:
        return []
    if sample_size == 1:
        return [values[0]]
    indexes = sorted({round(index * (len(values) - 1) / (sample_size - 1)) for index in range(sample_size)})
    return [values[index] for index in indexes]


def _check(check, passed, detail):
    return {"check": check, "status": "passed" if bool(passed) else "failed", "detail": detail}


if __name__ == "__main__":
    main()
