# -*- coding: utf-8 -*-
r"""
Project entry point.

Click Run in Spyder without command-line arguments to execute the complete
restartable workflow in auto_complete_after_vpn.py.  That workflow fetches
external data, rebuilds derived artifacts, runs each strategy in a fresh
low-memory subprocess, generates reports, and verifies the final outputs.

Command-line calls with arguments retain the focused pipeline and low-memory
batch interfaces used by the orchestrator.
"""

import argparse
import gc
import sys

import pandas as pd

from config import (
    ABNORMAL_RETURN_CSV,
    ABNORMAL_RETURN_THRESHOLD,
    ADJUSTMENT_FACTORS_PARQUET,
    ADJUSTMENT_DATA_VERSION,
    BASELINE_VERSION,
    BACKTEST_INITIAL_CASH,
    BACKTEST_RISK_FREE_RATE,
    CLEAN_DAILY_PARQUET,
    CORPORATE_ACTION_DATA_VERSION,
    DATA_VERSION,
    DATA_QUALITY_SUMMARY_CSV,
    ENABLE_HOT_THEME_BIAS,
    ENABLE_EXPERIMENT_TRACKING,
    ENABLE_LEARNING_STRATEGIES,
    ENABLE_PLACEHOLDER_STRATEGIES,
    ENABLE_QUANTUM_INSPIRED_STRATEGIES,
    END_DATE,
    FEATURE_DAILY_PARQUET,
    HOT_THEME_SLOT_RATIO,
    HOT_THEME_WEIGHTS,
    INCLUDE_INSTRUMENT_TYPES,
    INCLUDE_MARKETS,
    LEARNING_STRATEGY_WHITELIST,
    MARKET_CAP_PARQUET,
    PIPELINE_CACHE_JSON,
    PROCESSED_DIR,
    RAW_DAILY_PARQUET,
    READ_LIMIT,
    RESEARCH_ATTEMPT_ID,
    RESEARCH_IDEA_ID,
    RESEARCH_RUN_MODE,
    REPORT_DIR,
    RESULT_DIR,
    RUNS_DIR,
    START_DATE,
    TDX_DIR,
    FAILED_CODES_CSV,
    GOVERNANCE_OUTPUT_DIR,
)
from functions.backtest_engine import run_backtest
from functions.data_sources.adjustment_factors import build_adjustment_factors_quality_report
from functions.evaluation.experiment_tracker import (
    mark_run_completed,
    mark_run_failed,
    start_experiment_run,
)
from functions.clean_daily_data import clean_daily_data
from functions.convert_tdx_daily import convert_tdx_daily, limit_file_rows_balanced
from functions.feature_engineering import generate_daily_features_multi as generate_daily_features
from functions.feature_engineering import (
    generate_multi_strategies,
    generate_one_strategy,
    required_feature_columns_for_strategy,
)
from functions.pipeline_cache import (
    build_signature,
    code_file_fingerprint,
    file_fingerprint,
    mark_step_completed,
    should_skip_step,
)
from functions.progress import progress_iter
from functions.governance import build_research_status, print_runtime_disclosure
from functions.report_utils import print_project_status
from functions.report_builder import build_strategy_report, save_strategy_report
from functions.strategy_registry import STRATEGY_FACTOR_DESCRIPTIONS, STRATEGY_REGISTRY, list_strategy_names
from functions.strategy_selection import run_strategy_selection
from functions.tdx_day_file_reader import collect_tdx_day_files
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

BACKTEST_SHOW_PLOT = False

NON_STRATEGY_PARQUETS = {
    "tdx_daily_raw.parquet",
    "tdx_daily_clean.parquet",
    "tdx_daily_features.parquet",
    "strategy_selection.parquet",
}


def load_saved_strategies():
    """Load saved strategy selection parquet files from data/processed."""
    strategy_files = [
        PROCESSED_DIR / f"{name}.parquet"
        for name in expected_strategy_names()
        if (PROCESSED_DIR / f"{name}.parquet").exists()
    ]
    return {path.stem: pd.read_parquet(path) for path in strategy_files}


def expected_strategy_names():
    return list_strategy_names()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--low-memory", action="store_true", help="Run strategy selection/backtest in small batches.")
    parser.add_argument("--batch-size", type=int, default=1, help="Low-memory batch size. Use 1 safest; 4 maximum recommended.")
    parser.add_argument("--batch-index", type=int, default=0, help="Zero-based low-memory batch index.")
    parser.add_argument("--only", nargs="*", default=None, help="Run explicit strategy names only.")
    parser.add_argument("--sources", nargs="*", default=None, help="Filter strategies by source: rule ml classic_ml quantum_inspired.")
    parser.add_argument("--mode", choices=["pipeline", "select", "backtest", "all"], default="pipeline")
    parser.add_argument("--resume", action="store_true", help="Skip existing low-memory selections/backtests.")
    parser.add_argument("--skip-data-steps", action="store_true", help="In low-memory mode, skip convert/clean/features and use saved feature parquet.")
    parser.add_argument("--governance", action="store_true", help="Run the phase-one daily decision-council backtest.")
    parser.add_argument("--governance-start-date", default=None)
    parser.add_argument("--governance-end-date", default=None)
    parser.add_argument("--governance-max-days", type=int, default=None)
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default="strict")
    parser.add_argument(
        "--governance-variant",
        choices=["rules_based_president", "equal_weight_alpha_ensemble", "rules_based_president_without_sector_cap", "rules_based_president_without_safety_agent"],
        default="rules_based_president",
    )
    return parser.parse_args()


def _build_convert_signature():
    file_rows = collect_tdx_day_files(
        tdx_dir=TDX_DIR,
        include_markets=INCLUDE_MARKETS,
        include_types=INCLUDE_INSTRUMENT_TYPES,
    )
    selected_rows = limit_file_rows_balanced(file_rows, READ_LIMIT)
    payload = {
        "step": "convert_tdx_daily",
        "params": {
            "include_markets": INCLUDE_MARKETS,
            "include_types": INCLUDE_INSTRUMENT_TYPES,
            "read_limit": READ_LIMIT,
        },
        "reader_code": [
            code_file_fingerprint("functions/convert_tdx_daily.py"),
            code_file_fingerprint("functions/tdx_day_file_reader.py"),
        ],
        "source_files": [
            {
                "symbol": row["symbol"],
                "instrument_type": row["instrument_type"],
                "fingerprint": file_fingerprint(row["file_path"]),
            }
            for row in selected_rows
        ],
    }
    return build_signature(payload), len(selected_rows)


def _build_clean_signature():
    payload = {
        "step": "clean_daily_data",
        "params": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "abnormal_return_threshold": ABNORMAL_RETURN_THRESHOLD,
        },
        "raw_input": file_fingerprint(RAW_DAILY_PARQUET),
        "code": [
            code_file_fingerprint("functions/clean_daily_data.py"),
            code_file_fingerprint("functions/quality_checks.py"),
        ],
    }
    return build_signature(payload)


def _build_feature_signature():
    payload = {
        "step": "generate_daily_features",
        "clean_input": file_fingerprint(CLEAN_DAILY_PARQUET),
        "adjustment_input": file_fingerprint(ADJUSTMENT_FACTORS_PARQUET),
        "market_cap_input": file_fingerprint(MARKET_CAP_PARQUET),
        "research_run_mode": RESEARCH_RUN_MODE,
        "code": [
            code_file_fingerprint("functions/feature_engineering.py"),
            code_file_fingerprint("functions/sector_taxonomy.py"),
            code_file_fingerprint("functions/data_sources/adjustment_factors.py"),
            code_file_fingerprint("functions/pricing/price_views.py"),
        ],
    }
    return build_signature(payload)


def _build_strategy_signature():
    strategy_names = expected_strategy_names()
    payload = {
        "step": "generate_multi_strategies",
        "params": {
            "top_n": STRATEGY_TOP_N,
            "freq": STRATEGY_FREQ,
            "start_date": STRATEGY_START_DATE,
            "end_date": STRATEGY_END_DATE,
            "include_types": STRATEGY_INCLUDE_TYPES,
            "enable_hot_theme_bias": ENABLE_HOT_THEME_BIAS,
            "hot_theme_slot_ratio": HOT_THEME_SLOT_RATIO,
            "hot_theme_weights": HOT_THEME_WEIGHTS,
            "enable_learning_strategies": ENABLE_LEARNING_STRATEGIES,
            "learning_strategy_whitelist": LEARNING_STRATEGY_WHITELIST,
            "enable_placeholder_strategies": ENABLE_PLACEHOLDER_STRATEGIES,
            "enable_quantum_inspired_strategies": ENABLE_QUANTUM_INSPIRED_STRATEGIES,
        },
        "feature_input": file_fingerprint(FEATURE_DAILY_PARQUET),
        "strategy_names": strategy_names,
        "code": [
            code_file_fingerprint("functions/feature_engineering.py"),
            code_file_fingerprint("functions/strategy_selection.py"),
            code_file_fingerprint("functions/sector_taxonomy.py"),
            code_file_fingerprint("functions/factors/factor_ml.py"),
            code_file_fingerprint("functions/factors/factor_learning.py"),
        ],
    }
    outputs = [PROCESSED_DIR / f"{name}.parquet" for name in strategy_names]
    outputs.extend(REPORT_DIR / f"strategy_selection_summary_{name}.csv" for name in strategy_names)
    return build_signature(payload), outputs


def _build_backtest_signature(strategy_names):
    payload = {
        "step": "run_backtests",
        "params": {
            "initial_cash": BACKTEST_INITIAL_CASH,
            "risk_free_rate": BACKTEST_RISK_FREE_RATE,
            "show_plot": BACKTEST_SHOW_PLOT,
        },
        "selection_inputs": [
            file_fingerprint(PROCESSED_DIR / f"{name}.parquet") for name in strategy_names
        ],
        "code": [
            code_file_fingerprint("functions/backtest_engine.py"),
            code_file_fingerprint("functions/metrics.py"),
            code_file_fingerprint("functions/execution/order_simulator.py"),
            code_file_fingerprint("functions/execution/execution_rules.py"),
            code_file_fingerprint("functions/execution/cost_model.py"),
        ],
    }
    outputs = [RESULT_DIR / "backtest_strategy_summary.csv"]
    for name in strategy_names:
        outputs.extend(
            [
                RESULT_DIR / f"backtest_daily_result_{name}.csv",
                RESULT_DIR / f"backtest_daily_result_{name}.parquet",
                RESULT_DIR / f"backtest_metrics_{name}.csv",
                RESULT_DIR / f"backtest_holdings_{name}.csv",
                RESULT_DIR / f"backtest_orders_{name}.csv",
                RESULT_DIR / f"equity_curve_{name}.png",
            ]
        )
    learning_strategy_names = [
        name for name in strategy_names
        if name.startswith("classic_ml_") or name.startswith("quantum_inspired_")
    ]
    for name in learning_strategy_names:
        outputs.append(RESULT_DIR / f"backtest_learning_metadata_{name}.csv")
    return build_signature(payload), outputs


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
    if RESEARCH_RUN_MODE != "formal":
        print("\n========== Exploratory metrics only ==========")
        print("P0/formal data requirements are not complete; no strategy ranking is asserted.")
        print(summary_df[["strategy", "total_return", "sharpe", "max_drawdown"]].to_string(index=False))
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


def assert_formal_prerequisites():
    if RESEARCH_RUN_MODE != "formal":
        return
    research_status = build_research_status()
    if not research_status.formal_eligible:
        raise RuntimeError(
            "Formal mode is blocked: "
            f"{research_status.formal_block_reason_code}. "
            f"{research_status.formal_block_reason_detail}"
        )
    if not ADJUSTMENT_FACTORS_PARQUET.exists():
        raise RuntimeError("Formal mode requires published provider adjustment factors")
    if not MARKET_CAP_PARQUET.exists():
        raise RuntimeError("Formal mode requires published real market-cap history")
    factors = pd.read_parquet(ADJUSTMENT_FACTORS_PARQUET)
    quality = build_adjustment_factors_quality_report(factors)
    metric_map = dict(zip(quality["metric"], quality["value"]))
    if int(metric_map.get("validated_factor_rows", 0)) <= 0:
        raise RuntimeError("Formal mode requires validated provider factor rows")


def run_low_memory(args):
    assert_formal_prerequisites()
    print_project_status()

    if not args.skip_data_steps:
        if RUN_STEP_1_CONVERT_TDX:
            print("\n========== STEP 1: convert TDX daily data ==========")
            step_signature, selected_count = _build_convert_signature()
            step_outputs = [RAW_DAILY_PARQUET, FAILED_CODES_CSV]
            if should_skip_step("step_1_convert_tdx", step_signature, step_outputs):
                print(f"Skip step 1: selected {selected_count} files unchanged and raw parquet already exists.")
            else:
                convert_tdx_daily(limit=READ_LIMIT)
                mark_step_completed("step_1_convert_tdx", step_signature, step_outputs)

        if RUN_STEP_2_CLEAN_DATA:
            print("\n========== STEP 2: clean daily data ==========")
            step_signature = _build_clean_signature()
            step_outputs = [CLEAN_DAILY_PARQUET, DATA_QUALITY_SUMMARY_CSV, ABNORMAL_RETURN_CSV]
            if should_skip_step("step_2_clean_data", step_signature, step_outputs):
                print("Skip step 2: raw input and cleaning parameters unchanged.")
            else:
                clean_daily_data()
                mark_step_completed("step_2_clean_data", step_signature, step_outputs)

        if RUN_STEP_3_FEATURES:
            print("\n========== STEP 3: generate features ==========")
            step_signature = _build_feature_signature()
            step_outputs = [FEATURE_DAILY_PARQUET]
            if should_skip_step("step_3_features", step_signature, step_outputs):
                print("Skip step 3: clean data and feature formulas unchanged.")
            else:
                generate_daily_features()
                mark_step_completed("step_3_features", step_signature, step_outputs)

    selected_names = _low_memory_strategy_names(args)
    print("\n========== Low-memory strategy batch ==========")
    print("Selected strategies:", selected_names)
    if not selected_names:
        print("No strategy selected for this batch.")
        return

    if args.mode in {"pipeline", "select", "all"} and RUN_STEP_4_STRATEGY_SELECTION:
        for strategy_name in progress_iter(selected_names, desc="low-memory selection", total=len(selected_names)):
            selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
            if args.resume and selection_path.exists():
                print(f"Skip existing selection: {strategy_name}")
                continue
            _low_memory_generate_selection(strategy_name)
            gc.collect()

    if args.mode in {"pipeline", "backtest", "all"} and RUN_STEP_6_BACKTEST:
        records = []
        for strategy_name in progress_iter(selected_names, desc="low-memory backtest", total=len(selected_names)):
            metrics_path = RESULT_DIR / f"backtest_metrics_{strategy_name}.csv"
            if args.resume and metrics_path.exists():
                print(f"Skip existing backtest: {strategy_name}")
                continue
            records.append(_low_memory_run_backtest(strategy_name))
            gc.collect()
        if records:
            _save_low_memory_summary(records)

    print("\nLow-memory batch completed.")


def _low_memory_strategy_names(args):
    if args.only:
        unknown = sorted(set(args.only) - set(STRATEGY_REGISTRY))
        if unknown:
            raise KeyError(f"Unknown strategies: {unknown}")
        names = list(args.only)
    else:
        names = list_strategy_names()
    if args.sources:
        sources = set(args.sources)
        names = [name for name in names if STRATEGY_REGISTRY[name].source in sources]
    start = max(args.batch_index, 0) * max(args.batch_size, 1)
    end = start + max(args.batch_size, 1)
    return names[start:end] if not args.only else names


def _low_memory_generate_selection(strategy_name):
    import pyarrow.parquet as pq

    schema_cols = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    columns = [col for col in required_feature_columns_for_strategy(strategy_name) if col in schema_cols]
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


def _low_memory_run_backtest(strategy_name):
    selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
    if not selection_path.exists():
        raise FileNotFoundError(f"Missing strategy selection: {selection_path}")
    print(f"\n========== Backtest strategy: {strategy_name} ==========")
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


def _save_low_memory_summary(records):
    batch_df = pd.DataFrame(records)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULT_DIR / "backtest_strategy_summary_batch.csv"
    if output.exists():
        existing = pd.read_csv(output)
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
    summary.to_csv(output, index=False, encoding="utf-8-sig")
    report_file = save_strategy_report(
        build_strategy_report(summary),
        RESULT_DIR / "strategy_diagnostic_report_batch.md",
    )
    print("Saved low-memory batch summary:", output)
    print("Saved low-memory diagnostic report:", report_file)


def main():
    assert_formal_prerequisites()
    run_dir = None
    if ENABLE_EXPERIMENT_TRACKING:
        tracked_inputs = [
            RAW_DAILY_PARQUET,
            CLEAN_DAILY_PARQUET,
            FEATURE_DAILY_PARQUET,
            PIPELINE_CACHE_JSON,
        ]
        config_snapshot = {
            "data_version": DATA_VERSION,
            "adjustment_data_version": ADJUSTMENT_DATA_VERSION,
            "corporate_action_data_version": CORPORATE_ACTION_DATA_VERSION,
            "research_run_mode": RESEARCH_RUN_MODE,
            "idea_id": RESEARCH_IDEA_ID,
            "attempt_id": RESEARCH_ATTEMPT_ID,
            "baseline_version": BASELINE_VERSION,
            "read_limit": READ_LIMIT,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "include_markets": list(INCLUDE_MARKETS),
            "include_instrument_types": list(INCLUDE_INSTRUMENT_TYPES),
            "strategy_top_n": STRATEGY_TOP_N,
            "strategy_freq": STRATEGY_FREQ,
            "strategy_start_date": STRATEGY_START_DATE,
            "strategy_end_date": STRATEGY_END_DATE,
            "enable_hot_theme_bias": ENABLE_HOT_THEME_BIAS,
            "enable_learning_strategies": ENABLE_LEARNING_STRATEGIES,
            "learning_strategy_whitelist": LEARNING_STRATEGY_WHITELIST,
            "enable_placeholder_strategies": ENABLE_PLACEHOLDER_STRATEGIES,
            "enable_quantum_inspired_strategies": ENABLE_QUANTUM_INSPIRED_STRATEGIES,
        }
        run_id, run_dir, _ = start_experiment_run(
            config_snapshot=config_snapshot,
            tracked_inputs=tracked_inputs,
            extra={"module_phase": "module_01_experiment_skeleton"},
        )
        print(f"Run tracking enabled: {run_id}")
        print(f"Run metadata directory: {run_dir}")

    print_project_status()

    try:
        df_features = None
        strategies = {}

        if RUN_STEP_1_CONVERT_TDX:
            print("\n========== STEP 1: convert TDX daily data ==========")
            step_signature, selected_count = _build_convert_signature()
            step_outputs = [RAW_DAILY_PARQUET, FAILED_CODES_CSV]
            if should_skip_step("step_1_convert_tdx", step_signature, step_outputs):
                print(f"Skip step 1: selected {selected_count} files unchanged and raw parquet already exists.")
            else:
                convert_tdx_daily(limit=READ_LIMIT)
                mark_step_completed(
                    "step_1_convert_tdx",
                    step_signature,
                    step_outputs,
                    extra={"selected_file_count": selected_count},
                )

        if RUN_STEP_2_CLEAN_DATA:
            print("\n========== STEP 2: clean daily data ==========")
            step_signature = _build_clean_signature()
            step_outputs = [CLEAN_DAILY_PARQUET, DATA_QUALITY_SUMMARY_CSV, ABNORMAL_RETURN_CSV]
            if should_skip_step("step_2_clean_data", step_signature, step_outputs):
                print("Skip step 2: raw input and cleaning parameters unchanged.")
            else:
                clean_daily_data()
                mark_step_completed("step_2_clean_data", step_signature, step_outputs)

        if RUN_STEP_3_FEATURES:
            print("\n========== STEP 3: generate features ==========")
            step_signature = _build_feature_signature()
            step_outputs = [FEATURE_DAILY_PARQUET]
            if should_skip_step("step_3_features", step_signature, step_outputs):
                print("Skip step 3: clean data and feature formulas unchanged.")
                df_features = pd.read_parquet(FEATURE_DAILY_PARQUET)
            else:
                df_features = generate_daily_features()
                mark_step_completed("step_3_features", step_signature, step_outputs)

        if RUN_STEP_4_STRATEGY_SELECTION:
            print("\n========== STEP 4: generate strategy selections ==========")
            step_signature, step_outputs = _build_strategy_signature()
            if should_skip_step("step_4_strategy_selection", step_signature, step_outputs):
                print("Skip step 4: feature data and strategy formulas unchanged.")
                strategies = load_saved_strategies()
            else:
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

                for name, df_sel in progress_iter(
                    strategies.items(),
                    desc="save selections",
                    total=len(strategies),
                ):
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
                mark_step_completed("step_4_strategy_selection", step_signature, step_outputs)

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

            strategy_names = sorted(strategies)
            step_signature, step_outputs = _build_backtest_signature(strategy_names)
            if should_skip_step("step_6_backtest", step_signature, step_outputs):
                print("Skip step 6: strategy selections and backtest formulas unchanged.")
            else:
                backtest_records = []
                for name, df_sel in progress_iter(
                    strategies.items(),
                    desc="run backtests",
                    total=len(strategies),
                ):
                    print(f"\n========== Backtest strategy: {name} ==========")
                    _, metrics, _ = run_backtest(
                        df_selection=df_sel,
                        initial_cash=BACKTEST_INITIAL_CASH,
                        risk_free_rate=BACKTEST_RISK_FREE_RATE,
                        show_plot=BACKTEST_SHOW_PLOT,
                        strategy_name=name,
                        factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(name),
                        compute_theoretical_upper_bound=False,
                    )
                    backtest_records.append(metrics_to_record(name, metrics))

                summary_df = build_strategy_summary(pd.DataFrame(backtest_records))
                RESULT_DIR.mkdir(parents=True, exist_ok=True)
                summary_file = RESULT_DIR / "backtest_strategy_summary.csv"
                summary_df.to_csv(summary_file, index=False, encoding="utf-8-sig")
                report_text = build_strategy_report(summary_df)
                report_file = save_strategy_report(report_text)
                print_strategy_rankings(summary_df)
                print("Saved strategy ranking summary:", summary_file)
                print("Saved strategy diagnostic report:", report_file)
                mark_step_completed("step_6_backtest", step_signature, step_outputs)

        print("\nSelected pipeline steps completed.")
        if ENABLE_EXPERIMENT_TRACKING and run_dir is not None:
            mark_run_completed(
                run_dir,
                extra={
                    "result_dir": str(RESULT_DIR),
                    "runs_dir": str(RUNS_DIR),
                },
            )
    except Exception as exc:
        if ENABLE_EXPERIMENT_TRACKING and run_dir is not None:
            mark_run_failed(run_dir, str(exc))
        raise


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            from auto_complete_after_vpn import main as run_auto_completion

            print("No command-line arguments detected. Running complete automatic workflow.")
            run_auto_completion()
        else:
            cli_args = parse_args()
            if cli_args.governance:
                from functions.decision_council.runner import run_governance_backtest

                run_governance_backtest(
                    start_date=cli_args.governance_start_date,
                    end_date=cli_args.governance_end_date,
                    max_days=cli_args.governance_max_days,
                    safety_proxy_mode=cli_args.safety_proxy_mode,
                    enable_sector_cap=cli_args.governance_variant != "rules_based_president_without_sector_cap",
                    enable_safety_agent=cli_args.governance_variant != "rules_based_president_without_safety_agent",
                    enable_reputation=cli_args.governance_variant != "equal_weight_alpha_ensemble",
                    output_dir=(
                        GOVERNANCE_OUTPUT_DIR
                        if cli_args.governance_variant == "rules_based_president"
                        else GOVERNANCE_OUTPUT_DIR / cli_args.governance_variant
                    ),
                )
            elif cli_args.low_memory:
                run_low_memory(cli_args)
            else:
                main()
    finally:
        print_runtime_disclosure()
