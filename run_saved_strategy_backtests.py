# -*- coding: utf-8 -*-
"""Run current registered strategies from saved selection parquet files."""
from __future__ import annotations

import pandas as pd

from config import BACKTEST_INITIAL_CASH, BACKTEST_RISK_FREE_RATE, PROCESSED_DIR, RESULT_DIR
from functions.backtest_engine import run_backtest
from main import build_strategy_summary, metrics_to_record
from functions.report_builder import build_strategy_report, save_strategy_report
from functions.strategy_registry import STRATEGY_FACTOR_DESCRIPTIONS, list_strategy_names


def main():
    records = []
    missing = []
    for strategy_name in list_strategy_names():
        selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
        if not selection_path.exists():
            missing.append(str(selection_path))
            continue
        print(f"Backtest saved strategy: {strategy_name}")
        selection = pd.read_parquet(selection_path)
        _, metrics, _ = run_backtest(
            df_selection=selection,
            initial_cash=BACKTEST_INITIAL_CASH,
            risk_free_rate=BACKTEST_RISK_FREE_RATE,
            show_plot=False,
            strategy_name=strategy_name,
            factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(strategy_name),
            compute_theoretical_upper_bound=False,
        )
        records.append(metrics_to_record(strategy_name, metrics))

    if missing:
        raise FileNotFoundError("Missing saved strategy selections:\n" + "\n".join(missing))
    summary = build_strategy_summary(pd.DataFrame(records))
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULT_DIR / "backtest_strategy_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path = save_strategy_report(build_strategy_report(summary))
    print(f"Saved strategy summary: {summary_path}")
    print(f"Saved strategy report: {report_path}")


if __name__ == "__main__":
    main()
