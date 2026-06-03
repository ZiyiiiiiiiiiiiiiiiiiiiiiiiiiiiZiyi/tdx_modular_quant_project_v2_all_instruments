from pathlib import Path

import pandas as pd

from config import (
    CLEAN_DAILY_PARQUET,
    FEATURE_DAILY_PARQUET,
    PROCESSED_DIR,
    RAW_DAILY_PARQUET,
    RESULT_DIR,
)
from functions.strategy_registry import STRATEGY_REGISTRY, list_strategy_names


REQUIRED_FEATURE_COLUMNS = {
    "date",
    "symbol",
    "close",
    "ret_1",
    "ret_20",
    "volatility_20",
    "score_mom_lowvol",
}

REQUIRED_SELECTION_COLUMNS = {
    "rebalance_date",
    "symbol",
    "score",
    "weight",
}

REQUIRED_SUMMARY_COLUMNS = {
    "strategy",
    "total_return",
    "sharpe",
    "max_drawdown",
    "composite_score",
}


def check_file_exists(path: Path, label: str, failures: list[str]):
    if path.exists():
        print(f"[PASS] {label}: {path}")
        return True
    print(f"[FAIL] {label}: missing {path}")
    failures.append(f"{label} missing: {path}")
    return False


def check_columns(frame: pd.DataFrame, required_columns: set[str], label: str, failures: list[str]):
    missing = sorted(required_columns - set(frame.columns))
    if not missing:
        print(f"[PASS] {label}: required columns present")
        return
    print(f"[FAIL] {label}: missing columns {missing}")
    failures.append(f"{label} missing columns: {missing}")


def verify_mainline_outputs():
    failures: list[str] = []

    print("=== Verify mainline outputs ===")
    raw_ok = check_file_exists(RAW_DAILY_PARQUET, "raw parquet", failures)
    clean_ok = check_file_exists(CLEAN_DAILY_PARQUET, "clean parquet", failures)
    feature_ok = check_file_exists(FEATURE_DAILY_PARQUET, "feature parquet", failures)

    if feature_ok:
        feature_df = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=list(REQUIRED_FEATURE_COLUMNS))
        check_columns(feature_df, REQUIRED_FEATURE_COLUMNS, "feature parquet", failures)

    strategy_names = list_strategy_names()
    print(f"Configured strategy count: {len(strategy_names)}")
    print(f"Configured strategy names: {strategy_names}")

    missing_strategy_files = []
    for strategy_name in strategy_names:
        selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
        if not selection_path.exists():
            missing_strategy_files.append(str(selection_path))
            print(f"[FAIL] strategy selection: missing {selection_path}")
            continue
        selection_df = pd.read_parquet(selection_path)
        print(f"[PASS] strategy selection: {selection_path}")
        check_columns(
            selection_df,
            REQUIRED_SELECTION_COLUMNS,
            f"strategy selection {strategy_name}",
            failures,
        )

    if missing_strategy_files:
        failures.append(f"missing strategy selection files: {len(missing_strategy_files)}")

    existing_strategy_files = {
        path.stem
        for path in PROCESSED_DIR.glob("*.parquet")
        if path.name not in {
            "tdx_daily_raw.parquet",
            "tdx_daily_clean.parquet",
            "tdx_daily_features.parquet",
            "strategy_selection.parquet",
        }
    }
    unexpected_strategy_files = sorted(existing_strategy_files - set(strategy_names))
    if unexpected_strategy_files:
        print(f"[INFO] retained legacy/non-active strategy files: {unexpected_strategy_files}")
    else:
        print("[PASS] processed strategy files match configured registry")

    summary_path = RESULT_DIR / "backtest_strategy_summary.csv"
    summary_ok = check_file_exists(summary_path, "backtest summary", failures)
    if summary_ok:
        summary_df = pd.read_csv(summary_path)
        check_columns(summary_df, REQUIRED_SUMMARY_COLUMNS, "backtest summary", failures)

        summary_strategies = set(summary_df["strategy"].astype(str))
        missing_from_summary = sorted(set(strategy_names) - summary_strategies)
        unexpected_in_summary = sorted(summary_strategies - set(strategy_names))
        if missing_from_summary:
            print(f"[FAIL] backtest summary missing strategies: {missing_from_summary}")
            failures.append(
                f"backtest summary missing configured strategies: {missing_from_summary}"
            )
        else:
            print("[PASS] backtest summary includes all configured strategies")

        if unexpected_in_summary:
            print(f"[FAIL] backtest summary has unexpected strategies: {unexpected_in_summary}")
            failures.append(
                f"backtest summary contains unexpected strategies: {unexpected_in_summary}"
            )
        else:
            print("[PASS] backtest summary contains no unexpected strategies")

    registry_duplicates = [
        name for name in strategy_names if strategy_names.count(name) > 1
    ]
    if registry_duplicates:
        print(f"[FAIL] duplicate strategy names in registry: {registry_duplicates}")
        failures.append(f"duplicate strategy names in registry: {registry_duplicates}")
    else:
        print("[PASS] strategy registry names are unique")

    missing_descriptions = [
        name for name, spec in STRATEGY_REGISTRY.items()
        if not getattr(spec, "description", "")
    ]
    if missing_descriptions:
        print(f"[FAIL] strategy registry missing descriptions: {missing_descriptions}")
        failures.append(
            f"strategy registry missing descriptions: {missing_descriptions}"
        )
    else:
        print("[PASS] strategy registry descriptions are populated")

    print()
    if failures:
        print("Verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    if raw_ok and clean_ok and feature_ok:
        print("Verification passed.")


if __name__ == "__main__":
    verify_mainline_outputs()
