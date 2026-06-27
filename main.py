# -*- coding: utf-8 -*-
r"""
Project entry point.

`main.py` is the primary user-facing master switch.

Without arguments it runs the normal local pipeline directly:
convert -> clean -> features -> strategy selection -> view -> backtest.

Pipeline parameters live in `config.py`.
Pipeline step on/off switches live in `pipeline_steps.py`.

The larger restartable orchestrator remains available explicitly through
`--auto-complete`.
"""

import argparse
import gc
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

from config import (
    ABNORMAL_RETURN_CSV,
    ABNORMAL_RETURN_THRESHOLD,
    ADJUSTMENT_FACTORS_PARQUET,
    ADJUSTMENT_DATA_VERSION,
    BASELINE_VERSION,
    BACKTEST_CAPITAL_PROFILES,
    BACKTEST_INITIAL_CASH,
    BACKTEST_RISK_FREE_RATE,
    BACKTEST_SKIPPED_STRATEGIES_CSV,
    BACKTEST_SHOW_PLOT,
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
    RUNTIME_CONFIG_SNAPSHOT_JSON,
    RUNS_DIR,
    START_DATE,
    STRATEGY_PARAMS,
    STRATEGY_PARAMS_VERSION,
    TDX_DIR,
    FAILED_CODES_CSV,
    GOVERNANCE_OUTPUT_DIR,
    STRATEGY_SCORE_COL,
    STRATEGY_TOP_N,
    STRATEGY_FREQ,
    STRATEGY_START_DATE,
    STRATEGY_END_DATE,
    STRATEGY_INCLUDE_TYPES,
    EXPORT_SELECTION_EXCEL,
    PRINT_SELECTION_ROWS,
    CLI_MAIN_BATCH_INDEX,
    CLI_MAIN_BATCH_SIZE,
    CLI_MAIN_GOVERNANCE_VARIANT,
    CLI_MAIN_MODE,
    MAIN_STRATEGY_BOUNDED_PARQUET_GB_THRESHOLD,
    MAIN_STRATEGY_EXECUTION_MODE,
    CLI_MAIN_SAFETY_PROXY_MODE,
    CLI_GOVERNANCE_END_DATE,
    CLI_GOVERNANCE_MAX_DAYS,
    CLI_GOVERNANCE_START_DATE,
    DEFAULT_BACKTEST_CAPITAL_PROFILE,
    assert_valid_configuration,
    backtest_profile_suffix,
    get_backtest_capital_profile,
    strategy_params_hash,
)
from pipeline_steps import (
    RUN_STEP_1_CONVERT_TDX,
    RUN_STEP_2_CLEAN_DATA,
    RUN_STEP_3_FEATURES,
    RUN_STEP_4_STRATEGY_SELECTION,
    RUN_STEP_5_VIEW_SELECTION,
    RUN_STEP_6_BACKTEST,
)
from functions.backtest_engine import run_backtest
from functions.date_window import window_identity
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


NON_STRATEGY_PARQUETS = {
    "tdx_daily_raw.parquet",
    "tdx_daily_clean.parquet",
    "tdx_daily_features.parquet",
    "strategy_selection.parquet",
}


class StrategyTaskProgressWindow:
    """Console-only progress reporter for long-running per-strategy tasks.

    The project UI now uses browser dashboards. This class intentionally avoids
    Tk so Spyder cannot block the kernel on a native window event loop.
    """

    def __init__(self, title="Strategy Progress"):
        self.enabled = True
        self.title = str(title)
        self._started_at = time.time()
        self._last_printed = 0.0
        print(f"{self.title}: waiting to start...")

    def update(self, *, current: int, total: int, strategy_name: str, stage: str, detail: str = ""):
        if not self.enabled:
            return
        total = max(int(total), 1)
        current = max(int(current), 0)
        pct = min(max((current / total) * 100.0, 0.0), 100.0)
        elapsed = int(time.time() - self._started_at)
        now = time.time()
        if now - self._last_printed < 2.0 and current < total:
            return
        self._last_printed = now
        detail_text = f" | {detail}" if detail else ""
        print(
            f"{self.title}: {pct:5.1f}% ({current}/{total}) | "
            f"{stage}: {strategy_name}{detail_text} | elapsed={elapsed}s"
        )

    def close(self):
        self.enabled = False


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


def _main_pipeline_has_enabled_steps():
    return any(
        [
            RUN_STEP_1_CONVERT_TDX,
            RUN_STEP_2_CLEAN_DATA,
            RUN_STEP_3_FEATURES,
            RUN_STEP_4_STRATEGY_SELECTION,
            RUN_STEP_5_VIEW_SELECTION,
            RUN_STEP_6_BACKTEST,
        ]
    )


def _feature_parquet_size_gb() -> float:
    path = Path(FEATURE_DAILY_PARQUET)
    if not path.exists():
        return 0.0
    return path.stat().st_size / (1024 ** 3)


def _check_feature_completeness() -> tuple[bool, str]:
    """Check if existing feature parquet has all columns needed by current strategies.

    Returns (is_complete, reason).
    If is_complete is True, feature generation can be skipped even if
    strategy formulas changed, as long as the needed columns already exist.
    """
    if not FEATURE_DAILY_PARQUET.exists():
        return False, "feature parquet does not exist"

    try:
        import pyarrow.parquet as pq
        existing_columns = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    except Exception:
        return False, "cannot read feature parquet schema"

    strategy_names = expected_strategy_names()
    needed_columns = set()
    for name in strategy_names:
        try:
            needed_columns.update(required_feature_columns_for_strategy(name))
        except Exception:
            pass

    missing = needed_columns - existing_columns
    if missing:
        return False, f"missing {len(missing)} columns: {sorted(missing)[:5]}..."

    return True, f"all {len(needed_columns)} required columns present"


def _resolve_strategy_execution_mode() -> tuple[str, str]:
    configured = str(MAIN_STRATEGY_EXECUTION_MODE).strip().lower()
    if configured == "bounded":
        return "bounded", "configured"

    parquet_size_gb = _feature_parquet_size_gb()
    if parquet_size_gb >= float(MAIN_STRATEGY_BOUNDED_PARQUET_GB_THRESHOLD):
        return "bounded", f"feature parquet {parquet_size_gb:.2f} GiB exceeds threshold"
    return "bounded", "bounded mode is the safe default for main pipeline"


def _save_skipped_backtest_report(rows, *, replace: bool = False):
    if not rows:
        return None
    output = Path(BACKTEST_SKIPPED_STRATEGIES_CSV)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if output.exists() and not replace:
        existing = pd.read_csv(output)
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    frame = frame.drop_duplicates(
        subset=["strategy", "reason", "configured_start_date", "configured_end_date"],
        keep="last",
    )
    frame.to_csv(output, index=False, encoding="utf-8-sig")
    print("Saved skipped backtest report:", output)
    return output


def _skipped_backtest_row(strategy_name, reason):
    identity = window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE)
    return {
        "strategy": strategy_name,
        "reason": str(reason),
        "configured_start_date": identity["start_date"],
        "configured_end_date": identity["end_date"],
    }


def _classify_backtest_skip_reason(exc: Exception) -> str | None:
    message = str(exc)
    if "selection is empty" in message:
        return "empty_selection"
    if "has no selections inside configured date window" in message:
        return "date_window_empty"
    if "df_selection missing required columns" in message:
        return "backtest_input_invalid"
    return None


def _feature_date_filters():
    filters = []
    if STRATEGY_START_DATE is not None:
        filters.append(("date", ">=", pd.Timestamp(STRATEGY_START_DATE)))
    if STRATEGY_END_DATE is not None:
        filters.append(("date", "<=", pd.Timestamp(STRATEGY_END_DATE)))
    return filters or None


def _write_runtime_config_snapshot(config_snapshot, *, run_dir=None):
    targets = [Path(RUNTIME_CONFIG_SNAPSHOT_JSON)]
    if run_dir is not None:
        targets.append(Path(run_dir) / "runtime_config_snapshot.json")
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(config_snapshot, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def parse_args():
    from functions.governance_variant_registry import list_governance_variant_names
    from functions.universe_registry import list_universe_names

    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-complete", action="store_true", help="Run the restartable full orchestrator in auto_complete_after_vpn.py.")
    parser.add_argument("--low-memory", action="store_true", help="Run strategy selection/backtest in small batches.")
    parser.add_argument("--batch-size", type=int, default=CLI_MAIN_BATCH_SIZE, help="Low-memory batch size.")
    parser.add_argument("--batch-index", type=int, default=CLI_MAIN_BATCH_INDEX, help="Zero-based low-memory batch index.")
    parser.add_argument("--only", nargs="*", default=None, help="Run explicit strategy names only.")
    parser.add_argument("--sources", nargs="*", default=None, help="Filter strategies by source: rule ml classic_ml quantum_inspired.")
    parser.add_argument("--mode", choices=["pipeline", "select", "backtest", "all"], default=CLI_MAIN_MODE)
    parser.add_argument("--resume", action="store_true", help="Skip existing low-memory selections/backtests.")
    parser.add_argument("--skip-data-steps", action="store_true", help="In low-memory mode, skip convert/clean/features and use saved feature parquet.")
    parser.add_argument("--governance", action="store_true", help="Run the phase-one daily decision-council backtest.")
    parser.add_argument("--governance-start-date", default=CLI_GOVERNANCE_START_DATE)
    parser.add_argument("--governance-end-date", default=CLI_GOVERNANCE_END_DATE)
    parser.add_argument("--governance-max-days", type=int, default=CLI_GOVERNANCE_MAX_DAYS)
    parser.add_argument(
        "--governance-universe",
        dest="governance_universes",
        action="append",
        choices=list_universe_names(),
        default=None,
        help="Governance stock pool to run. Repeat this option to run multiple review universes.",
    )
    parser.add_argument(
        "--governance-shadow-portfolios",
        dest="governance_shadow_portfolios",
        action="store_true",
        default=None,
        help="Enable expensive per-alpha shadow backtests for governance reputation updates.",
    )
    parser.add_argument(
        "--no-governance-shadow-portfolios",
        dest="governance_shadow_portfolios",
        action="store_false",
        help="Disable per-alpha shadow backtests and keep reputation weights static for a faster governance run.",
    )
    parser.add_argument("--no-live-monitor", action="store_true", help="Disable the low-memory governance metrics window.")
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default=CLI_MAIN_SAFETY_PROXY_MODE)
    parser.add_argument(
        "--capital-profile",
        choices=sorted(BACKTEST_CAPITAL_PROFILES),
        default=DEFAULT_BACKTEST_CAPITAL_PROFILE,
        help="Backtest account profile. Default keeps the legacy 1,000,000 baseline.",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=None,
        help="Override the selected backtest capital profile's initial cash.",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=None,
        help="Override max holdings per rebalance. Use 0 for unlimited.",
    )
    parser.add_argument(
        "--min-cash-buffer",
        type=float,
        default=None,
        help="Override minimum cash buffer kept out of buys.",
    )
    parser.add_argument(
        "--governance-variant",
        choices=list_governance_variant_names(),
        default=CLI_MAIN_GOVERNANCE_VARIANT,
    )
    parser.add_argument("--registry-suite", action="store_true", help="Run the main strategy pipeline and governance main version sequentially.")
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


def _capital_profile_from_args(args):
    return get_backtest_capital_profile(
        getattr(args, "capital_profile", DEFAULT_BACKTEST_CAPITAL_PROFILE),
        initial_cash=getattr(args, "initial_cash", None),
        max_positions_override=(
            getattr(args, "max_positions", None)
            if getattr(args, "max_positions", None) is not None
            else "__profile_default__"
        ),
        min_cash_buffer=getattr(args, "min_cash_buffer", None),
    )


def _backtest_summary_path(capital_profile_name: str) -> Path:
    return RESULT_DIR / f"backtest_strategy_summary{backtest_profile_suffix(capital_profile_name)}.csv"


def _build_backtest_signature(strategy_names, capital_profile):
    suffix = backtest_profile_suffix(capital_profile["name"])
    payload = {
        "step": "run_backtests",
        "params": {
            "capital_profile": capital_profile["name"],
            "initial_cash": capital_profile["initial_cash"],
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
            code_file_fingerprint("functions/execution/trade_pairing.py"),
        ],
    }
    outputs = [_backtest_summary_path(capital_profile["name"])]
    for name in strategy_names:
        outputs.extend(
            [
                RESULT_DIR / f"backtest_daily_result_{name}{suffix}.csv",
                RESULT_DIR / f"backtest_daily_result_{name}{suffix}.parquet",
                RESULT_DIR / f"backtest_metrics_{name}{suffix}.csv",
                RESULT_DIR / f"backtest_holdings_{name}{suffix}.csv",
                RESULT_DIR / f"backtest_orders_{name}{suffix}.csv",
                RESULT_DIR / f"backtest_trade_pairs_{name}{suffix}.csv",
                RESULT_DIR / f"backtest_open_positions_{name}{suffix}.csv",
                RESULT_DIR / f"equity_curve_{name}{suffix}.png",
            ]
        )
    learning_strategy_names = [
        name for name in strategy_names
        if name.startswith("classic_ml_") or name.startswith("quantum_inspired_")
    ]
    for name in learning_strategy_names:
        outputs.append(RESULT_DIR / f"backtest_learning_metadata_{name}{suffix}.csv")
    return build_signature(payload), outputs


def metrics_to_record(strategy_name, metrics):
    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    record = {"strategy": strategy_name}
    spec = STRATEGY_REGISTRY.get(strategy_name)
    record.update({
        f"configured_{key}": value
        for key, value in window_identity(STRATEGY_START_DATE, STRATEGY_END_DATE).items()
    })
    for key, value in metric_map.items():
        record[key] = value
    if spec is not None:
        record.setdefault("strategy_source", spec.source)
        record.setdefault("weighting_mode", "kelly_managed" if spec.source in {"technical", "research", "position_management"} else "equal_weight")

    numeric_cols = [
        "trading_days",
        "final_net_value",
        "total_return",
        "annual_return",
        "annual_volatility",
        "sharpe",
        "max_drawdown",
        "win_rate",
        "trade_win_rate",
        "turnover_ratio",
        "transaction_cost_ratio",
        "blocked_order_count",
        "failed_order_ratio",
        "tax_impact_ratio",
        "frozen_aum_ratio",
        "cash_drag",
        "top1_weight",
        "top5_weight_sum",
        "effective_n",
        "degradation_count",
        "benchmark_excess_return",
        "crowding_top_sector_weight",
        "crowding_hot_sector_weight",
        "crowding_unique_sector_count",
        "exposure_ret_20_tilt",
        "exposure_volatility_20_tilt",
        "exposure_close_to_ma20_tilt",
        "exposure_amount_ratio_20_tilt",
        "training_window_days",
        "training_sample_count",
        "label_purge_periods",
        "prior_p",
        "prior_strength",
        "posterior_alpha",
        "posterior_beta",
        "posterior_sample_count",
        "signal_candidate_count",
        "signal_trigger_count",
        "signal_trigger_rate",
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "capital_initial_cash",
        "capital_min_cash_buffer",
        "capital_max_positions",
        "realized_trade_count",
        "winning_trade_count",
        "losing_trade_count",
        "realized_pnl_amount",
        "unrealized_pnl_amount",
        "open_position_count",
        "inventory_underflow_count",
    ]
    for col in numeric_cols:
        record[col] = pd.to_numeric(record.get(col), errors="coerce")
    return record


def build_strategy_summary(summary_df):
    summary = summary_df.copy()
    inferred_sources = summary.get("strategy", pd.Series("", index=summary.index)).map(
        lambda name: STRATEGY_REGISTRY[name].source if name in STRATEGY_REGISTRY else "unknown"
    )
    existing_sources = summary.get("strategy_source", pd.Series(pd.NA, index=summary.index)).astype("string")
    missing_source_mask = existing_sources.isna() | existing_sources.str.strip().eq("") | existing_sources.str.lower().eq("unknown")
    summary["strategy_source"] = existing_sources.where(~missing_source_mask, inferred_sources).fillna("unknown").astype(str)
    inferred_weighting = summary["strategy_source"].map(
        lambda source: "kelly_managed" if source in {"technical", "research", "position_management"} else ("dynamic_governance" if source == "governance" else "equal_weight")
    )
    existing_weighting = summary.get("weighting_mode", pd.Series(pd.NA, index=summary.index)).astype("string")
    stale_equal_weight_mask = existing_weighting.str.lower().eq("equal_weight") & summary["strategy_source"].isin({"technical", "research", "position_management", "governance"})
    missing_weighting_mask = existing_weighting.isna() | existing_weighting.str.strip().eq("") | existing_weighting.str.lower().eq("unknown") | stale_equal_weight_mask
    summary["weighting_mode"] = existing_weighting.where(~missing_weighting_mask, inferred_weighting).fillna("equal_weight").astype(str)
    summary["return_score"] = summary["total_return"].rank(method="average", pct=True).fillna(0.0)
    summary["sharpe_score"] = summary["sharpe"].rank(method="average", pct=True).fillna(0.0)
    summary["drawdown_score"] = summary["max_drawdown"].rank(method="average", pct=True).fillna(0.0)
    summary["composite_score"] = 100 * (
        0.4 * summary["return_score"]
        + 0.35 * summary["sharpe_score"]
        + 0.25 * summary["drawdown_score"]
    )
    category_order = {
        "rule": 0,
        "technical": 1,
        "research": 1,
        "position_management": 1,
        "governance": 2,
        "ml": 3,
        "classic_ml": 3,
        "quantum_inspired": 3,
        "unknown": 9,
    }
    summary["report_category_order"] = summary["strategy_source"].map(category_order).fillna(9)
    return summary.sort_values(["report_category_order", "composite_score"], ascending=[True, False]).reset_index(drop=True)


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
    progress_window = StrategyTaskProgressWindow(title="Low-memory Strategy Tasks")

    try:
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
            for index, strategy_name in enumerate(
                progress_iter(selected_names, desc="low-memory selection", total=len(selected_names)),
                start=1,
            ):
                progress_window.update(
                    current=index - 1,
                    total=len(selected_names),
                    strategy_name=strategy_name,
                    stage="Selection",
                    detail="Waiting to start",
                )
                selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
                if args.resume and selection_path.exists():
                    print(f"Skip existing selection: {strategy_name}")
                    progress_window.update(
                        current=index,
                        total=len(selected_names),
                        strategy_name=strategy_name,
                        stage="Selection",
                        detail="Skipped existing output",
                    )
                    continue
                _low_memory_generate_selection(
                    strategy_name,
                    progress_hook=lambda stage, detail, idx=index, name=strategy_name: progress_window.update(
                        current=idx - 1,
                        total=len(selected_names),
                        strategy_name=name,
                        stage=f"Selection/{stage}",
                        detail=detail,
                    ),
                )
                progress_window.update(
                    current=index,
                    total=len(selected_names),
                    strategy_name=strategy_name,
                    stage="Selection",
                    detail="Completed",
                )
                gc.collect()

        if args.mode in {"pipeline", "backtest", "all"} and RUN_STEP_6_BACKTEST:
            capital_profile = _capital_profile_from_args(args)
            records = []
            skipped_rows = []
            for index, strategy_name in enumerate(
                progress_iter(selected_names, desc="low-memory backtest", total=len(selected_names)),
                start=1,
            ):
                progress_window.update(
                    current=index - 1,
                    total=len(selected_names),
                    strategy_name=strategy_name,
                    stage="Backtest",
                    detail="Waiting to start",
                )
                metrics_path = RESULT_DIR / f"backtest_metrics_{strategy_name}{backtest_profile_suffix(capital_profile['name'])}.csv"
                if args.resume and metrics_path.exists():
                    print(f"Skip existing backtest: {strategy_name}")
                    progress_window.update(
                        current=index,
                        total=len(selected_names),
                        strategy_name=strategy_name,
                        stage="Backtest",
                        detail="Skipped existing output",
                    )
                    continue
                outcome = _low_memory_run_backtest(
                    strategy_name,
                    capital_profile=capital_profile,
                    progress_hook=lambda stage, detail, idx=index, name=strategy_name: progress_window.update(
                        current=idx - 1,
                        total=len(selected_names),
                        strategy_name=name,
                        stage=f"Backtest/{stage}",
                        detail=detail,
                    ),
                )
                if outcome["status"] == "ok":
                    records.append(outcome["record"])
                    completion_detail = "Completed"
                else:
                    skipped_rows.append(_skipped_backtest_row(strategy_name, outcome["reason"]))
                    completion_detail = f"Skipped: {outcome['reason']}"
                progress_window.update(
                    current=index,
                    total=len(selected_names),
                    strategy_name=strategy_name,
                    stage="Backtest",
                    detail=completion_detail,
                )
                gc.collect()
            if records:
                _save_low_memory_summary(records, capital_profile_name=capital_profile["name"])
            if skipped_rows:
                _save_skipped_backtest_report(skipped_rows)

        print("\nLow-memory batch completed.")
    finally:
        progress_window.close()


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


def _low_memory_generate_selection(strategy_name, progress_hook=None):
    import pyarrow.parquet as pq

    schema_cols = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    columns = [col for col in required_feature_columns_for_strategy(strategy_name) if col in schema_cols]
    if progress_hook is not None:
        progress_hook("load_features", f"Loading {len(columns)} feature columns")
    print(f"Load features for {strategy_name}: {len(columns)} columns")
    features = pd.read_parquet(
        FEATURE_DAILY_PARQUET,
        columns=columns,
        filters=_feature_date_filters(),
    )
    if progress_hook is not None:
        progress_hook("generate_selection", "Computing selection rows")
    selection = generate_one_strategy(
        features,
        strategy_name=strategy_name,
        top_n=STRATEGY_TOP_N,
        freq=STRATEGY_FREQ,
        include_types=STRATEGY_INCLUDE_TYPES,
        start_date=STRATEGY_START_DATE,
        end_date=STRATEGY_END_DATE,
        progress_hook=progress_hook,
    )
    if progress_hook is not None:
        progress_hook("save_selection", f"Saving {len(selection)} selection rows")
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
    if progress_hook is not None:
        progress_hook("selection_done", "Selection completed")
    del features, selection


def _low_memory_run_backtest(
    strategy_name,
    progress_hook=None,
    capital_profile_name=DEFAULT_BACKTEST_CAPITAL_PROFILE,
    capital_profile=None,
):
    capital_profile = capital_profile or get_backtest_capital_profile(capital_profile_name)
    selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
    if not selection_path.exists():
        print(f"Skip backtest {strategy_name}: selection file is missing")
        return {
            "status": "skipped",
            "reason": "missing_selection_file",
        }
    print(f"\n========== Backtest strategy: {strategy_name} ==========")
    if progress_hook is not None:
        progress_hook("load_selection", "Loading saved selection parquet")
    selection = pd.read_parquet(selection_path)
    if selection.empty:
        print(f"Skip backtest {strategy_name}: selection is empty")
        del selection
        return {
            "status": "skipped",
            "reason": "empty_selection",
        }
    try:
        if progress_hook is not None:
            progress_hook("run_backtest", "Running backtest engine")
        _, metrics, _ = run_backtest(
            df_selection=selection,
            initial_cash=capital_profile["initial_cash"],
            risk_free_rate=BACKTEST_RISK_FREE_RATE,
            show_plot=False,
            strategy_name=strategy_name,
            capital_profile_name=capital_profile["name"],
            capital_profile=capital_profile,
            factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(strategy_name),
            compute_theoretical_upper_bound=False,
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
        )
    except ValueError as exc:
        reason = _classify_backtest_skip_reason(exc)
        if reason is None:
            raise
        print(f"Skip backtest {strategy_name}: {reason}")
        return {
            "status": "skipped",
            "reason": reason,
        }
    if progress_hook is not None:
        progress_hook("backtest_done", "回测完成")
    record = metrics_to_record(strategy_name, metrics)
    return {
        "status": "ok",
        "record": record,
    }


def _run_single_governance_variant(
    variant_name: str,
    *,
    start_date: str,
    end_date: str,
    max_days: int | None,
    safety_proxy_mode: str,
    universe_name: str | None = None,
    enable_shadow_portfolios: bool = True,
    show_live_monitor: bool = True,
):
    from config import REGISTRY_FRAMEWORK_VERSION
    from functions.decision_council.runner import run_governance_backtest
    from functions.governance_variant_registry import get_governance_variant_spec
    from functions.universe_registry import get_universe_spec

    variant_spec = get_governance_variant_spec(variant_name)
    selected_universe_name = universe_name or variant_spec.universe_name
    universe_spec = get_universe_spec(selected_universe_name)
    output_dir = GOVERNANCE_OUTPUT_DIR / selected_universe_name / variant_name / variant_spec.alpha_bundle
    return run_governance_backtest(
        start_date=start_date,
        end_date=end_date,
        max_days=max_days,
        safety_proxy_mode=safety_proxy_mode,
        governance_variant=variant_name,
        enable_sector_cap=variant_spec.enable_sector_cap,
        enable_safety_agent=variant_spec.enable_safety_agent,
        enable_reputation=variant_spec.enable_reputation,
        entry_confirmation_mode=variant_spec.extra.get("entry_confirmation_mode", "full"),
        policy_exit_mode=variant_spec.extra.get("exit_mode", "full"),
        selection_weight_mode=variant_spec.extra.get("selection_weight_mode", "reputation_weighted"),
        regime_overlay_mode=variant_spec.extra.get("regime_overlay_mode", "full"),
        risk_hard_gate_enabled=variant_spec.extra.get("risk_hard_gate_enabled", False),
        probability_bucket_mode=variant_spec.extra.get("probability_bucket_mode", "default"),
        output_dir=output_dir,
        universe_name=selected_universe_name,
        universe_mode=universe_spec.mode,
        alpha_bundle=variant_spec.alpha_bundle,
        registry_version=REGISTRY_FRAMEWORK_VERSION,
        target_index_codes=tuple(universe_spec.target_index_codes),
        require_constituents=universe_spec.require_constituents,
        allow_fallback=universe_spec.allow_fallback,
        allowed_instrument_types=tuple(universe_spec.allowed_instrument_types),
        enable_quality_filters=universe_spec.quality_filter_enabled,
        enable_shadow_portfolios=enable_shadow_portfolios,
        show_live_monitor=show_live_monitor,
    )


def run_registry_suite(args):
    selected_universes = _normalize_governance_universes(getattr(args, "governance_universes", None))
    main()
    _run_single_governance_variant(
        "rules_based_president",
        start_date=args.governance_start_date,
        end_date=args.governance_end_date,
        max_days=args.governance_max_days,
        safety_proxy_mode=args.safety_proxy_mode,
        universe_name=selected_universes[0],
        enable_shadow_portfolios=bool(args.governance_shadow_portfolios) if args.governance_shadow_portfolios is not None else True,
        show_live_monitor=not args.no_live_monitor,
    )


def run_full_registry_matrix(args):
    from run_governance_experiments import (
        build_experiment_comparison_report,
        run_alpha_ablation,
        run_universe_ablation,
        save_experiment_comparison_report,
    )

    run_registry_suite(args)

    alpha_results = run_alpha_ablation(
        start_date=args.governance_start_date,
        end_date=args.governance_end_date,
        max_days=args.governance_max_days,
    )
    alpha_comparison = build_experiment_comparison_report(alpha_results)
    alpha_path = save_experiment_comparison_report(alpha_comparison, "alpha_ablation")
    print("Saved alpha ablation summary:", alpha_path)

    universe_results = run_universe_ablation(
        start_date=args.governance_start_date,
        end_date=args.governance_end_date,
        max_days=args.governance_max_days,
    )
    universe_comparison = build_experiment_comparison_report(universe_results)
    universe_path = save_experiment_comparison_report(universe_comparison, "universe_ablation")
    print("Saved universe ablation summary:", universe_path)


DEFAULT_GOVERNANCE_REVIEW_UNIVERSES = ("hs300_csi500_a500_strict", "hs300_strict")


def _normalize_governance_universes(raw_universes) -> tuple[str, ...]:
    from functions.universe_registry import list_universe_names

    if not raw_universes:
        return DEFAULT_GOVERNANCE_REVIEW_UNIVERSES
    if isinstance(raw_universes, str):
        raw_items = raw_universes.split(",")
    else:
        raw_items = []
        for item in raw_universes:
            if isinstance(item, str):
                raw_items.extend(item.split(","))
    available = set(list_universe_names())
    cleaned: list[str] = []
    for item in raw_items:
        name = str(item).strip()
        if not name or name in cleaned:
            continue
        if name not in available:
            raise ValueError(f"Unknown governance universe '{name}'. Available: {sorted(available)}")
        cleaned.append(name)
    return tuple(cleaned) if cleaned else DEFAULT_GOVERNANCE_REVIEW_UNIVERSES


def _month_to_date(value: str | None, *, end_of_month: bool) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 7:
        period = pd.Period(text, freq="M")
        ts = period.to_timestamp(how="end" if end_of_month else "start")
    else:
        ts = pd.Timestamp(text)
    return ts.strftime("%Y-%m-%d")


def _apply_interactive_governance_params(args, selection: dict, tasks: list[str]):
    runtime_args = argparse.Namespace(**vars(args))
    governance_tasks = {
        "governance_active",
        "governance_mainline_review",
        "governance_layer_validation",
        "governance_layer_ablation_suite",
    }
    if not any(task in governance_tasks for task in tasks):
        return runtime_args

    governance = selection.get("governance", {}) if isinstance(selection, dict) else {}
    if not isinstance(governance, dict):
        governance = {}

    runtime_args.governance_universes = _normalize_governance_universes(
        governance.get("universes") or getattr(runtime_args, "governance_universes", None)
    )

    start_date = _month_to_date(governance.get("start_month"), end_of_month=False)
    end_date = _month_to_date(governance.get("end_month"), end_of_month=True)
    if start_date:
        runtime_args.governance_start_date = start_date
    if end_date:
        runtime_args.governance_end_date = end_date
    if pd.Timestamp(runtime_args.governance_start_date) > pd.Timestamp(runtime_args.governance_end_date):
        raise ValueError(
            f"Governance start date is after end date: "
            f"{runtime_args.governance_start_date} > {runtime_args.governance_end_date}"
        )

    max_days = governance.get("max_days")
    if max_days is not None and str(max_days).strip():
        max_days_int = int(str(max_days).strip())
        if max_days_int <= 0:
            raise ValueError("Governance max trading days must be positive.")
        runtime_args.governance_max_days = max_days_int
    if "shadow_portfolios" in governance:
        runtime_args.governance_shadow_portfolios = bool(governance.get("shadow_portfolios"))
    return runtime_args


def _apply_interactive_backtest_params(args, selection: dict):
    runtime_args = argparse.Namespace(**vars(args))
    backtest = selection.get("backtest", {}) if isinstance(selection, dict) else {}
    if not isinstance(backtest, dict):
        return runtime_args
    capital_profile = str(backtest.get("capital_profile", "")).strip()
    if capital_profile:
        runtime_args.capital_profile = capital_profile
    initial_cash = str(backtest.get("initial_cash", "")).strip()
    max_positions = str(backtest.get("max_positions", "")).strip()
    min_cash_buffer = str(backtest.get("min_cash_buffer", "")).strip()
    if initial_cash:
        runtime_args.initial_cash = float(initial_cash)
    if max_positions:
        runtime_args.max_positions = int(max_positions)
    if min_cash_buffer:
        runtime_args.min_cash_buffer = float(min_cash_buffer)
    _capital_profile_from_args(runtime_args)
    return runtime_args


def run_governance_mainline_review_from_main(args):
    """Run the two-universe governance review flow from the main launcher."""
    from build_governance_mainline_report import build_report
    from functions.decision_council.live_monitor import GovernanceLiveMonitor
    from run_governance_experiments import run_single_experiment

    review_universes = _normalize_governance_universes(getattr(args, "governance_universes", None))
    variant_name = "rules_based_president"
    alpha_bundle = "president_core_bundle"
    shared_live_monitor = None
    if not args.no_live_monitor:
        shared_live_monitor = GovernanceLiveMonitor(total_days=1, initial_nav=1.0)

    for universe_name in review_universes:
        print("=" * 72)
        print(f"Running mainline review universe: {universe_name}")
        print("=" * 72)
        run_single_experiment(
            variant_name=variant_name,
            alpha_bundle=alpha_bundle,
            universe_name=universe_name,
            start_date=args.governance_start_date,
            end_date=args.governance_end_date,
            max_days=args.governance_max_days,
            enable_shadow_portfolios=bool(args.governance_shadow_portfolios) if args.governance_shadow_portfolios is not None else True,
            show_live_monitor=not args.no_live_monitor,
            live_monitor=shared_live_monitor,
        )
    report_path, comparison_path = build_report()
    print(f"Saved review report: {report_path}")
    print(f"Saved comparison csv: {comparison_path}")


def run_governance_layer_validation_from_main(args):
    """Run a compact governance line that isolates base signal quality."""
    from functions.decision_council.live_monitor import GovernanceLiveMonitor
    from run_governance_experiments import run_single_experiment

    review_universes = _normalize_governance_universes(getattr(args, "governance_universes", None))
    variant_name = "governance_layer_validation"
    alpha_bundle = "validation_core_bundle"
    shared_live_monitor = None
    if not args.no_live_monitor:
        shared_live_monitor = GovernanceLiveMonitor(total_days=1, initial_nav=1.0)

    for universe_name in review_universes:
        print("=" * 72)
        print(f"Running layer validation universe: {universe_name}")
        print("=" * 72)
        run_single_experiment(
            variant_name=variant_name,
            alpha_bundle=alpha_bundle,
            universe_name=universe_name,
            start_date=args.governance_start_date,
            end_date=args.governance_end_date,
            max_days=args.governance_max_days,
            enable_shadow_portfolios=False,
            show_live_monitor=not args.no_live_monitor,
            live_monitor=shared_live_monitor,
        )


LAYER_ABLATION_SUITE = (
    ("governance_core_base", "validation_core_bundle", "01_core_base"),
    ("governance_core_base", "diagnostic_trend_bundle", "02_trend_only"),
    ("governance_core_base", "diagnostic_reversal_bundle", "03_reversal_only"),
    ("governance_core_base", "diagnostic_orderflow_bundle", "04_orderflow_only"),
    ("governance_core_base", "diagnostic_breakout_bundle", "05_breakout_only"),
    ("governance_core_base", "diagnostic_core_minus_trend_bundle", "06_core_minus_trend"),
    ("governance_core_base", "diagnostic_core_minus_reversal_bundle", "07_core_minus_reversal"),
    ("governance_core_base", "diagnostic_core_minus_orderflow_bundle", "08_core_minus_orderflow"),
    ("governance_core_base", "diagnostic_core_minus_breakout_bundle", "09_core_minus_breakout"),
    ("governance_core_plus_regime", "validation_core_bundle", "10_core_plus_regime"),
    ("governance_core_plus_probability", "validation_core_bundle", "11_core_plus_probability"),
    ("governance_core_plus_complex_exit", "validation_core_bundle", "12_core_plus_complex_exit"),
    ("governance_full_mainline_control", "president_core_bundle", "13_full_mainline_control"),
)


def run_governance_layer_ablation_suite_from_main(args):
    """Run the enhanced module/layer diagnostic suite for the selected universes and window."""
    from functions.decision_council.live_monitor import GovernanceLiveMonitor
    from functions.decision_council.layer_ablation_diagnostics import build_layer_ablation_diagnostics
    from run_governance_experiments import build_output_path, run_single_experiment

    review_universes = _normalize_governance_universes(getattr(args, "governance_universes", None))
    suite_id = pd.Timestamp.now().strftime("suite_%Y%m%d_%H%M%S")
    shared_live_monitor = None
    if not args.no_live_monitor:
        shared_live_monitor = GovernanceLiveMonitor(total_days=1, initial_nav=1.0)
    comparison_rows = []
    for universe_name in review_universes:
        for variant_name, alpha_bundle, suite_step in LAYER_ABLATION_SUITE:
            print("=" * 72)
            print(f"Running enhanced diagnostic step: {suite_step}")
            print(f"  Universe: {universe_name}")
            print(f"  Variant: {variant_name}")
            print(f"  Alpha Bundle: {alpha_bundle}")
            print("=" * 72)
            saved = run_single_experiment(
                variant_name=variant_name,
                alpha_bundle=alpha_bundle,
                universe_name=universe_name,
                start_date=args.governance_start_date,
                end_date=args.governance_end_date,
                max_days=args.governance_max_days,
                enable_shadow_portfolios=False,
                show_live_monitor=not args.no_live_monitor,
                live_monitor=shared_live_monitor,
                output_dir_suffix=suite_id,
            )
            summary_path = saved.get("governance_strategy_summary")
            if summary_path is None:
                summary_path = build_output_path(variant_name, alpha_bundle, universe_name) / suite_id / "governance_strategy_summary.csv"
            try:
                summary = pd.read_csv(summary_path)
            except Exception:
                summary = pd.DataFrame()
            if summary.empty:
                comparison_rows.append(
                    {
                        "suite_step": suite_step,
                        "universe_name": universe_name,
                        "variant_name": variant_name,
                        "alpha_bundle": alpha_bundle,
                        "suite_id": suite_id,
                        "summary_status": "missing_or_empty",
                    }
                )
                continue
            row = summary.iloc[0].to_dict()
            row.update(
                {
                    "suite_step": suite_step,
                    "universe_name": universe_name,
                    "variant_name": variant_name,
                    "alpha_bundle": alpha_bundle,
                    "suite_id": suite_id,
                    "summary_status": "ok",
                }
            )
            comparison_rows.append(row)

    comparison = pd.DataFrame(comparison_rows)
    output_path = RESULT_DIR / "governance" / f"layer_ablation_suite_comparison_{suite_id}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved layer ablation suite comparison: {output_path}")
    diagnostic_paths = build_layer_ablation_diagnostics(
        suite_id=suite_id,
        universe_names=review_universes,
        suite_steps=LAYER_ABLATION_SUITE,
        result_dir=RESULT_DIR,
    )
    for name, path in diagnostic_paths.items():
        print(f"Saved layer diagnostic {name}: {path}")


def _apply_runtime_profile(args, profile_name: str, tasks: list[str]):
    runtime_args = argparse.Namespace(**vars(args))
    profile = str(profile_name or "full").strip().lower()
    governance_tasks = {
        "governance_active",
        "governance_mainline_review",
        "governance_layer_validation",
        "governance_layer_ablation_suite",
    }
    touches_governance = any(task in governance_tasks for task in tasks)

    if profile != "fast" or not touches_governance:
        if touches_governance and runtime_args.governance_shadow_portfolios is None:
            runtime_args.governance_shadow_portfolios = False
        shadow_state = "on" if runtime_args.governance_shadow_portfolios else "off"
        return runtime_args, "full", f"完整历史复核窗口，影子组合={shadow_state}。"

    configured_end = pd.Timestamp(runtime_args.governance_end_date or CLI_GOVERNANCE_END_DATE)
    configured_start = pd.Timestamp(runtime_args.governance_start_date or CLI_GOVERNANCE_START_DATE)
    fast_start = max(configured_start, configured_end - pd.Timedelta(days=365))
    runtime_args.governance_start_date = fast_start.strftime("%Y-%m-%d")
    runtime_args.governance_end_date = configured_end.strftime("%Y-%m-%d")
    runtime_args.governance_max_days = min(int(runtime_args.governance_max_days), 180) if runtime_args.governance_max_days is not None else 180
    if runtime_args.governance_shadow_portfolios is None:
        runtime_args.governance_shadow_portfolios = False
    return (
        runtime_args,
        "fast",
        (
            f"Fast review window: {runtime_args.governance_start_date} -> {runtime_args.governance_end_date}, "
            f"max_days={runtime_args.governance_max_days}, shadow_portfolios=off."
        ),
    )


def launch_interactive_main_menu():
    state_dir = Path(tempfile.gettempdir()) / "tdx_main_launcher"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"selection_{os.getpid()}.json"
    if state_path.exists():
        try:
            state_path.unlink()
        except Exception:
            pass

    launcher_script = Path(__file__).with_name("main_launcher_web.py")
    if not launcher_script.exists():
        print("Browser launcher script is missing.")
        return {}

    proc = subprocess.Popen(
        [sys.executable, "-u", str(launcher_script), str(state_path)],
        cwd=str(Path(__file__).resolve().parent),
    )
    print(f"主启动页已在外部浏览器模式启动（pid={proc.pid}）。")

    selection = {}
    last_wait_notice = time.time()
    while proc.poll() is None:
        if state_path.exists():
            try:
                selection = json.loads(state_path.read_text(encoding="utf-8"))
                break
            except Exception:
                pass
        if time.time() - last_wait_notice >= 15:
            print("等待你在启动页选择任务...")
            last_wait_notice = time.time()
        time.sleep(0.2)

    if not selection and state_path.exists():
        try:
            selection = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            selection = {}

    try:
        state_path.unlink()
    except Exception:
        pass
    return selection


def run_interactive_selection(selection, args):
    tasks = [] if not selection else selection.get("tasks", [])
    profile = "full" if not selection else selection.get("profile", "full")
    if not tasks:
        print("Interactive launcher cancelled.")
        return
    runtime_args = _apply_interactive_backtest_params(args, selection)
    runtime_args = _apply_interactive_governance_params(runtime_args, selection, tasks)
    runtime_args, profile_name, profile_note = _apply_runtime_profile(runtime_args, profile, tasks)
    print(f"启动页运行档位：{profile_name}")
    print(profile_note)
    if (
        "governance_active" in tasks
        or "governance_mainline_review" in tasks
        or "governance_layer_validation" in tasks
        or "governance_layer_ablation_suite" in tasks
    ):
        selected_universes = _normalize_governance_universes(getattr(runtime_args, "governance_universes", None))
        runtime_args.governance_universes = selected_universes
        print(
            "治理任务选择："
            f"universes={list(selected_universes)}, "
            f"start={runtime_args.governance_start_date}, "
            f"end={runtime_args.governance_end_date}, "
            f"max_days={runtime_args.governance_max_days}"
        )

    if "main_pipeline" in tasks:
        main(runtime_args)
    if "governance_active" in tasks:
        selected_universes = _normalize_governance_universes(getattr(runtime_args, "governance_universes", None))
        _run_single_governance_variant(
            "rules_based_president",
            start_date=runtime_args.governance_start_date,
            end_date=runtime_args.governance_end_date,
            max_days=runtime_args.governance_max_days,
            safety_proxy_mode=runtime_args.safety_proxy_mode,
            universe_name=selected_universes[0],
            enable_shadow_portfolios=bool(runtime_args.governance_shadow_portfolios) if runtime_args.governance_shadow_portfolios is not None else True,
            show_live_monitor=not runtime_args.no_live_monitor,
        )
    if "governance_mainline_review" in tasks:
        run_governance_mainline_review_from_main(runtime_args)
    if "governance_layer_validation" in tasks:
        run_governance_layer_validation_from_main(runtime_args)
    if "governance_layer_ablation_suite" in tasks:
        run_governance_layer_ablation_suite_from_main(runtime_args)


def _run_pbo_analysis(strategy_names: list[str]) -> dict | None:
    """Run PBO analysis on completed backtest results."""
    from functions.pbo_cscv import compute_pbo

    strategy_returns = {}
    for name in strategy_names:
        daily_path = RESULT_DIR / f"backtest_daily_result_{name}.parquet"
        if not daily_path.exists():
            daily_path = RESULT_DIR / f"backtest_daily_result_{name}.csv"
        if not daily_path.exists():
            continue
        try:
            daily = pd.read_parquet(daily_path) if str(daily_path).endswith(".parquet") else pd.read_csv(daily_path)
            if "daily_return" in daily.columns and not daily.empty:
                daily["daily_return"] = pd.to_numeric(daily["daily_return"], errors="coerce").fillna(0.0)
                strategy_returns[name] = daily["daily_return"].reset_index(drop=True)
        except Exception:
            pass

    if len(strategy_returns) < 3:
        return None

    # Align return series to same length
    min_len = min(len(s) for s in strategy_returns.values())
    aligned_returns = {name: s.iloc[:min_len] for name, s in strategy_returns.items()}

    return compute_pbo(aligned_returns, n_blocks=16)


def _run_leakage_audit() -> dict | None:
    """Run data leakage audit on the feature parquet."""
    import pyarrow.parquet as pq
    from functions.leakage_detector import run_full_leakage_audit

    if not FEATURE_DAILY_PARQUET.exists():
        return None

    # Read a sample of the feature data for auditing
    schema = pq.read_schema(FEATURE_DAILY_PARQUET)
    all_columns = set(schema.names)

    # Collect all feature columns (excluding labels and metadata)
    feature_columns = []
    label_columns = [c for c in all_columns if c.startswith("future_ret_")]
    meta_columns = {"date", "symbol", "instrument_type", "code", "market"}
    for col in sorted(all_columns):
        if col not in label_columns and col not in meta_columns:
            feature_columns.append(col)

    # Read sample data (first 50000 rows) for statistical checks
    try:
        sample = pd.read_parquet(FEATURE_DAILY_PARQUET)
        if len(sample) > 50000:
            sample = sample.head(50000)
    except MemoryError:
        # If full read fails, try with columns subset
        sample = pd.read_parquet(
            FEATURE_DAILY_PARQUET,
            columns=["date", "symbol", "close"] + [c for c in feature_columns[:20] if c in all_columns],
        )

    return run_full_leakage_audit(
        feature_df=sample,
        feature_columns=feature_columns,
        label_columns=label_columns,
    )


def _save_low_memory_summary(records, capital_profile_name=DEFAULT_BACKTEST_CAPITAL_PROFILE):
    batch_df = pd.DataFrame(records)
    suffix = backtest_profile_suffix(capital_profile_name)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULT_DIR / f"backtest_strategy_summary_batch{suffix}.csv"
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
        RESULT_DIR / f"strategy_diagnostic_report_batch{suffix}.md",
    )
    print("Saved low-memory batch summary:", output)
    print("Saved low-memory diagnostic report:", report_file)


def main(args=None):
    args = args or parse_args()
    assert_formal_prerequisites()
    run_dir = None
    progress_window = StrategyTaskProgressWindow()
    strategy_execution_mode, strategy_execution_reason = _resolve_strategy_execution_mode()
    if ENABLE_EXPERIMENT_TRACKING and _main_pipeline_has_enabled_steps():
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
            "strategy_params_version": STRATEGY_PARAMS_VERSION,
            "strategy_params_hash": strategy_params_hash(),
            "strategy_params": STRATEGY_PARAMS,
            "enable_hot_theme_bias": ENABLE_HOT_THEME_BIAS,
            "enable_learning_strategies": ENABLE_LEARNING_STRATEGIES,
            "learning_strategy_whitelist": LEARNING_STRATEGY_WHITELIST,
            "enable_placeholder_strategies": ENABLE_PLACEHOLDER_STRATEGIES,
            "enable_quantum_inspired_strategies": ENABLE_QUANTUM_INSPIRED_STRATEGIES,
        }
        _write_runtime_config_snapshot(config_snapshot)
        run_id, run_dir, _ = start_experiment_run(
            config_snapshot=config_snapshot,
            tracked_inputs=tracked_inputs,
            extra={"module_phase": "module_01_experiment_skeleton"},
        )
        print(f"Run tracking enabled: {run_id}")
        print(f"Run metadata directory: {run_dir}")
        _write_runtime_config_snapshot(config_snapshot, run_dir=run_dir)

    print_project_status()

    try:
        df_features = None
        strategy_names = expected_strategy_names()
        available_strategy_names = []

        print(
            "Strategy execution mode:",
            strategy_execution_mode,
            f"({strategy_execution_reason})",
        )

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
            else:
                # Smart cache: if feature parquet already has all columns needed
                # by current strategies, skip expensive regeneration
                is_complete, completeness_reason = _check_feature_completeness()
                if is_complete:
                    print(f"Skip step 3: feature parquet already complete ({completeness_reason}).")
                    mark_step_completed("step_3_features", step_signature, step_outputs)
                else:
                    print(f"Regenerating features: {completeness_reason}")
                    df_features = generate_daily_features()
                    mark_step_completed("step_3_features", step_signature, step_outputs)

        if RUN_STEP_4_STRATEGY_SELECTION:
            print("\n========== STEP 4: generate strategy selections ==========")
            step_signature, step_outputs = _build_strategy_signature()
            if should_skip_step("step_4_strategy_selection", step_signature, step_outputs):
                print("Skip step 4: feature data and strategy formulas unchanged.")
                available_strategy_names = [
                    name for name in strategy_names
                    if (PROCESSED_DIR / f"{name}.parquet").exists()
                ]
            else:
                if df_features is not None:
                    del df_features
                    df_features = None
                    gc.collect()

                available_strategy_names = []
                for index, strategy_name in enumerate(
                    progress_iter(
                        strategy_names,
                        desc="generate selections",
                        total=len(strategy_names),
                    ),
                    start=1,
                ):
                    progress_window.update(
                        current=index - 1,
                        total=len(strategy_names),
                        strategy_name=strategy_name,
                        stage="Selection",
                        detail="Waiting to start",
                    )
                    _low_memory_generate_selection(
                        strategy_name,
                        progress_hook=lambda stage, detail, idx=index, name=strategy_name: progress_window.update(
                            current=idx - 1,
                            total=len(strategy_names),
                            strategy_name=name,
                            stage=f"Selection/{stage}",
                            detail=detail,
                        ),
                    )
                    available_strategy_names.append(strategy_name)
                    progress_window.update(
                        current=index,
                        total=len(strategy_names),
                        strategy_name=strategy_name,
                        stage="Selection",
                        detail="Completed",
                    )
                    gc.collect()
                mark_step_completed("step_4_strategy_selection", step_signature, step_outputs)

        if RUN_STEP_5_VIEW_SELECTION:
            print("\n========== STEP 5: view strategy selections ==========")
            view_strategy_selection(
                export_excel=EXPORT_SELECTION_EXCEL,
                print_rows=PRINT_SELECTION_ROWS,
                strategy_names=available_strategy_names or None,
            )

        if RUN_STEP_6_BACKTEST:
            print("\n========== STEP 6: run backtests ==========")
            capital_profile = _capital_profile_from_args(args)
            if not available_strategy_names:
                available_strategy_names = [
                    name for name in strategy_names
                    if (PROCESSED_DIR / f"{name}.parquet").exists()
                ]

            if not available_strategy_names:
                raise RuntimeError("No strategy selections available for backtest")

            available_strategy_names = sorted(available_strategy_names)
            step_signature, step_outputs = _build_backtest_signature(available_strategy_names, capital_profile)
            if should_skip_step("step_6_backtest", step_signature, step_outputs):
                print("Skip step 6: strategy selections and backtest formulas unchanged.")
            else:
                backtest_records = []
                skipped_rows = []
                for index, name in enumerate(
                    progress_iter(
                        available_strategy_names,
                        desc="run backtests",
                        total=len(available_strategy_names),
                    ),
                    start=1,
                ):
                    progress_window.update(
                        current=index - 1,
                        total=len(available_strategy_names),
                        strategy_name=name,
                        stage="Backtest",
                        detail="Waiting to start",
                    )
                    outcome = _low_memory_run_backtest(
                        name,
                        capital_profile=capital_profile,
                        progress_hook=lambda stage, detail, idx=index, strategy_name=name: progress_window.update(
                            current=idx - 1,
                            total=len(available_strategy_names),
                            strategy_name=strategy_name,
                            stage=f"Backtest/{stage}",
                            detail=detail,
                        ),
                    )
                    if outcome["status"] == "ok":
                        backtest_records.append(outcome["record"])
                        completion_detail = "Completed"
                    else:
                        skipped_rows.append(_skipped_backtest_row(name, outcome["reason"]))
                        completion_detail = f"Skipped: {outcome['reason']}"
                    progress_window.update(
                        current=index,
                        total=len(available_strategy_names),
                        strategy_name=name,
                        stage="Backtest",
                        detail=completion_detail,
                    )
                    gc.collect()

                if backtest_records:
                    summary_df = build_strategy_summary(pd.DataFrame(backtest_records))
                    RESULT_DIR.mkdir(parents=True, exist_ok=True)
                    summary_file = _backtest_summary_path(capital_profile["name"])
                    summary_df.to_csv(summary_file, index=False, encoding="utf-8-sig")
                    report_text = build_strategy_report(summary_df)
                    report_output = RESULT_DIR / f"strategy_diagnostic_report{backtest_profile_suffix(capital_profile['name'])}.md"
                    report_file = save_strategy_report(report_text, report_output)
                    print_strategy_rankings(summary_df)
                    print("Saved strategy ranking summary:", summary_file)
                    print("Saved strategy diagnostic report:", report_file)

                    # PBO (Probability of Backtest Overfitting) via CSCV
                    try:
                        from functions.pbo_cscv import pbo_summary_report
                        pbo_result = _run_pbo_analysis(available_strategy_names)
                        if pbo_result is not None:
                            pbo_report_path = RESULT_DIR / "pbo_overfitting_report.md"
                            pbo_report_path.write_text(
                                pbo_summary_report(pbo_result), encoding="utf-8"
                            )
                            print(f"Saved PBO report: {pbo_report_path}")
                            print(f"  PBO = {pbo_result['pbo']:.2%}, mean logit = {pbo_result['mean_logit']:.4f}")
                    except Exception as exc:
                        print(f"PBO analysis skipped: {exc}")

                    # Data leakage audit
                    try:
                        from functions.leakage_detector import leakage_audit_report
                        leakage_result = _run_leakage_audit()
                        if leakage_result is not None:
                            leakage_report_path = RESULT_DIR / "leakage_audit_report.md"
                            leakage_report_path.write_text(
                                leakage_audit_report(leakage_result), encoding="utf-8"
                            )
                            print(f"Saved leakage audit: {leakage_report_path}")
                            if not leakage_result["is_clean"]:
                                print(f"  WARNING: {leakage_result['total_violations']} leakage issue(s) detected!")
                            else:
                                print("  No data leakage detected.")
                    except Exception as exc:
                        print(f"Leakage audit skipped: {exc}")

                    # Decision accuracy analysis
                    try:
                        from functions.decision_accuracy import (
                            build_all_strategies_accuracy_report,
                            plot_all_accuracy,
                            save_accuracy_summary_csv,
                            accuracy_report_markdown,
                        )
                        print("\n--- Decision Accuracy Analysis ---")
                        accuracy_results = build_all_strategies_accuracy_report(available_strategy_names)
                        if accuracy_results:
                            plot_all_accuracy(accuracy_results)
                            save_accuracy_summary_csv(accuracy_results)
                            accuracy_md_path = RESULT_DIR / "decision_accuracy_report.md"
                            accuracy_md_path.write_text(
                                accuracy_report_markdown(accuracy_results), encoding="utf-8"
                            )
                            print(f"Saved accuracy report: {accuracy_md_path}")
                            # Print summary
                            for name, result in sorted(accuracy_results.items()):
                                acc = result.get("overall_accuracy", 0.0)
                                total = result.get("total_decisions", 0)
                                correct = result.get("correct_decisions", 0)
                                print(f"  {name}: {acc:.1%} ({correct}/{total})")
                    except Exception as exc:
                        print(f"Accuracy analysis skipped: {exc}")
                else:
                    print("Skip strategy ranking summary: all candidate backtests were empty.")
                if skipped_rows:
                    _save_skipped_backtest_report(skipped_rows, replace=True)
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
    finally:
        progress_window.close()


if __name__ == "__main__":
    show_runtime_disclosure = not any(arg in {"-h", "--help"} for arg in sys.argv[1:])
    try:
        assert_valid_configuration()
        if len(sys.argv) == 1:
            cli_args = parse_args()
            print("正在浏览器中打开主启动页。")
            tasks = launch_interactive_main_menu()
            run_interactive_selection(tasks, cli_args)
            sys.exit(0)
        cli_args = parse_args()
        if cli_args.auto_complete:
            from auto_complete_after_vpn import main as run_auto_completion

            print("Running explicit auto-complete workflow.")
            run_auto_completion()
        elif cli_args.registry_suite:
            run_registry_suite(cli_args)
        elif cli_args.governance:
            selected_universes = _normalize_governance_universes(getattr(cli_args, "governance_universes", None))
            _run_single_governance_variant(
                cli_args.governance_variant,
                start_date=cli_args.governance_start_date,
                end_date=cli_args.governance_end_date,
                max_days=cli_args.governance_max_days,
                safety_proxy_mode=cli_args.safety_proxy_mode,
                universe_name=selected_universes[0],
                enable_shadow_portfolios=bool(cli_args.governance_shadow_portfolios) if cli_args.governance_shadow_portfolios is not None else True,
                show_live_monitor=not cli_args.no_live_monitor,
            )
        elif cli_args.low_memory:
            run_low_memory(cli_args)
        else:
            main()
    finally:
        if show_runtime_disclosure:
            print_runtime_disclosure()
