# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from config import CLEAN_DAILY_PARQUET, FEATURE_DAILY_PARQUET
from functions.factors.factor_ml import compute_factor as compute_ml_factor
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
    "ml_elasticnet": "ElasticNet 机器学习综合分 score_ml",
    "ml_xgboost": "XGBoost 机器学习综合分 score_ml",
    "ml_lightgbm": "LightGBM 机器学习综合分 score_ml",
    "event_factor": "占位事件因子：当前暂用20日收益率 ret_20",
    "alternative_factor": "占位另类因子：当前暂用20日收益率 ret_20",
}


def generate_daily_features_multi():
    df = pd.read_parquet(CLEAN_DAILY_PARQUET)
    df = df.sort_values([GROUP_COL, "date"])
    g = df.groupby(GROUP_COL, group_keys=False)

    for n in [1, 5, 10, 20, 60]:
        df[f"ret_{n}"] = g["close"].pct_change(n)

    for n in [5, 10, 20, 60, 120]:
        df[f"ma_{n}"] = g["close"].transform(lambda x: x.rolling(n, min_periods=n).mean())
        df[f"volume_ma_{n}"] = g["volume"].transform(lambda x: x.rolling(n, min_periods=n).mean())

    df["close_to_ma20"] = df["close"] / df["ma_20"] - 1
    df["close_to_ma60"] = df["close"] / df["ma_60"] - 1

    for n in [10, 20, 60]:
        df[f"volatility_{n}"] = g["ret_1"].transform(lambda x: x.rolling(n, min_periods=n).std())

    df["amplitude"] = df["high"] / df["low"] - 1
    df["intraday_ret"] = df["close"] / df["open"] - 1
    max_open_close = df[["open", "close"]].max(axis=1)
    min_open_close = df[["open", "close"]].min(axis=1)
    df["upper_shadow"] = df["high"] / max_open_close - 1
    df["lower_shadow"] = min_open_close / df["low"] - 1
    price_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_ratio"] = (df["close"] - df["open"]).abs() / price_range

    df["amount_ma20"] = g["amount"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    df["amount_ratio_20"] = df["amount"] / df["amount_ma20"] - 1

    df["score_mom_lowvol"] = df["ret_20"] - df["volatility_20"]

    df.to_parquet(FEATURE_DAILY_PARQUET, index=False)

    print("Feature shape:", df.shape)
    return df


def select_instruments_by_score(
    df,
    score_col,
    top_n=5,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    ascending=False,
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

    df_sel = df_sel.sort_values(["date", score_col], ascending=[True, ascending])
    df_sel["rank"] = df_sel.groupby("date")[score_col].rank(
        method="first",
        ascending=ascending,
    )
    df_sel = df_sel[df_sel["rank"] <= top_n].copy()
    df_sel["rebalance_date"] = df_sel["date"]
    df_sel["score"] = df_sel[score_col]
    df_sel["weight"] = 1.0 / df_sel.groupby("rebalance_date")["symbol"].transform("count")
    return df_sel


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

    def select(score_col, ascending=False, source_df=None):
        selection_source = df
        if source_df is not None:
            selection_source = df.merge(
                source_df[["date", "symbol", score_col]],
                on=["date", "symbol"],
                how="left",
                suffixes=("", "_score"),
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
        )

    strategies["momentum"] = select("ret_20")
    strategies["reversal"] = select("ret_5", ascending=True)
    strategies["low_vol"] = select("volatility_20", ascending=True)
    strategies["volume_extreme"] = select("volume_ma_20")
    strategies["ma_break"] = select("close_to_ma20")
    strategies["kline_shape"] = select("amplitude")
    strategies["mom_lowvol"] = select("score_mom_lowvol")

    df_ml_en = compute_ml_factor(df, model_type="elasticnet")
    df_ml_xgb = compute_ml_factor(df, model_type="xgboost")
    df_ml_lgb = compute_ml_factor(df, model_type="lightgbm")

    strategies["ml_elasticnet"] = select("score_ml", source_df=df_ml_en)
    strategies["ml_xgboost"] = select("score_ml", source_df=df_ml_xgb)
    strategies["ml_lightgbm"] = select("score_ml", source_df=df_ml_lgb)

    strategies["event_factor"] = select("ret_20")
    strategies["alternative_factor"] = select("ret_20")

    return strategies


def run_backtest(df_features, strategies, initial_cash=1.0):
    """Legacy helper kept for compatibility; prefer functions.backtest_engine."""
    results = {}
    for name, df_sel in strategies.items():
        df_sel = df_sel.copy()
        df_sel = df_sel.sort_values(["symbol", "date"])
        df_sel["daily_ret"] = df_sel.groupby("symbol")["ret_1"].shift(-1)
        df_sel = df_sel.dropna(subset=["daily_ret"])
        df_sel["weight"] = 1 / df_sel.groupby("date")["symbol"].transform("count")
        df_sel["portfolio_ret"] = df_sel["daily_ret"] * df_sel["weight"]
        df_daily = df_sel.groupby("date")["portfolio_ret"].sum().reset_index()
        df_daily["nav"] = (1 + df_daily["portfolio_ret"]).cumprod() * initial_cash
        results[name] = df_daily
    return results
