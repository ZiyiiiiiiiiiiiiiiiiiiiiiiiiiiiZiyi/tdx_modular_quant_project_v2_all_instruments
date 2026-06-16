# -*- coding: utf-8 -*-
import pandas as pd
from config import (
    ABNORMAL_RETURN_CSV,
    DATA_CONTINUITY_GAP_DAYS_WARN,
    DATA_CONTINUITY_REPORT_CSV,
    DATA_QUALITY_SUMMARY_CSV,
    STOCK_INFO_CSV,
)
from functions.execution.execution_rules import build_price_limit_metadata, rounded_price_limit

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
    name_series = _security_name_series(df)
    symbol_frame = pd.DataFrame(
        {
            "symbol": df.get(group_col, pd.Series("", index=df.index)).astype(str),
            "is_st_raw": df.get("is_st", pd.Series(pd.NA, index=df.index)),
            "security_name": name_series,
        }
    )
    limit_meta = symbol_frame.apply(
        lambda row: build_price_limit_metadata(
            row["symbol"],
            is_st=row.get("is_st_raw"),
            name=row.get("security_name"),
        ),
        axis=1,
        result_type="expand",
    )
    df["board_type"] = limit_meta["board_type"]
    df["is_st"] = limit_meta["is_st"].astype(bool)
    df["price_limit_ratio"] = pd.to_numeric(limit_meta["price_limit_ratio"], errors="coerce")
    prev_close = df.groupby(group_col)["close"].shift(1)
    df["prev_close"] = prev_close
    df["limit_up_price"] = [
        rounded_price_limit(base, ratio, "up") if pd.notna(base) and pd.notna(ratio) and float(base) > 0 else pd.NA
        for base, ratio in zip(df["prev_close"], df["price_limit_ratio"])
    ]
    df["limit_down_price"] = [
        rounded_price_limit(base, ratio, "down") if pd.notna(base) and pd.notna(ratio) and float(base) > 0 else pd.NA
        for base, ratio in zip(df["prev_close"], df["price_limit_ratio"])
    ]
    df["rough_limit_up"] = (
        pd.to_numeric(df["close"], errors="coerce")
        >= pd.to_numeric(df["limit_up_price"], errors="coerce")
    ).fillna(False)
    df["rough_limit_down"] = (
        pd.to_numeric(df["close"], errors="coerce")
        <= pd.to_numeric(df["limit_down_price"], errors="coerce")
    ).fillna(False)

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
            board_type=("board_type", "last"),
            is_st=("is_st", "max"),
            price_limit_ratio=("price_limit_ratio", "last"),
        )
        .reset_index()
    )

    return basic.merge(info, on=group_col, how="right")

def build_data_quality_summary(df):
    continuity = build_data_continuity_report(df)
    large_gap_symbols = int(
        continuity.loc[continuity["symbol"] != "__summary__", "has_large_gap"].fillna(False).astype(bool).sum()
    ) if not continuity.empty else 0
    max_gap_days = int(
        pd.to_numeric(
            continuity.loc[continuity["symbol"] != "__summary__", "max_calendar_gap_days"],
            errors="coerce",
        ).fillna(0).max()
    ) if not continuity.empty else 0
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
            "rough_limit_up_rows",
            "rough_limit_down_rows",
            "st_rows",
            "continuity_gap_warn_days",
            "symbols_with_large_calendar_gap",
            "max_calendar_gap_days",
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
            df["rough_limit_up"].sum(),
            df["rough_limit_down"].sum(),
            df["is_st"].sum() if "is_st" in df.columns else 0,
            int(DATA_CONTINUITY_GAP_DAYS_WARN),
            large_gap_symbols,
            max_gap_days,
        ]
    })
    return summary


def build_data_continuity_report(df, group_col="symbol"):
    if df.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "rows",
                "start_date",
                "end_date",
                "mean_calendar_gap_days",
                "median_calendar_gap_days",
                "max_calendar_gap_days",
                "large_gap_count",
                "has_large_gap",
                "continuity_status",
            ]
        )
    ordered = df.sort_values([group_col, "date"]).copy()
    ordered["calendar_gap_days"] = ordered.groupby(group_col)["date"].diff().dt.days
    report = (
        ordered.groupby(group_col, dropna=False)
        .agg(
            rows=("date", "count"),
            start_date=("date", "min"),
            end_date=("date", "max"),
            mean_calendar_gap_days=("calendar_gap_days", "mean"),
            median_calendar_gap_days=("calendar_gap_days", "median"),
            max_calendar_gap_days=("calendar_gap_days", "max"),
            large_gap_count=("calendar_gap_days", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > int(DATA_CONTINUITY_GAP_DAYS_WARN)).sum())),
        )
        .reset_index()
        .rename(columns={group_col: "symbol"})
    )
    report["has_large_gap"] = report["large_gap_count"] > 0
    report["continuity_status"] = report["has_large_gap"].map({True: "gap_warning", False: "ok"})
    summary = pd.DataFrame(
        [
            {
                "symbol": "__summary__",
                "rows": int(report["rows"].sum()),
                "start_date": report["start_date"].min(),
                "end_date": report["end_date"].max(),
                "mean_calendar_gap_days": pd.to_numeric(report["mean_calendar_gap_days"], errors="coerce").mean(),
                "median_calendar_gap_days": pd.to_numeric(report["median_calendar_gap_days"], errors="coerce").median(),
                "max_calendar_gap_days": pd.to_numeric(report["max_calendar_gap_days"], errors="coerce").max(),
                "large_gap_count": int(pd.to_numeric(report["large_gap_count"], errors="coerce").fillna(0).sum()),
                "has_large_gap": bool(report["has_large_gap"].any()),
                "continuity_status": "gap_warning" if bool(report["has_large_gap"].any()) else "ok",
            }
        ]
    )
    return pd.concat([report, summary], ignore_index=True)


def _security_name_series(df):
    for column in ["security_name", "stock_name", "name"]:
        if column in df.columns:
            return df[column]
    return pd.Series(pd.NA, index=df.index)

def save_quality_reports(df, group_col="symbol"):
    instrument_info = build_instrument_info(df, group_col=group_col)
    abnormal = df[df["abnormal_jump"]].copy()
    summary = build_data_quality_summary(df)
    continuity = build_data_continuity_report(df, group_col=group_col)

    instrument_info.to_csv(STOCK_INFO_CSV, index=False, encoding="utf-8-sig")
    abnormal.to_csv(ABNORMAL_RETURN_CSV, index=False, encoding="utf-8-sig")
    summary.to_csv(DATA_QUALITY_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    continuity.to_csv(DATA_CONTINUITY_REPORT_CSV, index=False, encoding="utf-8-sig")

    print("Saved instrument info:", STOCK_INFO_CSV)
    print("Saved abnormal rows:", ABNORMAL_RETURN_CSV)
    print("Saved data quality summary:", DATA_QUALITY_SUMMARY_CSV)
    print("Saved data continuity report:", DATA_CONTINUITY_REPORT_CSV)
