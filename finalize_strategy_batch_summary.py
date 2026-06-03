# -*- coding: utf-8 -*-
"""Publish a complete strategy summary only after every active strategy reruns."""
from __future__ import annotations

import pandas as pd

from config import EXECUTION_MODEL_VERSION, RESULT_DIR
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
    expected = set(list_strategy_names())
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


if __name__ == "__main__":
    main()
