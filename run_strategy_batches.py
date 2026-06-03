# -*- coding: utf-8 -*-
"""Low-memory batch runner for strategy generation and saved-strategy backtests."""
from __future__ import annotations

import argparse
import gc

import pandas as pd
import pyarrow.parquet as pq

from config import (
    BACKTEST_INITIAL_CASH,
    BACKTEST_RISK_FREE_RATE,
    FEATURE_DAILY_PARQUET,
    PROCESSED_DIR,
    RESULT_DIR,
)
from functions.backtest_engine import run_backtest
from functions.governance import print_runtime_disclosure
from functions.feature_engineering import (
    generate_one_strategy,
    required_feature_columns_for_strategy,
)
from functions.report_builder import build_strategy_report, save_strategy_report
from functions.strategy_registry import STRATEGY_FACTOR_DESCRIPTIONS, STRATEGY_REGISTRY, list_strategy_names
from functions.strategy_selection import run_strategy_selection


STRATEGY_TOP_N = 20
STRATEGY_FREQ = "ME"
STRATEGY_START_DATE = "2021-01-01"
STRATEGY_END_DATE = None
STRATEGY_INCLUDE_TYPES = ("stock", "etf_fund")
STRATEGY_SCORE_COL = "score_mom_lowvol"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["select", "backtest", "all"], default="all")
    parser.add_argument("--batch-size", type=int, default=1, help="Use 1 for low memory; 4 is the practical upper bound.")
    parser.add_argument("--offset", type=int, default=0, help="Zero-based batch offset.")
    parser.add_argument("--batch-index", type=int, default=None, help="Alternative to --offset: offset=batch_index*batch_size.")
    parser.add_argument("--only", nargs="*", default=None, help="Explicit strategy names.")
    parser.add_argument("--sources", nargs="*", default=None, help="Filter source types: rule ml classic_ml quantum_inspired.")
    parser.add_argument("--resume", action="store_true", help="Skip existing outputs for the selected mode.")
    parser.add_argument("--smoke", action="store_true", help="Run the smallest quick check: first strategy in the resolved batch.")
    args = parser.parse_args()

    strategy_names = _resolve_strategy_names(args.only, args.sources)
    if args.smoke:
        strategy_names = strategy_names[:1]
    else:
        start = max(args.offset, 0)
        if args.batch_index is not None:
            start = max(args.batch_index, 0) * max(args.batch_size, 1)
        end = start + max(args.batch_size, 1)
        strategy_names = strategy_names[start:end]

    if not strategy_names:
        print("No strategies selected.")
        return
    print("Selected strategies:", strategy_names)

    if args.mode in {"select", "all"}:
        for strategy_name in strategy_names:
            if args.resume and (PROCESSED_DIR / f"{strategy_name}.parquet").exists():
                print(f"Skip existing selection: {strategy_name}")
                continue
            _generate_and_save_selection(strategy_name)
            gc.collect()

    if args.mode in {"backtest", "all"}:
        records = []
        for strategy_name in strategy_names:
            metrics_path = RESULT_DIR / f"backtest_metrics_{strategy_name}.csv"
            if args.resume and metrics_path.exists():
                print(f"Skip existing backtest: {strategy_name}")
                continue
            record = _run_one_backtest(strategy_name)
            records.append(record)
            gc.collect()
        if records:
            _append_batch_summary(records)


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


def _generate_and_save_selection(strategy_name):
    columns = _existing_columns(required_feature_columns_for_strategy(strategy_name))
    print(f"Load features for {strategy_name}: {len(columns)} columns")
    features = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=columns)
    selection = generate_one_strategy(
        features,
        strategy_name=strategy_name,
        top_n=STRATEGY_TOP_N,
        freq=STRATEGY_FREQ,
        include_types=STRATEGY_INCLUDE_TYPES,
        start_date=STRATEGY_START_DATE,
        end_date=STRATEGY_END_DATE,
    )
    print(f"Save selection {strategy_name}: rows={len(selection)}")
    run_strategy_selection(
        df_features=features,
        df_selection=selection,
        score_col=STRATEGY_SCORE_COL,
        top_n=STRATEGY_TOP_N,
        freq=STRATEGY_FREQ,
        include_types=STRATEGY_INCLUDE_TYPES,
        start_date=STRATEGY_START_DATE,
        end_date=STRATEGY_END_DATE,
        strategy_name=strategy_name,
    )
    del features, selection


def _run_one_backtest(strategy_name):
    selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
    if not selection_path.exists():
        raise FileNotFoundError(f"Missing selection file: {selection_path}")
    print(f"Backtest {strategy_name}")
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
    record = metrics_to_record(strategy_name, metrics)
    del selection, metrics
    return record


def _append_batch_summary(records):
    batch_df = pd.DataFrame(records)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    batch_path = RESULT_DIR / "backtest_strategy_summary_batch.csv"
    if batch_path.exists():
        existing = pd.read_csv(batch_path)
        if "execution_model_version" in batch_df.columns:
            current_versions = set(batch_df["execution_model_version"].dropna().astype(str))
            if "execution_model_version" not in existing.columns:
                existing = existing.iloc[0:0].copy()
            else:
                existing = existing[
                    existing["execution_model_version"].astype(str).isin(current_versions)
                ]
        if not existing.empty:
            batch_df = pd.concat([existing, batch_df], ignore_index=True)
        batch_df = batch_df.drop_duplicates(subset=["strategy"], keep="last")
    summary = build_strategy_summary(batch_df)
    summary.to_csv(batch_path, index=False, encoding="utf-8-sig")
    save_strategy_report(build_strategy_report(summary), RESULT_DIR / "strategy_diagnostic_report_batch.md")
    print(f"Saved batch summary: {batch_path}")


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


def metrics_to_record(strategy_name, metrics):
    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    record = {"strategy": strategy_name}
    for key, value in metric_map.items():
        record[key] = value
    for col in [
        "trading_days",
        "final_net_value",
        "total_return",
        "annual_return",
        "annual_volatility",
        "sharpe",
        "max_drawdown",
        "win_rate",
    ]:
        record[col] = pd.to_numeric(record.get(col), errors="coerce")
    return record


def _existing_columns(columns):
    schema_cols = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    return [col for col in columns if col in schema_cols]


if __name__ == "__main__":
    try:
        main()
    finally:
        print_runtime_disclosure()
