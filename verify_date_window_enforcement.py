# -*- coding: utf-8 -*-
"""Regression checks proving configured dates constrain persisted and backtested data."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.date_window import assert_date_window, filter_date_window, normalize_date_window


def main():
    failures = []
    _check_window_helpers(failures)
    _check_selection_persistence(failures)
    _check_backtest_window(failures)
    if failures:
        raise AssertionError("\n".join(failures))
    print("[PASS] configured date windows are enforced across selection and backtest")


def _check_window_helpers(failures):
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2020-12-31", "2021-01-04", "2021-12-31", "2022-01-04"])}
    )
    filtered = filter_date_window(frame, "date", "2021-01-01", "2021-12-31")
    if filtered["date"].dt.year.tolist() != [2021, 2021]:
        failures.append("shared date-window filter did not retain only 2021 rows")
    try:
        normalize_date_window("2022-01-01", "2021-12-31")
    except ValueError:
        pass
    else:
        failures.append("invalid reversed date window was not rejected")


def _check_selection_persistence(failures):
    import functions.strategy_selection as module

    selection = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2020-12-31", "2021-06-30", "2022-01-03"]),
            "rank": [1, 1, 1],
            "symbol": ["sh600000"] * 3,
            "score": [1.0, 1.0, 1.0],
            "weight": [0.05, 0.05, 0.05],
        }
    )
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        old_processed = module.PROCESSED_DIR
        old_report = module.REPORT_DIR
        module.PROCESSED_DIR = temp / "processed"
        module.REPORT_DIR = temp / "reports"
        module.PROCESSED_DIR.mkdir()
        module.REPORT_DIR.mkdir()
        try:
            saved = module.run_strategy_selection(
                df_selection=selection,
                strategy_name="date_window_test",
                start_date="2021-01-01",
                end_date="2021-12-31",
            )
        finally:
            module.PROCESSED_DIR = old_processed
            module.REPORT_DIR = old_report
    if len(saved) != 1 or saved["rebalance_date"].iloc[0] != pd.Timestamp("2021-06-30"):
        failures.append("strategy persistence allowed rows outside the configured window")
    if saved["configured_start_date"].iloc[0] != "2021-01-01":
        failures.append("strategy persistence did not record its configured date identity")


def _check_backtest_window(failures):
    import functions.backtest_engine as module

    feature_dates = pd.bdate_range("2020-12-28", "2022-01-07")
    feature = pd.DataFrame(
        {
            "date": feature_dates,
            "symbol": "sh600000",
            "close": 10.0 + pd.Series(range(len(feature_dates)), dtype=float) * 0.01,
            "close_nominal": 10.0 + pd.Series(range(len(feature_dates)), dtype=float) * 0.01,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "amount": 10_000_000.0,
            "volume": 1_000_000.0,
            "is_trading": True,
            "rough_limit_up": False,
            "rough_limit_down": False,
            "instrument_type": "stock",
        }
    )
    selection = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2020-12-31", "2021-01-04", "2022-01-03"]),
            "symbol": ["sh600000"] * 3,
            "weight": [0.05, 0.05, 0.05],
            "instrument_type": ["stock"] * 3,
        }
    )
    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        feature_path = temp / "features.parquet"
        feature.to_parquet(feature_path, index=False)
        old_feature = module.FEATURE_DAILY_PARQUET
        old_result = module.RESULT_DIR
        old_cache = module._FEATURE_DATA_CACHE
        module.FEATURE_DAILY_PARQUET = feature_path
        module.RESULT_DIR = temp / "results"
        module._FEATURE_DATA_CACHE = None
        try:
            daily, metrics, _ = module.run_backtest(
                selection,
                initial_cash=100_000.0,
                max_weight=0.05,
                show_plot=False,
                strategy_name="date_window_test",
                compute_theoretical_upper_bound=False,
                start_date="2021-01-01",
                end_date="2021-12-31",
            )
        finally:
            module.FEATURE_DAILY_PARQUET = old_feature
            module.RESULT_DIR = old_result
            module._FEATURE_DATA_CACHE = old_cache
    try:
        assert_date_window(daily, "date", "2021-01-01", "2021-12-31", "backtest output")
    except ValueError as exc:
        failures.append(str(exc))
    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    if metric_map.get("configured_start_date") != "2021-01-01":
        failures.append("backtest metrics did not record configured_start_date")
    if metric_map.get("configured_end_date") != "2021-12-31":
        failures.append("backtest metrics did not record configured_end_date")


if __name__ == "__main__":
    main()
