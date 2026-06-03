# -*- coding: utf-8 -*-
import pandas as pd


def classify_monthly_market_regime(index_returns_df, date_col="date", return_col="benchmark_return"):
    frame = index_returns_df.copy()
    frame[date_col] = pd.to_datetime(frame[date_col])
    frame["month"] = frame[date_col].dt.to_period("M").astype(str)
    monthly = frame.groupby("month", as_index=False)[return_col].mean()
    monthly["regime"] = monthly[return_col].apply(_regime_from_return)
    return monthly


def summarize_strategy_by_regime(strategy_returns_df, regime_df, date_col="date", return_col="daily_return"):
    frame = strategy_returns_df.copy()
    frame[date_col] = pd.to_datetime(frame[date_col])
    frame["month"] = frame[date_col].dt.to_period("M").astype(str)
    merged = frame.merge(regime_df[["month", "regime"]], on="month", how="left")
    return (
        merged.groupby("regime", as_index=False)[return_col]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "avg_return", "count": "row_count"})
    )


def _regime_from_return(value):
    if pd.isna(value):
        return "unknown"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"
