# -*- coding: utf-8 -*-
"""
Project entry point.

Runs the local TDX daily-data research pipeline:
1. Convert raw .day files
2. Clean daily data
3. Generate features
4. Generate and save multi-strategy selections
5. Export selection views
6. Run backtests
"""

import pandas as pd

from config import FEATURE_DAILY_PARQUET, PROCESSED_DIR, READ_LIMIT, RESULT_DIR
from functions.backtest_engine import run_backtest
from functions.clean_daily_data import clean_daily_data
from functions.convert_tdx_daily import convert_tdx_daily
from functions.feature_engineering import generate_daily_features_multi as generate_daily_features
from functions.feature_engineering import generate_multi_strategies
from functions.feature_engineering import STRATEGY_FACTOR_DESCRIPTIONS
from functions.report_utils import print_project_status
from functions.strategy_selection import run_strategy_selection
from functions.view_strategy_selection import view_strategy_selection


RUN_STEP_1_CONVERT_TDX = True
RUN_STEP_2_CLEAN_DATA = True
RUN_STEP_3_FEATURES = True
RUN_STEP_4_STRATEGY_SELECTION = True
RUN_STEP_5_VIEW_SELECTION = True
RUN_STEP_6_BACKTEST = True

STRATEGY_SCORE_COL = "score_mom_lowvol"
STRATEGY_TOP_N = 20
STRATEGY_FREQ = "ME"
STRATEGY_START_DATE = "2021-01-01"
STRATEGY_END_DATE = None
STRATEGY_INCLUDE_TYPES = ("stock", "etf_fund")

EXPORT_SELECTION_EXCEL = True
PRINT_SELECTION_ROWS = 30

BACKTEST_INITIAL_CASH = 1.0
BACKTEST_RISK_FREE_RATE = 0.0
BACKTEST_SHOW_PLOT = True

NON_STRATEGY_PARQUETS = {
    "tdx_daily_raw.parquet",
    "tdx_daily_clean.parquet",
    "tdx_daily_features.parquet",
}


def load_saved_strategies():
    """Load saved strategy selection parquet files from data/processed."""
    strategy_files = sorted(
        path for path in PROCESSED_DIR.glob("*.parquet")
        if path.name not in NON_STRATEGY_PARQUETS
    )
    return {path.stem: pd.read_parquet(path) for path in strategy_files}


def metrics_to_record(strategy_name, metrics):
    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    record = {"strategy": strategy_name}
    for key, value in metric_map.items():
        record[key] = value

    numeric_cols = [
        "trading_days",
        "final_net_value",
        "total_return",
        "annual_return",
        "annual_volatility",
        "sharpe",
        "max_drawdown",
        "win_rate",
    ]
    for col in numeric_cols:
        record[col] = pd.to_numeric(record.get(col), errors="coerce")
    return record


def build_strategy_summary(summary_df):
    summary = summary_df.copy()
    summary["return_score"] = summary["total_return"].rank(method="average", pct=True).fillna(0.0)
    summary["sharpe_score"] = summary["sharpe"].rank(method="average", pct=True).fillna(0.0)
    summary["drawdown_score"] = summary["max_drawdown"].rank(method="average", pct=True).fillna(0.0)
    summary["composite_score"] = 100 * (
        0.4 * summary["return_score"]
        + 0.35 * summary["sharpe_score"]
        + 0.25 * summary["drawdown_score"]
    )
    return summary.sort_values("composite_score", ascending=False).reset_index(drop=True)


def print_strategy_rankings(summary_df):
    if summary_df.empty:
        print("\n========== Backtest ranking summary ==========")
        print("No backtest summary rows available.")
        return

    def print_block(title, ranked_df, primary_col):
        print(f"\n{title}")
        for _, row in ranked_df.iterrows():
            if primary_col in {"total_return", "annual_return", "annual_volatility", "max_drawdown", "win_rate"}:
                primary_value = f"{row[primary_col]:.2%}"
            else:
                primary_value = f"{row[primary_col]:.4f}"
            print(
                f"{row['strategy']}: "
                f"累计收益={row['total_return']:.2%}, "
                f"夏普={row['sharpe']:.4f}, "
                f"最大回撤={row['max_drawdown']:.2%}, "
                f"{primary_col}={primary_value}"
            )

    print("\n========== Backtest ranking summary ==========")
    print_block(
        "累计收益前五",
        summary_df.sort_values("total_return", ascending=False).head(5),
        "total_return",
    )
    print_block(
        "夏普率前五",
        summary_df.sort_values("sharpe", ascending=False).head(5),
        "sharpe",
    )
    print_block(
        "最大回撤最低前五",
        summary_df.sort_values("max_drawdown", ascending=False).head(5),
        "max_drawdown",
    )
    print_block(
        "综合分前五",
        summary_df.sort_values("composite_score", ascending=False).head(5),
        "composite_score",
    )


def main():
    print_project_status()

    df_features = None
    strategies = {}

    if RUN_STEP_1_CONVERT_TDX:
        print("\n========== STEP 1: convert TDX daily data ==========")
        convert_tdx_daily(limit=READ_LIMIT)

    if RUN_STEP_2_CLEAN_DATA:
        print("\n========== STEP 2: clean daily data ==========")
        clean_daily_data()

    if RUN_STEP_3_FEATURES:
        print("\n========== STEP 3: generate features ==========")
        df_features = generate_daily_features()

    if RUN_STEP_4_STRATEGY_SELECTION:
        print("\n========== STEP 4: generate strategy selections ==========")
        if df_features is None:
            df_features = pd.read_parquet(FEATURE_DAILY_PARQUET)

        strategies = generate_multi_strategies(
            df_features,
            top_n=STRATEGY_TOP_N,
            freq=STRATEGY_FREQ,
            include_types=STRATEGY_INCLUDE_TYPES,
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
        )

        for name, df_sel in strategies.items():
            run_strategy_selection(
                df_features=df_features,
                df_selection=df_sel,
                score_col=STRATEGY_SCORE_COL,
                top_n=STRATEGY_TOP_N,
                freq=STRATEGY_FREQ,
                include_types=STRATEGY_INCLUDE_TYPES,
                start_date=STRATEGY_START_DATE,
                end_date=STRATEGY_END_DATE,
                strategy_name=name,
            )

    if RUN_STEP_5_VIEW_SELECTION:
        print("\n========== STEP 5: view strategy selections ==========")
        view_strategy_selection(
            export_excel=EXPORT_SELECTION_EXCEL,
            print_rows=PRINT_SELECTION_ROWS,
            strategy_names=list(strategies) if strategies else None,
        )

    if RUN_STEP_6_BACKTEST:
        print("\n========== STEP 6: run backtests ==========")
        if not strategies:
            strategies = load_saved_strategies()

        if not strategies:
            raise RuntimeError("No strategy selections available for backtest")

        backtest_records = []
        for name, df_sel in strategies.items():
            print(f"\n========== Backtest strategy: {name} ==========")
            _, metrics, _ = run_backtest(
                df_selection=df_sel,
                initial_cash=BACKTEST_INITIAL_CASH,
                risk_free_rate=BACKTEST_RISK_FREE_RATE,
                show_plot=BACKTEST_SHOW_PLOT,
                strategy_name=name,
                factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(name),
            )
            backtest_records.append(metrics_to_record(name, metrics))

        summary_df = build_strategy_summary(pd.DataFrame(backtest_records))
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        summary_file = RESULT_DIR / "backtest_strategy_summary.csv"
        summary_df.to_csv(summary_file, index=False, encoding="utf-8-sig")
        print_strategy_rankings(summary_df)
        print("Saved strategy ranking summary:", summary_file)

    print("\nSelected pipeline steps completed.")


if __name__ == "__main__":
    main()
