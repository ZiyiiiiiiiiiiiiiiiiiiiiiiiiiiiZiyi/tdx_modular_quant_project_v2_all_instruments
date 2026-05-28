# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import LIQUIDITY_LOCK_REPORT_CSV, MAX_LIQUIDITY_LOCK_DAYS


LIQUIDITY_LOCK_COLUMNS = [
    "symbol",
    "start_date",
    "last_seen_date",
    "lock_reason",
    "delay_days",
    "forced_exit_triggered",
]


def build_liquidity_lock_report(
    delayed_orders,
    *,
    max_lock_days=MAX_LIQUIDITY_LOCK_DAYS,
):
    data = delayed_orders.copy()
    if data.empty:
        return pd.DataFrame(columns=LIQUIDITY_LOCK_COLUMNS)

    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    grouped = (
        data.groupby(["symbol", "delay_reason"], dropna=False)
        .agg(
            start_date=("trade_date", "min"),
            last_seen_date=("trade_date", "max"),
            delay_days=("delay_days", "sum"),
        )
        .reset_index()
        .rename(columns={"delay_reason": "lock_reason"})
    )
    grouped["forced_exit_triggered"] = grouped["delay_days"] >= max_lock_days
    return grouped[LIQUIDITY_LOCK_COLUMNS].copy()


def save_liquidity_lock_report(report_df, output_path=LIQUIDITY_LOCK_REPORT_CSV):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file
