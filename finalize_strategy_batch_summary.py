# -*- coding: utf-8 -*-
"""Publish a complete strategy summary only after every active strategy reruns."""
from __future__ import annotations

import pandas as pd

from config import (
    BACKTEST_SKIPPED_STRATEGIES_CSV,
    EXECUTION_MODEL_VERSION,
    PROCESSED_DIR,
    RESULT_DIR,
    STRATEGY_END_DATE,
    STRATEGY_START_DATE,
)
from functions.date_window import assert_date_window, window_identity
from functions.report_builder import build_strategy_report, save_strategy_report
from functions.strategy_registry import list_strategy_names


def main():
    batch_path = RESULT_DIR / "backtest_strategy_summary_batch.csv"
    if not batch_path.exists():
        raise FileNotFoundError(f"Missing batch summary: {batch_path}")
    summary = pd.read_csv(batch_path)
    if "execution_model_version" not in summary.columns:
        raise ValueError("Batch summary is missing execution_model_version")
    summary = summary[summary["execution_model_version"].astype(str) == EXECUTION_MODEL_VERSION].copy()
    identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    for key, value in identity.items():
        column = f"configured_{key}"
        if column not in summary.columns:
            summary = summary.iloc[0:0].copy()
            break
        expected = "" if value is None else str(value)
        summary = summary[summary[column].fillna("").astype(str) == expected]
    expected, skipped_empty, skipped_missing = _expected_backtested_strategy_names()
    summary = _attach_missing_metric_records(summary, expected)
    actual = set(summary["strategy"].astype(str))
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"Strategy batch summary is incomplete: missing={missing}, unexpected={unexpected}")
    summary = summary.drop_duplicates(subset=["strategy"], keep="last")
    summary_path = RESULT_DIR / "backtest_strategy_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path = save_strategy_report(build_strategy_report(summary))
    print("Published complete strategy summary:", summary_path)
    print("Published complete diagnostic report:", report_path)
    if skipped_empty:
        print("Skipped empty-selection strategies:", sorted(skipped_empty))
    if skipped_missing:
        print("Skipped missing-selection strategies:", sorted(skipped_missing))


def _expected_backtested_strategy_names():
    expected = set()
    skipped_empty = []
    skipped_missing = []
    skipped_reasons = _load_skipped_strategy_reasons()
    for strategy_name in list_strategy_names():
        reason = skipped_reasons.get(strategy_name)
        if reason in {
            "empty_selection",
            "missing_selection_file",
            "date_window_empty",
            "backtest_input_invalid",
        }:
            if reason == "missing_selection_file":
                skipped_missing.append(strategy_name)
            else:
                skipped_empty.append(strategy_name)
            continue
        selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
        if not selection_path.exists():
            skipped_missing.append(strategy_name)
            continue
        selection = pd.read_parquet(selection_path)
        if selection.empty:
            skipped_empty.append(strategy_name)
            continue
        assert_date_window(
            selection,
            "rebalance_date",
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
            label=f"saved selection {strategy_name}",
        )
        expected.add(strategy_name)
    return expected, skipped_empty, skipped_missing


def _load_skipped_strategy_reasons() -> dict[str, str]:
    path = BACKTEST_SKIPPED_STRATEGIES_CSV
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    required = {"strategy", "reason", "configured_start_date", "configured_end_date"}
    if not required.issubset(frame.columns):
        return {}
    identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    filtered = frame.copy()
    for key, value in identity.items():
        column = f"configured_{key}"
        expected = "" if value is None else str(value)
        filtered = filtered[filtered[column].fillna("").astype(str) == expected]
    if filtered.empty:
        return {}
    filtered = filtered.drop_duplicates(subset=["strategy"], keep="last")
    return dict(zip(filtered["strategy"].astype(str), filtered["reason"].astype(str)))


def _attach_missing_metric_records(summary: pd.DataFrame, expected: set[str]) -> pd.DataFrame:
    actual = set(summary["strategy"].astype(str)) if not summary.empty and "strategy" in summary.columns else set()
    missing = sorted(expected - actual)
    records = []
    for strategy_name in missing:
        metrics_path = RESULT_DIR / f"backtest_metrics_{strategy_name}.csv"
        if not metrics_path.exists():
            continue
        metrics = pd.read_csv(metrics_path)
        record = {"strategy": strategy_name}
        record.update(dict(zip(metrics["metric"], metrics["value"])))
        identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
        if any(
            str(record.get(f"configured_{key}", "")) != str(value)
            for key, value in identity.items()
        ):
            continue
        record["execution_model_version"] = EXECUTION_MODEL_VERSION
        records.append(record)
    if not records:
        return summary
    return pd.concat([summary, pd.DataFrame(records)], ignore_index=True, sort=False)


if __name__ == "__main__":
    main()
