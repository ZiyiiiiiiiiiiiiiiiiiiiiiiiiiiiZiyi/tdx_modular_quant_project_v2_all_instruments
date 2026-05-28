# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    CLEAN_DAILY_PARQUET,
    ENABLE_HOT_THEME_BIAS,
    FEATURE_DAILY_PARQUET,
    FEATURE_COVERAGE_REPORT_CSV,
    FEATURE_DISTRIBUTION_REPORT_CSV,
    FEATURE_REGISTRY_REPORT_CSV,
    FEATURE_STABILITY_REPORT_CSV,
    HOT_THEME_SLOT_RATIO,
    HOT_THEME_WEIGHTS,
    FORMAL_MODE_NAME,
    RESEARCH_RUN_MODE,
)
from functions.data_sources.adjustment_factors import attach_adjustment_factors_to_daily
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
from functions.factors.factor_learning import generate_learning_module_scores
from functions.factors.factor_ml import compute_factor as compute_ml_factor
from functions.labels import apply_default_labels
from functions.pricing.price_views import (
    POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS,
    attach_nominal_price_columns,
    attach_point_in_time_adjusted_price_columns,
)
from functions.sector_taxonomy import attach_sector_labels
from functions.strategy_registry import STRATEGY_REGISTRY
from functions.strategy_selection import get_rebalance_dates


GROUP_COL = "symbol"
NORMALIZED_FEATURE_COLUMNS = [
    "ret_20",
    "volatility_20",
    "close_to_ma20",
    "close_to_ma60",
    "amount_ratio_20",
    "score_mom_lowvol",
]


def generate_daily_features_multi():
    df = pd.read_parquet(CLEAN_DAILY_PARQUET)
    if ADJUSTMENT_FACTORS_PARQUET.exists():
        df = attach_adjustment_factors_to_daily(df, pd.read_parquet(ADJUSTMENT_FACTORS_PARQUET))
    df = build_feature_frame(df)

    _save_feature_reports(df)
    _save_feature_registry_validation(df)

    df.to_parquet(FEATURE_DAILY_PARQUET, index=False)
    print("Feature shape:", df.shape)
    return df


def build_feature_frame(df):
    df = df.sort_values([GROUP_COL, "date"]).copy()
    df = attach_nominal_price_columns(df)
    if "backward_factor" in df.columns:
        df = attach_point_in_time_adjusted_price_columns(df)
    use_pti_adjusted_prices = all(col in df.columns for col in POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS)
    price_suffix = "_adj_pti" if use_pti_adjusted_prices else ""
    open_col = f"open{price_suffix}"
    high_col = f"high{price_suffix}"
    low_col = f"low{price_suffix}"
    close_col = f"close{price_suffix}"
    df["feature_price_source"] = (
        "adjusted_point_in_time" if use_pti_adjusted_prices
        else "nominal_unadjusted"
    )
    df["formal_price_eligible"] = use_pti_adjusted_prices & df.get(
        "adj_factor_available", pd.Series(False, index=df.index)
    ).fillna(False)
    df["feature_timestamp"] = pd.to_datetime(df["date"])
    df = attach_sector_labels(df)
    grouped = df.groupby(GROUP_COL, group_keys=False)

    for n in [1, 5, 10, 20, 60]:
        df[f"ret_{n}"] = grouped[close_col].pct_change(n)

    for n in [5, 10, 20, 60, 120]:
        df[f"ma_{n}"] = grouped[close_col].transform(lambda x: x.rolling(n, min_periods=n).mean())
        df[f"volume_ma_{n}"] = grouped["volume"].transform(
            lambda x: x.rolling(n, min_periods=n).mean()
        )

    df["close_to_ma20"] = df[close_col] / df["ma_20"] - 1
    df["close_to_ma60"] = df[close_col] / df["ma_60"] - 1

    for n in [10, 20, 60]:
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

    df["score_mom_lowvol"] = df["ret_20"] - df["volatility_20"]

    df = apply_default_labels(df, price_col=close_col)
    df = _attach_normalized_feature_views(df)
    return df


def _attach_normalized_feature_views(df):
    available_cols = [col for col in NORMALIZED_FEATURE_COLUMNS if col in df.columns]
    if not available_cols:
        return df

    frame = df.copy()
    grouped = frame.groupby("date", sort=False)
    for col in available_cols:
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


def _save_feature_reports(df):
    report_cols = [col for col in NORMALIZED_FEATURE_COLUMNS if col in df.columns]
    if not report_cols:
        return

    build_feature_coverage_report(df, report_cols).to_csv(
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
):
    """Select top instruments only on configured rebalance dates."""
    df_sel = df.copy()
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

    df_sel = df_sel.dropna(subset=["date", "symbol", "close", score_col])
    if df_sel.empty:
        return df_sel

    rebalance_dates = get_rebalance_dates(df_sel, freq=freq)
    df_sel = df_sel[df_sel["date"].isin(rebalance_dates)]
    if df_sel.empty:
        return df_sel

    rows = []
    for rebalance_date, one_day in df_sel.groupby("date", sort=True):
        selected = _select_one_rebalance_day(
            one_day=one_day,
            score_col=score_col,
            top_n=top_n,
            ascending=ascending,
            hot_theme_weights=hot_theme_weights,
            hot_theme_slot_ratio=hot_theme_slot_ratio,
        )
        if selected.empty:
            continue

        selected["rebalance_date"] = rebalance_date
        selected["score"] = selected[score_col]
        selected["weight"] = 1.0 / len(selected)
        rows.append(selected)

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
        selection_source = df
        if source_df is not None:
            extra_cols = [col for col in source_df.columns if col not in {"date", "symbol"}]
            selection_source = df.merge(
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
        )

    ml_score_tables = {}
    learning_score_tables = None

    for strategy_name, spec in STRATEGY_REGISTRY.items():
        source_df = None

        if spec.source == "ml":
            if spec.model_type not in ml_score_tables:
                ml_score_tables[spec.model_type] = compute_ml_factor(
                    df,
                    model_type=spec.model_type,
                    rebalance_dates=candidate_dates,
                )
            source_df = ml_score_tables[spec.model_type]
        elif spec.source in {"classic_ml", "quantum_inspired"}:
            if learning_score_tables is None:
                learning_score_tables = generate_learning_module_scores(
                    df,
                    rebalance_dates=candidate_dates,
                )
            source_df = learning_score_tables[strategy_name]

        strategies[strategy_name] = select(
            spec.score_col,
            ascending=spec.ascending,
            source_df=source_df,
        )

    return strategies


def _strategy_rebalance_dates(df, freq, include_types, start_date, end_date):
    base = df.copy()
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
):
    day = one_day.copy()
    day["selection_score"] = _build_selection_score(
        day,
        score_col=score_col,
        ascending=ascending,
        hot_theme_weights=hot_theme_weights,
    )
    day = day.sort_values(["selection_score", "symbol"], ascending=[False, True]).reset_index(drop=True)

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
        return day.head(top_n).copy()

    selected = pd.concat(selected_frames, ignore_index=True)
    return selected.sort_values(["selection_score", "symbol"], ascending=[False, True]).head(top_n).copy()


def _build_selection_score(day, score_col, ascending, hot_theme_weights):
    score = pd.to_numeric(day[score_col], errors="coerce")
    base_score = -score if ascending else score
    rank_component = base_score.rank(method="first", pct=True, ascending=True)
    theme_bonus = day["sector_parent"].map(hot_theme_weights or {}).fillna(day["sector_parent_heat"]).fillna(0.0)
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
