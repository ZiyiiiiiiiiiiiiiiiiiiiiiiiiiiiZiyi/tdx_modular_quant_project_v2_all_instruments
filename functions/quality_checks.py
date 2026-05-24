# -*- coding: utf-8 -*-
import pandas as pd
from config import STOCK_INFO_CSV, ABNORMAL_RETURN_CSV, DATA_QUALITY_SUMMARY_CSV

def add_quality_flags(df, group_col="symbol", abnormal_threshold=0.20):
    df = df.copy()
    df = df.sort_values([group_col, "date"])

    df["valid_price"] = (
        (df["open"] > 0) &
        (df["high"] > 0) &
        (df["low"] > 0) &
        (df["close"] > 0) &
        (df["high"] >= df["low"])
    )

    df["valid_volume"] = (
        (df["volume"].fillna(0) >= 0) &
        (df["amount"].fillna(0) >= 0)
    )

    df["raw_ret"] = df.groupby(group_col)["close"].pct_change()
    df["abnormal_jump"] = df["raw_ret"].abs() > abnormal_threshold
    df["rough_limit_up"] = df["raw_ret"] >= 0.095
    df["rough_limit_down"] = df["raw_ret"] <= -0.095

    df["is_trading"] = (
        df["valid_price"] &
        df["valid_volume"] &
        (df["volume"].fillna(0) > 0) &
        (df["amount"].fillna(0) > 0)
    )

    return df

def build_instrument_info(df, group_col="symbol"):
    keep_cols = [group_col]
    for c in ["code", "market", "instrument_type"]:
        if c in df.columns:
            keep_cols.append(c)

    basic = df[keep_cols].drop_duplicates(subset=[group_col])

    info = (
        df.groupby(group_col)
        .agg(
            start_date=("date", "min"),
            end_date=("date", "max"),
            rows=("date", "count"),
            missing_close=("close", lambda x: x.isna().sum()),
            abnormal_count=("abnormal_jump", "sum"),
            trading_days=("is_trading", "sum"),
        )
        .reset_index()
    )

    return basic.merge(info, on=group_col, how="right")

def build_data_quality_summary(df):
    summary = pd.DataFrame({
        "metric": [
            "rows",
            "instrument_count",
            "date_min",
            "date_max",
            "missing_open",
            "missing_high",
            "missing_low",
            "missing_close",
            "invalid_price_rows",
            "invalid_volume_rows",
            "abnormal_jump_rows",
        ],
        "value": [
            len(df),
            df["symbol"].nunique(),
            df["date"].min(),
            df["date"].max(),
            df["open"].isna().sum(),
            df["high"].isna().sum(),
            df["low"].isna().sum(),
            df["close"].isna().sum(),
            (~df["valid_price"]).sum(),
            (~df["valid_volume"]).sum(),
            df["abnormal_jump"].sum(),
        ]
    })
    return summary

def save_quality_reports(df, group_col="symbol"):
    instrument_info = build_instrument_info(df, group_col=group_col)
    abnormal = df[df["abnormal_jump"]].copy()
    summary = build_data_quality_summary(df)

    instrument_info.to_csv(STOCK_INFO_CSV, index=False, encoding="utf-8-sig")
    abnormal.to_csv(ABNORMAL_RETURN_CSV, index=False, encoding="utf-8-sig")
    summary.to_csv(DATA_QUALITY_SUMMARY_CSV, index=False, encoding="utf-8-sig")

    print("Saved instrument info:", STOCK_INFO_CSV)
    print("Saved abnormal rows:", ABNORMAL_RETURN_CSV)
    print("Saved data quality summary:", DATA_QUALITY_SUMMARY_CSV)
