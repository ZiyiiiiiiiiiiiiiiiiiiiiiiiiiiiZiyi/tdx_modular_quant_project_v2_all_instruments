# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from config import (
    CLEAN_DAILY_PARQUET,
    FEATURE_DAILY_PARQUET,
    HOT_THEME_SLOT_RATIO,
    HOT_THEME_WEIGHTS,
)
from functions.factors.factor_learning import (
    LEARNING_STRATEGY_DESCRIPTIONS,
    generate_learning_module_scores,
)
from functions.factors.factor_ml import compute_factor as compute_ml_factor
from functions.sector_taxonomy import attach_sector_labels
from functions.strategy_selection import get_rebalance_dates


GROUP_COL = "symbol"

STRATEGY_FACTOR_DESCRIPTIONS = {
    "momentum": "20日收益率 ret_20，从高到低选取",
    "reversal": "5日收益率 ret_5，从低到高选取，短期反转",
    "low_vol": "20日波动率 volatility_20，从低到高选取，低波动",
    "volume_extreme": "20日成交量均值 volume_ma_20，从高到低选取",
    "ma_break": "收盘价相对20日均线偏离 close_to_ma20，从高到低选取",
    "kline_shape": "日内振幅 amplitude，从高到低选取",
    "mom_lowvol": "20日收益率 ret_20 - 20日波动率 volatility_20",
    "ml_elasticnet": "ElasticNet 机器学习综合分数 score_ml",
    "ml_xgboost": "XGBoost 机器学习综合分数 score_ml",
    "ml_lightgbm": "LightGBM 机器学习综合分数 score_ml",
    "event_factor": "占位事件因子：当前暂用 20日收益率 ret_20",
    "alternative_factor": "占位另类因子：当前暂用 20日收益率 ret_20",
}
STRATEGY_FACTOR_DESCRIPTIONS.update(LEARNING_STRATEGY_DESCRIPTIONS)


def generate_daily_features_multi():
    df = pd.read_parquet(CLEAN_DAILY_PARQUET)
    df = df.sort_values([GROUP_COL, "date"]).copy()
    df = attach_sector_labels(df)
    grouped = df.groupby(GROUP_COL, group_keys=False)

    for n in [1, 5, 10, 20, 60]:
        df[f"ret_{n}"] = grouped["close"].pct_change(n)

    for n in [5, 10, 20, 60, 120]:
        df[f"ma_{n}"] = grouped["close"].transform(lambda x: x.rolling(n, min_periods=n).mean())
        df[f"volume_ma_{n}"] = grouped["volume"].transform(
            lambda x: x.rolling(n, min_periods=n).mean()
        )

    df["close_to_ma20"] = df["close"] / df["ma_20"] - 1
    df["close_to_ma60"] = df["close"] / df["ma_60"] - 1

    for n in [10, 20, 60]:
        df[f"volatility_{n}"] = grouped["ret_1"].transform(
            lambda x: x.rolling(n, min_periods=n).std()
        )

    df["amplitude"] = df["high"] / df["low"] - 1
    df["intraday_ret"] = df["close"] / df["open"] - 1
    max_open_close = df[["open", "close"]].max(axis=1)
    min_open_close = df[["open", "close"]].min(axis=1)
    df["upper_shadow"] = df["high"] / max_open_close - 1
    df["lower_shadow"] = min_open_close / df["low"] - 1
    price_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_ratio"] = (df["close"] - df["open"]).abs() / price_range

    df["amount_ma20"] = grouped["amount"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    df["amount_ratio_20"] = df["amount"] / df["amount_ma20"] - 1

    df["score_mom_lowvol"] = df["ret_20"] - df["volatility_20"]

    df.to_parquet(FEATURE_DAILY_PARQUET, index=False)
    print("Feature shape:", df.shape)
    return df


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
        return select_instruments_by_score(
            selection_source,
            score_col,
            top_n=top_n,
            freq=freq,
            include_types=include_types,
            start_date=start_date,
            end_date=end_date,
            ascending=ascending,
            hot_theme_weights=HOT_THEME_WEIGHTS,
            hot_theme_slot_ratio=HOT_THEME_SLOT_RATIO,
        )

    strategies["momentum"] = select("ret_20")
    strategies["reversal"] = select("ret_5", ascending=True)
    strategies["low_vol"] = select("volatility_20", ascending=True)
    strategies["volume_extreme"] = select("volume_ma_20")
    strategies["ma_break"] = select("close_to_ma20")
    strategies["kline_shape"] = select("amplitude")
    strategies["mom_lowvol"] = select("score_mom_lowvol")

    df_ml_en = compute_ml_factor(df, model_type="elasticnet", rebalance_dates=candidate_dates)
    df_ml_xgb = compute_ml_factor(df, model_type="xgboost", rebalance_dates=candidate_dates)
    df_ml_lgb = compute_ml_factor(df, model_type="lightgbm", rebalance_dates=candidate_dates)

    strategies["ml_elasticnet"] = select("score_ml", source_df=df_ml_en)
    strategies["ml_xgboost"] = select("score_ml", source_df=df_ml_xgb)
    strategies["ml_lightgbm"] = select("score_ml", source_df=df_ml_lgb)

    learning_score_tables = generate_learning_module_scores(df, rebalance_dates=candidate_dates)
    for strategy_name, score_df in learning_score_tables.items():
        strategies[strategy_name] = select("score_learning", source_df=score_df)

    strategies["event_factor"] = select("ret_20")
    strategies["alternative_factor"] = select("ret_20")

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
