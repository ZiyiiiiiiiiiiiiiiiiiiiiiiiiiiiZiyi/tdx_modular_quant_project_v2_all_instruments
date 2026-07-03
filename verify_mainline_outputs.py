from pathlib import Path

import pandas as pd

from config import (
    ADJUSTMENT_PTI_QUALITY_CSV,
    CLEAN_DAILY_PARQUET,
    DATA_CONTINUITY_REPORT_CSV,
    FEATURE_DAILY_PARQUET,
    FEATURE_MEMORY_REPORT_CSV,
    GOVERNANCE_OUTPUT_DIR,
    PROCESSED_DIR,
    RAW_DAILY_PARQUET,
    RESULT_DIR,
    STRATEGY_END_DATE,
    STRATEGY_START_DATE,
)
from functions.date_window import assert_date_window, window_identity
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
    "strategy_source",
    "weighting_mode",
    "price_basis",
    "neutralization_mode",
    "ml_runtime_mode",
    "date_window",
    "degradation_flags",
}

REQUIRED_SUMMARY_COLUMNS = {
    "strategy",
    "total_return",
    "sharpe",
    "max_drawdown",
    "composite_score",
    "strategy_source",
    "weighting_mode",
    "benchmark_status",
    "top1_weight",
    "top5_weight_sum",
    "effective_n",
    "degradation_count",
}

REQUIRED_REPORT_SECTIONS = {
    "## Summary",
    "## Total Table",
    "## Category Tables",
    "## Diagnostics",
    "## Resources",
}

REQUIRED_GOVERNANCE_SUMMARY_COLUMNS = {
    "strategy",
    "strategy_source",
    "weighting_mode",
    "governance_variant",
    "safety_proxy_mode",
    "exposure_cap_mode",
    "trading_freeze_trigger_count",
    "emergency_deleveraging_trigger_count",
    "date_window",
}


def check_file_exists(path: Path, label: str, failures: list[str]):
    if path.exists():
        print(f"[PASS] {label}: {path}")
        return True
    print(f"[FAIL] {label}: missing {path}")
    failures.append(f"{label} missing: {path}")
    return False


def check_report_exists(path: Path, label: str, failures: list[str], pattern: str):
    if path.exists():
        print(f"[PASS] {label}: {path}")
        return True
    candidates = sorted(path.parent.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if candidates:
        latest = candidates[0]
        print(f"[PASS] {label}: configured path missing, using latest {latest}")
        return True
    print(f"[FAIL] {label}: missing {path} and no fallback matching {pattern}")
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
    check_report_exists(FEATURE_MEMORY_REPORT_CSV, "feature memory report", failures, "feature_memory_report_run*.csv")
    check_report_exists(DATA_CONTINUITY_REPORT_CSV, "data continuity report", failures, "data_continuity_report_run*.csv")
    check_report_exists(
        ADJUSTMENT_PTI_QUALITY_CSV,
        "adjustment pti coverage report",
        failures,
        "adjustment_pti_quality_report_run*.csv",
    )

    if feature_ok:
        feature_df = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=list(REQUIRED_FEATURE_COLUMNS))
        check_columns(feature_df, REQUIRED_FEATURE_COLUMNS, "feature parquet", failures)

    strategy_names = list_strategy_names()
    print(f"Configured strategy count: {len(strategy_names)}")
    print(f"Configured strategy names: {strategy_names}")

    missing_strategy_files = []
    empty_strategy_names = []
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
        if selection_df.empty:
            empty_strategy_names.append(strategy_name)
            print(f"[INFO] strategy selection {strategy_name}: empty selection, backtest summary row is optional")
        else:
            try:
                assert_date_window(
                    selection_df,
                    "rebalance_date",
                    start_date=STRATEGY_START_DATE,
                    end_date=STRATEGY_END_DATE,
                    label=f"strategy selection {strategy_name}",
                )
            except ValueError as exc:
                print(f"[FAIL] {exc}")
                failures.append(str(exc))
            else:
                print(f"[PASS] strategy selection {strategy_name}: configured date window enforced")

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
        identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
        for key, expected in identity.items():
            column = f"configured_{key}"
            if column not in summary_df.columns:
                failures.append(f"backtest summary missing date identity column: {column}")
                print(f"[FAIL] backtest summary missing date identity column: {column}")
                continue
            actual = summary_df[column].fillna("").astype(str)
            expected_text = "" if expected is None else str(expected)
            if not actual.eq(expected_text).all():
                failures.append(f"backtest summary contains stale {column} values")
                print(f"[FAIL] backtest summary contains stale {column} values")
            else:
                print(f"[PASS] backtest summary {column}: {expected_text or '-'}")

        summary_strategies = set(summary_df["strategy"].astype(str))
        expected_backtested = set(strategy_names) - set(empty_strategy_names)
        missing_from_summary = sorted(expected_backtested - summary_strategies)
        unexpected_in_summary = sorted(summary_strategies - set(strategy_names))
        if missing_from_summary:
            print(f"[FAIL] backtest summary missing strategies: {missing_from_summary}")
            failures.append(
                f"backtest summary missing configured strategies: {missing_from_summary}"
            )
        elif empty_strategy_names:
            print(
                "[PASS] backtest summary includes all non-empty configured strategies; "
                f"empty selections skipped: {sorted(empty_strategy_names)}"
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

    report_path = RESULT_DIR / "strategy_diagnostic_report.md"
    if check_file_exists(report_path, "strategy diagnostic report", failures):
        report_text = report_path.read_text(encoding="utf-8")
        missing_sections = sorted(section for section in REQUIRED_REPORT_SECTIONS if section not in report_text)
        if missing_sections:
            print(f"[FAIL] strategy diagnostic report missing sections: {missing_sections}")
            failures.append(f"strategy diagnostic report missing sections: {missing_sections}")
        else:
            print("[PASS] strategy diagnostic report contains required sections")

    governance_summary_path = GOVERNANCE_OUTPUT_DIR / "governance_strategy_summary.csv"
    if check_file_exists(governance_summary_path, "governance strategy summary", failures):
        governance_summary_df = pd.read_csv(governance_summary_path)
        check_columns(
            governance_summary_df,
            REQUIRED_GOVERNANCE_SUMMARY_COLUMNS,
            "governance strategy summary",
            failures,
        )

    governance_report_path = GOVERNANCE_OUTPUT_DIR / "governance_strategy_report.md"
    if check_file_exists(governance_report_path, "governance strategy report", failures):
        governance_report_text = governance_report_path.read_text(encoding="utf-8")
        required_governance_sections = REQUIRED_REPORT_SECTIONS | {"## Governance Summary"}
        missing_sections = sorted(section for section in required_governance_sections if section not in governance_report_text)
        if missing_sections:
            print(f"[FAIL] governance strategy report missing sections: {missing_sections}")
            failures.append(f"governance strategy report missing sections: {missing_sections}")
        else:
            print("[PASS] governance strategy report contains required sections")

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
