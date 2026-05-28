# -*- coding: utf-8 -*-
import pandas as pd

from config import RAW_DAILY_PARQUET, CLEAN_DAILY_PARQUET, START_DATE, END_DATE, ABNORMAL_RETURN_THRESHOLD
from functions.pricing.price_views import attach_nominal_price_columns
from functions.quality_checks import add_quality_flags, save_quality_reports

def basic_clean_daily(df):
    df = df.copy()

    df["date"] = pd.to_datetime(df["date"])
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["symbol"] = df["symbol"].astype(str)

    for col in ["open", "high", "low", "close", "amount", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "symbol", "close"])
    df = df.drop_duplicates(subset=["symbol", "date"], keep="last")
    df = df.sort_values(["symbol", "date"])

    if START_DATE is not None:
        df = df[df["date"] >= pd.to_datetime(START_DATE)].copy()

    if END_DATE is not None:
        df = df[df["date"] <= pd.to_datetime(END_DATE)].copy()

    return df

def clean_daily_data():
    df = pd.read_parquet(RAW_DAILY_PARQUET)
    print("Raw shape:", df.shape)

    clean = basic_clean_daily(df)
    clean = add_quality_flags(clean, group_col="symbol", abnormal_threshold=ABNORMAL_RETURN_THRESHOLD)
    clean = attach_nominal_price_columns(clean)
    clean.to_parquet(CLEAN_DAILY_PARQUET, index=False)

    save_quality_reports(clean, group_col="symbol")

    print("Saved clean daily data:", CLEAN_DAILY_PARQUET)
    print("Clean shape:", clean.shape)
    print("Instrument count:", clean["symbol"].nunique())
    print("Date range:", clean["date"].min(), "to", clean["date"].max())

    return clean
