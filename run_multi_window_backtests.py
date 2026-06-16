# -*- coding: utf-8 -*-
"""Run saved strategy selections across multiple calendar windows."""
from __future__ import annotations

import argparse

import pandas as pd

from config import (
    BACKTEST_INITIAL_CASH,
    BACKTEST_RISK_FREE_RATE,
    MULTI_WINDOW_BACKTEST_REPORT_MD,
    MULTI_WINDOW_BACKTEST_SUMMARY_CSV,
    MULTI_WINDOW_DEFAULT_MONTHS,
    MULTI_WINDOW_DEFAULT_STEP_MONTHS,
    PROCESSED_DIR,
    RESULT_DIR,
    STRATEGY_END_DATE,
    STRATEGY_START_DATE,
    assert_valid_configuration,
)
from functions.backtest_engine import run_backtest
from functions.date_window import generate_calendar_windows
from functions.report_builder import save_strategy_report
from functions.strategy_registry import STRATEGY_FACTOR_DESCRIPTIONS, STRATEGY_REGISTRY, list_strategy_names
from main import build_strategy_summary, metrics_to_record


def main():
    assert_valid_configuration()
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None, help="Explicit strategy names.")
    parser.add_argument("--sources", nargs="*", default=None, help="Filter strategy sources.")
    parser.add_argument("--start-date", default=STRATEGY_START_DATE)
    parser.add_argument("--end-date", default=STRATEGY_END_DATE)
    parser.add_argument("--window-months", type=int, default=MULTI_WINDOW_DEFAULT_MONTHS)
    parser.add_argument("--step-months", type=int, default=MULTI_WINDOW_DEFAULT_STEP_MONTHS)
    parser.add_argument("--limit-windows", type=int, default=None)
    args = parser.parse_args()

    strategy_names = _resolve_strategy_names(args.only, args.sources)
    windows = generate_calendar_windows(
        args.start_date,
        args.end_date,
        window_months=args.window_months,
        step_months=args.step_months,
    )
    if args.limit_windows is not None:
        windows = windows[: max(int(args.limit_windows), 0)]
    if not windows:
        raise SystemExit("No windows resolved.")
    if not strategy_names:
        raise SystemExit("No strategies selected.")

    print("Selected strategies:", strategy_names)
    print("Resolved windows:", windows)

    records = []
    for strategy_name in strategy_names:
        selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
        if not selection_path.exists():
            print(f"Skip {strategy_name}: missing selection file")
            continue
        selection = pd.read_parquet(selection_path)
        if selection.empty:
            print(f"Skip {strategy_name}: empty selection")
            continue
        for window in windows:
            result = _run_window_backtest(
                strategy_name=strategy_name,
                selection=selection,
                start_date=window["start_date"],
                end_date=window["end_date"],
                window_id=window["window_id"],
                window_months=args.window_months,
                step_months=args.step_months,
            )
            if result is not None:
                records.append(result)

    if not records:
        raise SystemExit("No multi-window backtest records were generated.")

    result_df = pd.DataFrame(records)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(MULTI_WINDOW_BACKTEST_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    report_text = build_multi_window_report(result_df)
    save_strategy_report(report_text, MULTI_WINDOW_BACKTEST_REPORT_MD)
    print(f"Saved multi-window summary: {MULTI_WINDOW_BACKTEST_SUMMARY_CSV}")
    print(f"Saved multi-window report: {MULTI_WINDOW_BACKTEST_REPORT_MD}")


def _resolve_strategy_names(only, sources):
    if only:
        unknown = sorted(set(only) - set(STRATEGY_REGISTRY))
        if unknown:
            raise KeyError(f"Unknown strategies: {unknown}")
        names = list(only)
    else:
        names = list_strategy_names()
    if sources:
        source_set = set(sources)
        names = [name for name in names if STRATEGY_REGISTRY[name].source in source_set]
    return names


def _run_window_backtest(*, strategy_name, selection, start_date, end_date, window_id, window_months, step_months):
    try:
        _, metrics, _ = run_backtest(
            df_selection=selection,
            initial_cash=BACKTEST_INITIAL_CASH,
            risk_free_rate=BACKTEST_RISK_FREE_RATE,
            show_plot=False,
            strategy_name=f"{strategy_name}_{window_id}",
            factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(strategy_name),
            compute_theoretical_upper_bound=False,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        print(f"Skip {strategy_name} {window_id}: {exc}")
        return None
    record = metrics_to_record(strategy_name, metrics)
    record["configured_start_date"] = str(start_date)
    record["configured_end_date"] = str(end_date)
    record["date_window"] = f"{start_date} -> {end_date}"
    record["window_id"] = window_id
    record["window_start_date"] = start_date
    record["window_end_date"] = end_date
    record["window_months"] = int(window_months)
    record["step_months"] = int(step_months)
    return record


def build_multi_window_report(result_df):
    result = result_df.copy()
    lines = [
        "# Multi-Window Backtest Report",
        "",
        "## Summary",
        f"- Window count: `{int(result['window_id'].nunique())}`",
        f"- Strategy count: `{int(result['strategy'].nunique())}`",
        "- This report exists to reduce overreliance on the single 2021 study window.",
        "",
        "## Window Records",
        result[
            [
                "strategy",
                "window_id",
                "window_start_date",
                "window_end_date",
                "total_return",
                "sharpe",
                "max_drawdown",
                "benchmark_excess_return",
            ]
        ].to_markdown(index=False),
        "",
        "## Strategy Averages",
    ]
    grouped = (
        result.groupby(["strategy", "strategy_source", "weighting_mode"], dropna=False)
        .agg(
            window_count=("window_id", "nunique"),
            avg_total_return=("total_return", "mean"),
            avg_sharpe=("sharpe", "mean"),
            worst_drawdown=("max_drawdown", "min"),
            avg_benchmark_excess_return=("benchmark_excess_return", "mean"),
        )
        .reset_index()
    )
    grouped = build_strategy_summary(
        grouped.rename(
            columns={
                "avg_total_return": "total_return",
                "avg_sharpe": "sharpe",
                "worst_drawdown": "max_drawdown",
                "avg_benchmark_excess_return": "benchmark_excess_return",
            }
        )
    )
    lines.append(
        grouped[
            [
                "strategy",
                "strategy_source",
                "weighting_mode",
                "window_count",
                "total_return",
                "sharpe",
                "max_drawdown",
                "benchmark_excess_return",
                "composite_score",
            ]
        ].to_markdown(index=False)
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
