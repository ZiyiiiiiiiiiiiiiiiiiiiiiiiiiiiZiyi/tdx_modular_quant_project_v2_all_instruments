# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    CLEAN_DAILY_PARQUET,
    ENABLE_HOT_THEME_BIAS,
    FEATURE_DAILY_PARQUET,
    FEATURE_COVERAGE_REPORT_CSV,
    FEATURE_DOWNCAST_FLOATS,
    FEATURE_MEMORY_REPORT_CSV,
    MODEL_TRAINING_DIAGNOSTICS_CSV,
    FEATURE_PTI_ADJUSTMENT_MIN_COVERAGE_RATIO,
    FEATURE_DISTRIBUTION_REPORT_CSV,
    FEATURE_REGISTRY_REPORT_CSV,
    FEATURE_STORAGE_MODE,
    FEATURE_STABILITY_REPORT_CSV,
    ENABLE_PRE_SCREEN_CANDIDATE_FACTOR_POOL,
    HOT_THEME_SLOT_RATIO,
    HOT_THEME_WEIGHTS,
    FORMAL_MODE_NAME,
    MARKET_CAP_PARQUET,
    RESEARCH_RUN_MODE,
    STRATEGY_FREQ_OVERRIDES,
    STRATEGY_MIN_SCORE_PERCENTILE,
)
from functions.data_sources.adjustment_factors import (
    attach_adjustment_factors_to_daily,
    save_adjustment_pti_coverage_report,
)
from functions.benchmark import save_investable_benchmark_report
from functions.factor_registry import default_factor_registry
from functions.feature_diagnostics import (
    build_feature_coverage_report,
    build_feature_distribution_report,
    build_feature_stability_report,
)
from functions.feature_normalization import (
    neutralize_by_group_and_size,
    robust_scale_cross_section,
    winsorize_cross_section,
    zscore_cross_section,
)
from functions.factors.factor_learning import generate_learning_module_scores, generate_learning_strategy_scores
from functions.factors.factor_candidate_pool import append_candidate_factors, base_candidate_factor_columns
from functions.factors.factor_ml import compute_factor as compute_ml_factor
from functions.labels import apply_default_labels
from functions.pricing.price_views import (
    POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS,
    attach_nominal_price_columns,
    attach_point_in_time_adjusted_price_columns,
)
from functions.progress import progress_iter, progress_step
from functions.sector_taxonomy import attach_sector_labels
from functions.strategy_registry import STRATEGY_REGISTRY
from functions.strategy_signal_generators import PRECOMPUTED_COLUMNS_BY_SIGNAL, build_technical_strategy_features
from functions.position_managed_selection import generate_position_managed_selection
from functions.strategy_selection import get_rebalance_dates


GROUP_COL = "symbol"
NORMALIZED_FEATURE_COLUMNS = [
    "ret_20",
    "volatility_20",
    "close_to_ma20",
    "close_to_ma60",
    "amount_ratio_20",
    "score_mom_lowvol",
    "score_orderflow_amount_shock",
    "score_orderflow_close_drive",
    "score_orderflow_accumulation",
    "score_orderflow_efficiency",
]

TRANSIENT_FEATURE_COLUMNS = {
    "macd_dif",
    "macd_dea",
    "macd_cross_up",
    "macd_cross_down",
    "turtle_high_20",
    "turtle_low_20",
    "turtle_high_55",
    "true_range",
    "turtle_breakout_55",
    "mean_reversion_ma20",
    "bollinger_position_20",
    "ma_cross_up",
    "kdj_rsv",
    "kdj_cross_up",
    "close_location",
    "intraday_return_proxy",
    "next_trade_date",
    "calendar_gap_days",
}


def generate_daily_features_multi():
    progress_step("feature step: load clean daily parquet")
    df = pd.read_parquet(CLEAN_DAILY_PARQUET)
    if ADJUSTMENT_FACTORS_PARQUET.exists():
        progress_step("feature step: attach adjustment factors")
        df = attach_adjustment_factors_to_daily(df, pd.read_parquet(ADJUSTMENT_FACTORS_PARQUET))
    progress_step("feature step: build feature frame")
    df = build_feature_frame(df)

    progress_step("feature step: finalize feature frame for storage")
    df, memory_report = finalize_feature_frame_for_storage(df)
    progress_step("feature step: save feature reports")
    _save_feature_reports(df, memory_report=memory_report)
    save_adjustment_pti_coverage_report(df)
    save_investable_benchmark_report()
    _save_feature_registry_validation(df)

    progress_step("feature step: write feature parquet")
    df.to_parquet(FEATURE_DAILY_PARQUET, index=False)
    print("Feature shape:", df.shape)
    return df


def finalize_feature_frame_for_storage(df):
    frame = df.copy(deep=False)
    rows_before = int(len(df))
    columns_before = int(len(df.columns))
    memory_before_bytes = int(df.memory_usage(deep=True).sum())
    dropped_columns = []

    if str(FEATURE_STORAGE_MODE).strip().lower() == "pruned":
        dropped_columns = sorted(set(frame.columns) & TRANSIENT_FEATURE_COLUMNS)
        if dropped_columns:
            frame = frame.drop(columns=dropped_columns)

    if bool(FEATURE_DOWNCAST_FLOATS):
        frame = _downcast_numeric_columns(frame)

    columns_after = int(len(frame.columns))
    memory_after_bytes = int(frame.memory_usage(deep=True).sum())
    memory_report = pd.DataFrame(
        [
            {
                "feature_storage_mode": str(FEATURE_STORAGE_MODE),
                "feature_downcast_floats": bool(FEATURE_DOWNCAST_FLOATS),
                "rows": rows_before,
                "columns_before": columns_before,
                "columns_after": columns_after,
                "dropped_column_count": len(dropped_columns),
                "dropped_columns": ",".join(dropped_columns),
                "memory_before_bytes": memory_before_bytes,
                "memory_after_bytes": memory_after_bytes,
                "memory_saved_bytes": max(memory_before_bytes - memory_after_bytes, 0),
                "memory_saved_ratio": 0.0 if memory_before_bytes <= 0 else max(memory_before_bytes - memory_after_bytes, 0) / memory_before_bytes,
            }
        ]
    )
    return frame, memory_report


def build_feature_frame(df):
    df = df.sort_values([GROUP_COL, "date"]).copy()
    progress_step("feature frame: attach market cap history")
    df = _attach_market_cap_history(df)
    progress_step("feature frame: attach price views")
    df = attach_nominal_price_columns(df)
    if "backward_factor" in df.columns:
        df = attach_point_in_time_adjusted_price_columns(df)
    adjustment_coverage_ratio = float(
        pd.to_numeric(df.get("adj_factor_available", pd.Series(False, index=df.index)), errors="coerce")
        .fillna(False)
        .astype(bool)
        .mean()
    ) if len(df) else 0.0
    adjustment_coverage_threshold = float(FEATURE_PTI_ADJUSTMENT_MIN_COVERAGE_RATIO)
    use_pti_adjusted_prices = (
        all(col in df.columns for col in POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS)
        and adjustment_coverage_ratio >= adjustment_coverage_threshold
        and adjustment_coverage_ratio > 0.0
    )
    price_suffix = "_adj_pti" if use_pti_adjusted_prices else ""
    open_col = f"open{price_suffix}"
    high_col = f"high{price_suffix}"
    low_col = f"low{price_suffix}"
    close_col = f"close{price_suffix}"
    df["feature_price_source"] = (
        "adjusted_point_in_time" if use_pti_adjusted_prices
        else "nominal_unadjusted"
    )
    df["adjustment_coverage_ratio"] = adjustment_coverage_ratio
    df["adjustment_coverage_threshold"] = adjustment_coverage_threshold
    df["price_basis_selection_mode"] = (
        "adjusted_point_in_time_coverage_sufficient"
        if use_pti_adjusted_prices
        else "nominal_due_partial_adjustment_coverage"
    )
    df["formal_price_eligible"] = use_pti_adjusted_prices & df.get(
        "adj_factor_available", pd.Series(False, index=df.index)
    ).fillna(False)
    df["feature_timestamp"] = pd.to_datetime(df["date"])
    progress_step("feature frame: attach sector labels")
    df = attach_sector_labels(df)
    has_neutralization_inputs = {"sector_parent", "stabilized_float_cap"}.issubset(df.columns)
    if has_neutralization_inputs:
        df["neutralization_mode"] = np.where(
            df["sector_parent"].notna() & df["stabilized_float_cap"].notna(),
            "industry_size_neutralized",
            "winsor_only",
        )
    else:
        df["neutralization_mode"] = "winsor_only"
    grouped = df.groupby(GROUP_COL, group_keys=False)

    for n in progress_iter([1, 5, 10, 20, 60], desc="returns"):
        df[f"ret_{n}"] = grouped[close_col].pct_change(n, fill_method=None)

    for n in progress_iter([5, 10, 20, 60, 120], desc="moving averages"):
        df[f"ma_{n}"] = grouped[close_col].transform(lambda x: x.rolling(n, min_periods=n).mean())
        df[f"volume_ma_{n}"] = grouped["volume"].transform(
            lambda x: x.rolling(n, min_periods=n).mean()
        )

    df["close_to_ma20"] = df[close_col] / df["ma_20"] - 1
    df["close_to_ma60"] = df[close_col] / df["ma_60"] - 1

    for n in progress_iter([10, 20, 60], desc="volatility"):
        df[f"volatility_{n}"] = grouped["ret_1"].transform(
            lambda x: x.rolling(n, min_periods=n).std()
        )

    df["amplitude"] = df[high_col] / df[low_col] - 1
    df["intraday_ret"] = df[close_col] / df[open_col] - 1
    max_open_close = df[[open_col, close_col]].max(axis=1)
    min_open_close = df[[open_col, close_col]].min(axis=1)
    df["upper_shadow"] = df[high_col] / max_open_close - 1
    df["lower_shadow"] = min_open_close / df[low_col] - 1
    price_range = (df[high_col] - df[low_col]).replace(0, np.nan)
    df["body_ratio"] = (df[close_col] - df[open_col]).abs() / price_range

    df["amount_ma20"] = grouped["amount"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    df["amount_ratio_20"] = df["amount"] / df["amount_ma20"] - 1

    amount_safe = pd.to_numeric(df["amount"], errors="coerce").clip(lower=0.0).fillna(0.0)
    df["_tmp_log_amount"] = np.log1p(amount_safe)
    log_amount_ma20 = grouped["_tmp_log_amount"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    amount_multiple_20 = amount_safe / df["amount_ma20"].replace(0, np.nan)
    flow_intensity = np.log1p(amount_multiple_20.clip(lower=0.0)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    intraday_direction = (
        ((df[close_col] - df[low_col]) - (df[high_col] - df[close_col]))
        / (df[high_col] - df[low_col]).replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    normalized_ret_1 = (
        pd.to_numeric(df["ret_1"], errors="coerce").fillna(0.0)
        / (pd.to_numeric(df["volatility_20"], errors="coerce").abs().fillna(0.0) + 0.01)
    )
    df["score_orderflow_amount_shock"] = (df["_tmp_log_amount"] - log_amount_ma20).replace([np.inf, -np.inf], np.nan)
    df["score_orderflow_close_drive"] = intraday_direction * flow_intensity
    df["score_orderflow_accumulation"] = (
        pd.to_numeric(df["intraday_ret"], errors="coerce").fillna(0.0)
        * pd.to_numeric(df["body_ratio"], errors="coerce").fillna(0.0)
        * flow_intensity
    )
    df["score_orderflow_efficiency"] = normalized_ret_1 * flow_intensity

    df["score_mom_lowvol"] = df["ret_20"] - df["volatility_20"]
    df = df.drop(columns=["_tmp_log_amount"])

    progress_step("feature frame: apply labels")
    df = apply_default_labels(df, price_col=close_col)
    progress_step("feature frame: attach technical strategy factors")
    df = build_technical_strategy_features(df)
    if bool(ENABLE_PRE_SCREEN_CANDIDATE_FACTOR_POOL):
        progress_step("feature frame: attach pre-screen candidate factor pool")
        df = append_candidate_factors(df, close_col=close_col)
    if bool(FEATURE_DOWNCAST_FLOATS):
        progress_step("feature frame: downcast working numeric columns")
        df = _downcast_numeric_columns(df)
    progress_step("feature frame: attach normalized feature views")
    df = _attach_normalized_feature_views(df)
    return df


def _attach_market_cap_history(df):
    if not MARKET_CAP_PARQUET.exists():
        return df
    market_cap = pd.read_parquet(
        MARKET_CAP_PARQUET,
        columns=[
            "symbol",
            "date",
            "total_cap",
            "float_cap",
            "market_cap_jump_flag",
            "float_cap_jump_flag",
            "jump_event_type",
            "stabilized_total_cap",
            "stabilized_float_cap",
        ],
    )
    market_cap["date"] = pd.to_datetime(market_cap["date"])
    frame = df
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.merge(market_cap, on=["symbol", "date"], how="left")


def _attach_normalized_feature_views(df):
    available_cols = [col for col in NORMALIZED_FEATURE_COLUMNS if col in df.columns]
    if not available_cols:
        return df

    frame = df
    grouped = frame.groupby("date", sort=False)
    for col in progress_iter(available_cols, desc="normalize features"):
        lower = grouped[col].transform(lambda s: s.quantile(0.01))
        upper = grouped[col].transform(lambda s: s.quantile(0.99))
        winsor = frame[col].clip(lower=lower, upper=upper)
        frame[f"{col}_winsor"] = winsor

        mean = winsor.groupby(frame["date"], sort=False).transform("mean")
        std = winsor.groupby(frame["date"], sort=False).transform("std").replace(0, 1.0).fillna(1.0)
        frame[f"{col}_z"] = (winsor - mean) / std

        median = winsor.groupby(frame["date"], sort=False).transform("median")
        q75 = winsor.groupby(frame["date"], sort=False).transform(lambda s: s.quantile(0.75))
        q25 = winsor.groupby(frame["date"], sort=False).transform(lambda s: s.quantile(0.25))
        iqr = (q75 - q25).abs().replace(0, 1e-9).fillna(1e-9)
        frame[f"{col}_robust"] = (winsor - median) / iqr

        if "sector_parent" in frame.columns and "stabilized_float_cap" in frame.columns:
            industry_mean = winsor.groupby([frame["date"], frame["sector_parent"]], sort=False).transform("mean")
            size_rank = frame.groupby("date", sort=False)["stabilized_float_cap"].rank(method="average", pct=True)
            size_centered = size_rank - size_rank.groupby(frame["date"], sort=False).transform("mean")
            frame[f"{col}_neutralized"] = winsor - industry_mean - size_centered.fillna(0.0)
        else:
            frame[f"{col}_neutralized"] = winsor
    return frame


def _save_feature_reports(df, memory_report=None):
    candidate_cols = base_candidate_factor_columns() if bool(ENABLE_PRE_SCREEN_CANDIDATE_FACTOR_POOL) else []
    report_cols = [col for col in [*NORMALIZED_FEATURE_COLUMNS, *candidate_cols] if col in df.columns]
    if report_cols:
        coverage_report = build_feature_coverage_report(df, report_cols)
        extra_rows = pd.DataFrame(
            [
                {
                    "feature": "__adjustment_coverage_ratio__",
                    "non_null_rows": int(len(df)),
                    "coverage_ratio": float(pd.to_numeric(df.get("adjustment_coverage_ratio"), errors="coerce").dropna().iloc[0])
                    if "adjustment_coverage_ratio" in df.columns and not pd.to_numeric(df.get("adjustment_coverage_ratio"), errors="coerce").dropna().empty
                    else 0.0,
                },
                {
                    "feature": "__neutralization_full_coverage_ratio__",
                    "non_null_rows": int(len(df)),
                    "coverage_ratio": float(
                        (
                            df.get("neutralization_mode", pd.Series("", index=df.index))
                            .astype(str)
                            .eq("industry_size_neutralized")
                        ).mean()
                    )
                    if len(df)
                    else 0.0,
                },
            ]
        )
        coverage_report = pd.concat([coverage_report, extra_rows], ignore_index=True)
        coverage_report.to_csv(
            FEATURE_COVERAGE_REPORT_CSV,
            index=False,
            encoding="utf-8-sig",
        )
        build_feature_distribution_report(df, report_cols).to_csv(
            FEATURE_DISTRIBUTION_REPORT_CSV,
            index=False,
            encoding="utf-8-sig",
        )
        build_feature_stability_report(df, report_cols).to_csv(
            FEATURE_STABILITY_REPORT_CSV,
            index=False,
            encoding="utf-8-sig",
        )
    if memory_report is not None:
        memory_report.to_csv(
            FEATURE_MEMORY_REPORT_CSV,
            index=False,
            encoding="utf-8-sig",
        )


def _save_feature_registry_validation(df):
    registry = default_factor_registry()
    rows = []
    available_columns = set(df.columns)
    for spec in registry.values():
        missing_outputs = sorted(set(spec.output_columns) - available_columns)
        rows.append(
            {
                "factor_name": spec.factor_name,
                "module_path": spec.module_path,
                "status": spec.status,
                "output_columns": ",".join(spec.output_columns),
                "missing_output_columns": ",".join(missing_outputs),
                "is_complete": len(missing_outputs) == 0,
            }
        )
    pd.DataFrame(rows).to_csv(
        FEATURE_REGISTRY_REPORT_CSV,
        index=False,
        encoding="utf-8-sig",
    )


def _downcast_numeric_columns(df):
    frame = df.copy(deep=False)
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_float_dtype(series):
            frame[column] = pd.to_numeric(series, errors="coerce", downcast="float")
        elif pd.api.types.is_integer_dtype(series):
            frame[column] = pd.to_numeric(series, errors="coerce", downcast="integer")
    return frame


def select_instruments_by_score(
    df,
    score_col,
    top_n=20,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    ascending=False,
    hot_theme_weights=None,
    hot_theme_slot_ratio=0.0,
    min_score_percentile=0.0,
):
    """Select top instruments only on configured rebalance dates."""
    needed_cols = [
        "date",
        "symbol",
        "close",
        score_col,
        "instrument_type",
        "is_trading",
        "abnormal_jump",
        "formal_price_eligible",
        "feature_price_source",
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "price_basis_selection_mode",
        "neutralization_mode",
        "strategy_params_version",
        "strategy_params_hash",
        "training_window_days",
        "training_sample_count",
        "label_purge_periods",
        "fitted_feature_count",
        "requested_model",
        "runtime_model",
        "ml_runtime_mode",
        "ml_degradation_flag",
        "sector_parent",
        "sector_parent_heat",
        "sector_branch_heat",
    ]
    needed_cols = list(dict.fromkeys(col for col in needed_cols if col in df.columns))
    df_sel = df.loc[:, needed_cols].copy()
    df_sel["date"] = pd.to_datetime(df_sel["date"])

    if start_date is not None:
        df_sel = df_sel[df_sel["date"] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df_sel = df_sel[df_sel["date"] <= pd.to_datetime(end_date)]
    if include_types is not None and "instrument_type" in df_sel.columns:
        df_sel = df_sel[df_sel["instrument_type"].isin(include_types)]
    if "is_trading" in df_sel.columns:
        df_sel = df_sel[df_sel["is_trading"] == True]
    if "abnormal_jump" in df_sel.columns:
        df_sel = df_sel[df_sel["abnormal_jump"] == False]
    if RESEARCH_RUN_MODE == FORMAL_MODE_NAME:
        if "formal_price_eligible" not in df_sel.columns:
            raise ValueError("Formal strategy selection requires point-in-time adjustment coverage")
        df_sel = df_sel[df_sel["formal_price_eligible"] == True]

    eligible_count_by_day = {}
    if not df_sel.empty:
        eligible_count_by_day = (
            df_sel.groupby("date", sort=False)["symbol"].count().to_dict()
        )

    df_sel = df_sel.dropna(subset=["date", "symbol", "close", score_col])
    if df_sel.empty:
        return df_sel

    rebalance_dates = get_rebalance_dates(df_sel, freq=freq)
    df_sel = df_sel[df_sel["date"].isin(rebalance_dates)]
    if df_sel.empty:
        return df_sel

    rows = []
    previous_symbols = set()
    for rebalance_date, one_day in df_sel.groupby("date", sort=True):
        selected = _select_one_rebalance_day(
            one_day=one_day,
            score_col=score_col,
            top_n=top_n,
            ascending=ascending,
            hot_theme_weights=hot_theme_weights,
            hot_theme_slot_ratio=hot_theme_slot_ratio,
            min_score_percentile=min_score_percentile,
            previous_symbols=previous_symbols,
        )
        if selected.empty:
            continue

        selected["rebalance_date"] = rebalance_date
        selected["score"] = selected[score_col]
        selected["weight"] = 1.0 / len(selected)
        eligible_count = int(eligible_count_by_day.get(rebalance_date, len(one_day)))
        selected["signal_candidate_count"] = eligible_count
        selected["signal_trigger_count"] = int(len(selected))
        selected["signal_trigger_rate"] = (
            0.0 if eligible_count <= 0 else float(len(selected)) / float(eligible_count)
        )
        selected["price_basis"] = selected.get("feature_price_source", "nominal_unadjusted")
        selected["degradation_flags"] = selected.apply(_selection_degradation_flags, axis=1)
        rows.append(selected)
        # Track selected symbols for next rebalance date (carry-forward)
        previous_symbols = set(selected["symbol"].tolist())

    if not rows:
        return df_sel.iloc[0:0].copy()

    result = pd.concat(rows, ignore_index=True)
    result["rank"] = result.groupby("rebalance_date")["selection_score"].rank(
        method="first",
        ascending=False,
    )
    return result.sort_values(["rebalance_date", "rank", "symbol"]).reset_index(drop=True)


def generate_multi_strategies(
    df,
    top_n,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
):
    """Generate all configured strategy selections."""
    strategies = {}
    candidate_dates = _strategy_rebalance_dates(
        df=df,
        freq=freq,
        include_types=include_types,
        start_date=start_date,
        end_date=end_date,
    )

    def select(score_col, ascending=False, source_df=None):
        base_cols = [
            "date",
            "symbol",
            "close",
            score_col,
            "instrument_type",
            "is_trading",
            "abnormal_jump",
            "formal_price_eligible",
            "feature_price_source",
            "neutralization_mode",
            "sector_parent",
            "sector_parent_heat",
            "sector_branch_heat",
        ]
        base_cols = list(dict.fromkeys(col for col in base_cols if col in df.columns))
        selection_source = df.loc[:, base_cols]
        if source_df is not None:
            extra_cols = [col for col in source_df.columns if col not in {"date", "symbol"}]
            selection_source = selection_source.merge(
                source_df[["date", "symbol", *extra_cols]],
                on=["date", "symbol"],
                how="left",
            )
        hot_theme_weights = HOT_THEME_WEIGHTS if ENABLE_HOT_THEME_BIAS else {}
        hot_theme_slot_ratio = HOT_THEME_SLOT_RATIO if ENABLE_HOT_THEME_BIAS else 0.0
        return select_instruments_by_score(
            selection_source,
            score_col,
            top_n=top_n,
            freq=freq,
            include_types=include_types,
            start_date=start_date,
            end_date=end_date,
            ascending=ascending,
            hot_theme_weights=hot_theme_weights,
            hot_theme_slot_ratio=hot_theme_slot_ratio,
            min_score_percentile=STRATEGY_MIN_SCORE_PERCENTILE,
        )

    ml_score_tables = {}
    learning_score_tables = None
    training_diagnostics = []

    for strategy_name, spec in progress_iter(
        STRATEGY_REGISTRY.items(),
        desc="generate strategies",
        total=len(STRATEGY_REGISTRY),
    ):
        source_df = None
        strategy_freq = STRATEGY_FREQ_OVERRIDES.get(strategy_name, freq)
        progress_step(f"strategy: {strategy_name} source={spec.source}")

        if spec.source == "ml":
            if spec.model_type not in ml_score_tables:
                ml_score_tables[spec.model_type] = compute_ml_factor(
                    df,
                    model_type=spec.model_type,
                    rebalance_dates=candidate_dates,
                )
                training_diagnostics.extend(
                    _frame_training_diagnostics(ml_score_tables[spec.model_type])
                )
            source_df = ml_score_tables[spec.model_type]
        elif spec.source in {"classic_ml", "quantum_inspired"}:
            if learning_score_tables is None:
                learning_score_tables = generate_learning_module_scores(
                    df,
                    rebalance_dates=candidate_dates,
                )
                for table in learning_score_tables.values():
                    training_diagnostics.extend(_frame_training_diagnostics(table))
            source_df = learning_score_tables[strategy_name]
        elif spec.source == "position_management":
            strategies[strategy_name], _ = generate_position_managed_selection(
                df,
                top_n=top_n,
                freq=strategy_freq,
                start_date=start_date,
                end_date=end_date,
                strategy_name=strategy_name,
            )
            strategies[strategy_name] = _attach_strategy_metadata(
                strategies[strategy_name],
                strategy_name=strategy_name,
                strategy_source=spec.source,
            )
            continue
        elif spec.source in {"technical", "research"}:
            strategies[strategy_name], _ = generate_position_managed_selection(
                df,
                top_n=top_n,
                freq=strategy_freq,
                start_date=start_date,
                end_date=end_date,
                strategy_name=strategy_name,
                signal_strategy_ids=[strategy_name],
            )
            strategies[strategy_name] = _attach_strategy_metadata(
                strategies[strategy_name],
                strategy_name=strategy_name,
                strategy_source=spec.source,
            )
            continue

        strategies[strategy_name] = select(
            spec.score_col,
            ascending=spec.ascending,
            source_df=source_df,
        )
        strategies[strategy_name] = _attach_strategy_metadata(
            strategies[strategy_name],
            strategy_name=strategy_name,
            strategy_source=spec.source,
        )

    _save_model_training_diagnostics(training_diagnostics)
    return strategies


def generate_one_strategy(
    df,
    strategy_name,
    top_n,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    progress_hook=None,
):
    """Generate one configured strategy selection with bounded intermediate state."""
    spec = STRATEGY_REGISTRY[strategy_name]
    freq = STRATEGY_FREQ_OVERRIDES.get(strategy_name, freq)
    candidate_dates = _strategy_rebalance_dates(
        df=df,
        freq=freq,
        include_types=include_types,
        start_date=start_date,
        end_date=end_date,
    )
    source_df = None
    training_diagnostics = []
    if spec.source == "ml":
        source_df = compute_ml_factor(
            df,
            model_type=spec.model_type,
            rebalance_dates=candidate_dates,
        )
        training_diagnostics.extend(_frame_training_diagnostics(source_df))
    elif spec.source in {"classic_ml", "quantum_inspired"}:
        source_df = generate_learning_strategy_scores(
            df,
            strategy_name=strategy_name,
            rebalance_dates=candidate_dates,
        )
        training_diagnostics.extend(_frame_training_diagnostics(source_df))
    elif spec.source == "position_management":
        selection, _ = generate_position_managed_selection(
            df,
            top_n=top_n,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            strategy_name=strategy_name,
            progress_hook=progress_hook,
        )
        return _attach_strategy_metadata(selection, strategy_name=strategy_name, strategy_source=spec.source)
    elif spec.source in {"technical", "research"}:
        selection, _ = generate_position_managed_selection(
            df,
            top_n=top_n,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            strategy_name=strategy_name,
            signal_strategy_ids=[strategy_name],
            progress_hook=progress_hook,
        )
        return _attach_strategy_metadata(selection, strategy_name=strategy_name, strategy_source=spec.source)

    base_cols = _selection_source_columns(spec.score_col, df.columns)
    selection_source = df.loc[:, base_cols]
    if source_df is not None:
        extra_cols = [col for col in source_df.columns if col not in {"date", "symbol"}]
        selection_source = selection_source.merge(
            source_df[["date", "symbol", *extra_cols]],
            on=["date", "symbol"],
            how="left",
        )
    selection = select_instruments_by_score(
        selection_source,
        spec.score_col,
        top_n=top_n,
        freq=freq,
        include_types=include_types,
        start_date=start_date,
        end_date=end_date,
        ascending=spec.ascending,
        hot_theme_weights=HOT_THEME_WEIGHTS if ENABLE_HOT_THEME_BIAS else {},
        hot_theme_slot_ratio=HOT_THEME_SLOT_RATIO if ENABLE_HOT_THEME_BIAS else 0.0,
        min_score_percentile=STRATEGY_MIN_SCORE_PERCENTILE,
    )
    _save_model_training_diagnostics(training_diagnostics)
    return _attach_strategy_metadata(selection, strategy_name=strategy_name, strategy_source=spec.source)


def _attach_strategy_metadata(selection, *, strategy_name, strategy_source):
    if selection is None:
        return selection
    result = selection.copy()
    result["strategy_name"] = strategy_name
    result["strategy_source"] = strategy_source
    result["weighting_mode"] = (
        "kelly_managed"
        if strategy_source in {"technical", "research", "position_management"}
        else "equal_weight"
    )
    result["price_basis"] = result.get("price_basis", result.get("feature_price_source", "nominal_unadjusted"))
    result["neutralization_mode"] = result.get("neutralization_mode", "winsor_only")
    result["ml_runtime_mode"] = result.get("ml_runtime_mode", "not_applicable")
    if "signal_candidate_count" not in result.columns:
        result["signal_candidate_count"] = pd.NA
    if "signal_trigger_count" not in result.columns:
        result["signal_trigger_count"] = pd.NA
    if "signal_trigger_rate" not in result.columns:
        result["signal_trigger_rate"] = pd.NA
    if "degradation_flags" not in result.columns:
        result["degradation_flags"] = ""
    if "governance_variant" not in result.columns:
        result["governance_variant"] = ""
    return result


def _selection_degradation_flags(row):
    flags = []
    if str(row.get("feature_price_source", "")) == "nominal_unadjusted":
        flags.append("price_basis_nominal_fallback")
        coverage_ratio = pd.to_numeric(pd.Series([row.get("adjustment_coverage_ratio")]), errors="coerce").iloc[0]
        coverage_threshold = pd.to_numeric(pd.Series([row.get("adjustment_coverage_threshold")]), errors="coerce").iloc[0]
        if pd.notna(coverage_ratio) and pd.notna(coverage_threshold) and coverage_ratio < coverage_threshold:
            flags.append("adjustment_coverage_below_threshold")
    if str(row.get("neutralization_mode", "")) != "industry_size_neutralized":
        flags.append("neutralization_disabled_or_partial")
    if str(row.get("ml_degradation_flag", "")):
        flags.append(str(row.get("ml_degradation_flag")))
    if bool(row.get("formal_price_eligible", False)) is False:
        flags.append("formal_price_ineligible")
    deduped = []
    for flag in flags:
        if flag and flag not in deduped:
            deduped.append(flag)
    return "|".join(deduped)


def _frame_training_diagnostics(frame):
    diagnostics = frame.attrs.get("training_diagnostics")
    if diagnostics is None:
        return []
    if isinstance(diagnostics, pd.DataFrame):
        if diagnostics.empty:
            return []
        return diagnostics.to_dict("records")
    return list(diagnostics)


def _save_model_training_diagnostics(rows):
    if not rows:
        return
    frame = pd.DataFrame(rows)
    if frame.empty:
        return
    if "rebalance_date" in frame.columns:
        frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce")
    sort_cols = [
        col for col in [
            "model_family",
            "strategy_id",
            "module_name",
            "profile_name",
            "rebalance_date",
            "status",
        ]
        if col in frame.columns
    ]
    if sort_cols:
        frame = frame.sort_values(sort_cols).reset_index(drop=True)
    frame.to_csv(MODEL_TRAINING_DIAGNOSTICS_CSV, index=False, encoding="utf-8-sig")


def required_feature_columns_for_strategy(strategy_name):
    spec = STRATEGY_REGISTRY[strategy_name]
    columns = set(_selection_source_columns(spec.score_col))
    columns.update(["ret_1", "ret_5", "ret_10", "ret_20", "ret_60", "close"])
    if spec.source == "ml":
        from functions.factors.factor_ml import BASE_ML_FEATURE_COLUMNS, DEFAULT_FEATURE_SUFFIX_PRIORITY

        columns.update(BASE_ML_FEATURE_COLUMNS)
        for base_col in BASE_ML_FEATURE_COLUMNS:
            for suffix in DEFAULT_FEATURE_SUFFIX_PRIORITY:
                columns.add(f"{base_col}{suffix}")
        columns.update(["future_ret_5"])
    elif spec.source in {"classic_ml", "quantum_inspired"}:
        from functions.factors.factor_learning import BASE_FEATURE_PRIORITY
        from config import LABEL_DEFAULT_HORIZONS

        columns.update(BASE_FEATURE_PRIORITY)
        for base_col in BASE_FEATURE_PRIORITY:
            for suffix in ("_neutralized", "_z", "_robust", "_winsor"):
                columns.add(f"{base_col}{suffix}")
        for horizon in LABEL_DEFAULT_HORIZONS:
            columns.add(f"future_ret_{horizon}")
    elif spec.source in {"technical", "research", "position_management"}:
        columns.update(
            [
                "code",
                "market",
                "amount",
                "raw_ret",
                "rough_limit_up",
                "rough_limit_down",
                "close_nominal",
                "feature_price_source",
                "adjustment_coverage_ratio",
                "adjustment_coverage_threshold",
                "price_basis_selection_mode",
                "formal_price_eligible",
                "ret_20",
                "future_ret_5",
                "future_ret_10",
                "future_ret_20",
                "volatility_20",
                "market_cap_jump_flag",
                "float_cap_jump_flag",
                "jump_event_type",
            ]
        )
        if spec.source == "position_management":
            columns.update(["open", "high", "low", "volume"])
            for needed_columns in PRECOMPUTED_COLUMNS_BY_SIGNAL.values():
                columns.update(needed_columns)
        else:
            columns.update(PRECOMPUTED_COLUMNS_BY_SIGNAL.get(strategy_name, set()))
    return sorted(columns)


def _selection_source_columns(score_col, available_columns=None):
    needed = [
        "date",
        "symbol",
        "close",
        score_col,
        "instrument_type",
        "is_trading",
        "abnormal_jump",
        "formal_price_eligible",
        "feature_price_source",
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "price_basis_selection_mode",
        "neutralization_mode",
        "strategy_params_version",
        "strategy_params_hash",
        "training_window_days",
        "training_sample_count",
        "label_purge_periods",
        "fitted_feature_count",
        "signal_candidate_count",
        "signal_trigger_count",
        "signal_trigger_rate",
        "sector_parent",
        "sector_parent_heat",
        "sector_branch_heat",
    ]
    if available_columns is None:
        return list(dict.fromkeys(needed))
    available = set(available_columns)
    return list(dict.fromkeys(col for col in needed if col in available))


def _strategy_rebalance_dates(df, freq, include_types, start_date, end_date):
    needed_cols = ["date", "symbol", "instrument_type", "is_trading", "abnormal_jump"]
    needed_cols = [col for col in needed_cols if col in df.columns]
    base = df.loc[:, needed_cols].copy()
    base["date"] = pd.to_datetime(base["date"])
    if start_date is not None:
        base = base[base["date"] >= pd.to_datetime(start_date)]
    if end_date is not None:
        base = base[base["date"] <= pd.to_datetime(end_date)]
    if include_types is not None and "instrument_type" in base.columns:
        base = base[base["instrument_type"].isin(include_types)]
    if "is_trading" in base.columns:
        base = base[base["is_trading"] == True]
    if "abnormal_jump" in base.columns:
        base = base[base["abnormal_jump"] == False]
    if base.empty:
        return pd.Series(dtype="datetime64[ns]")
    return get_rebalance_dates(base, freq=freq)


def _select_one_rebalance_day(
    one_day,
    score_col,
    top_n,
    ascending,
    hot_theme_weights,
    hot_theme_slot_ratio,
    min_score_percentile=0.0,
    previous_symbols=None,
):
    day = one_day.copy()
    day["selection_score"] = _build_selection_score(
        day,
        score_col=score_col,
        ascending=ascending,
        hot_theme_weights=hot_theme_weights,
    )
    day = day.sort_values(["selection_score", "symbol"], ascending=[False, True]).reset_index(drop=True)

    # Score qualification filter: only stocks above the historical percentile threshold qualify
    if min_score_percentile > 0 and score_col in day.columns:
        raw_score = pd.to_numeric(day[score_col], errors="coerce")
        score_threshold = raw_score.quantile(min_score_percentile)
        qualified = day[raw_score >= score_threshold]
        if not qualified.empty:
            day = qualified.reset_index(drop=True)

    hot_theme_weights = hot_theme_weights or {}
    hot_slots = min(int(round(top_n * hot_theme_slot_ratio)), top_n)
    quota_map = _allocate_hot_theme_slots(day, hot_slots=hot_slots, hot_theme_weights=hot_theme_weights)

    selected_frames = []
    selected_symbols = set()
    if quota_map:
        for theme_name, quota in quota_map.items():
            themed = day[
                (day["sector_parent"] == theme_name)
                & (~day["symbol"].isin(selected_symbols))
            ].head(quota)
            if themed.empty:
                continue
            selected_frames.append(themed)
            selected_symbols.update(themed["symbol"].tolist())

    remaining_slots = top_n - sum(len(frame) for frame in selected_frames)
    if remaining_slots > 0:
        fallback = day[~day["symbol"].isin(selected_symbols)].head(remaining_slots)
        if not fallback.empty:
            selected_frames.append(fallback)

    if not selected_frames:
        # Not enough qualified stocks: fill with previously qualified stocks if available
        if previous_symbols and len(previous_symbols) > 0:
            prev_available = one_day[one_day["symbol"].isin(previous_symbols)]
            if not prev_available.empty:
                prev_available = prev_available.copy()
                prev_available["selection_score"] = _build_selection_score(
                    prev_available,
                    score_col=score_col,
                    ascending=ascending,
                    hot_theme_weights=hot_theme_weights or {},
                )
                return prev_available.sort_values(
                    ["selection_score", "symbol"], ascending=[False, True]
                ).head(top_n).copy()
        # No qualified stocks and no previous positions: return empty (go to cash)
        return day.iloc[0:0].copy()

    selected = pd.concat(selected_frames, ignore_index=True)
    return selected.sort_values(["selection_score", "symbol"], ascending=[False, True]).head(top_n).copy()


def _build_selection_score(day, score_col, ascending, hot_theme_weights):
    score = pd.to_numeric(day[score_col], errors="coerce")
    base_score = -score if ascending else score
    rank_component = base_score.rank(method="first", pct=True, ascending=True)
    if "sector_parent" in day.columns:
        sector_parent = day["sector_parent"]
    else:
        sector_parent = pd.Series("", index=day.index)
    if "sector_parent_heat" in day.columns:
        sector_parent_heat = pd.to_numeric(day["sector_parent_heat"], errors="coerce").fillna(0.0)
    else:
        sector_parent_heat = pd.Series(0.0, index=day.index)
    theme_bonus = sector_parent.map(hot_theme_weights or {}).fillna(sector_parent_heat).fillna(0.0)
    if "sector_branch_heat" in day.columns:
        branch_bonus = pd.to_numeric(day["sector_branch_heat"], errors="coerce").fillna(0.0)
    else:
        branch_bonus = pd.Series(0.0, index=day.index)
    return rank_component + 0.20 * theme_bonus + 0.05 * branch_bonus


def _allocate_hot_theme_slots(day, hot_slots, hot_theme_weights):
    if hot_slots <= 0 or not hot_theme_weights:
        return {}

    available = (
        day[day["sector_parent"].isin(hot_theme_weights)]
        .groupby("sector_parent")["symbol"]
        .nunique()
    )
    available = available[available > 0]
    if available.empty:
        return {}

    weights = pd.Series(hot_theme_weights, dtype=float).reindex(available.index).fillna(0.0)
    if weights.sum() <= 0:
        return {}

    raw_quota = weights / weights.sum() * min(hot_slots, int(available.sum()))
    quota = raw_quota.astype(int).clip(upper=available)
    remaining = int(min(hot_slots, int(available.sum())) - quota.sum())

    if remaining > 0:
        remainders = (raw_quota - quota).sort_values(ascending=False)
        while remaining > 0:
            assigned = False
            for theme_name in remainders.index:
                if quota.loc[theme_name] >= available.loc[theme_name]:
                    continue
                quota.loc[theme_name] += 1
                remaining -= 1
                assigned = True
                if remaining == 0:
                    break
            if not assigned:
                break

    return {theme_name: int(value) for theme_name, value in quota.items() if int(value) > 0}


def run_backtest(df_features, strategies, initial_cash=1.0):
    """Legacy helper kept for compatibility; prefer functions.backtest_engine."""
    results = {}
    for name, df_sel in strategies.items():
        df_sel = df_sel.copy().sort_values(["symbol", "date"])
        df_sel["daily_ret"] = df_sel.groupby("symbol")["ret_1"].shift(-1)
        df_sel = df_sel.dropna(subset=["daily_ret"])
        df_sel["weight"] = 1 / df_sel.groupby("date")["symbol"].transform("count")
        df_sel["portfolio_ret"] = df_sel["daily_ret"] * df_sel["weight"]
        df_daily = df_sel.groupby("date")["portfolio_ret"].sum().reset_index()
        df_daily["nav"] = (1 + df_daily["portfolio_ret"]).cumprod() * initial_cash
        results[name] = df_daily
    return results
