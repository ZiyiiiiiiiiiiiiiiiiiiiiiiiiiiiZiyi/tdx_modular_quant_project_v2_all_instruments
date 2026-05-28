# -*- coding: utf-8 -*-
import pandas as pd

from config import (
    ENABLE_PRICE_LIMIT_CHECK,
    ENABLE_SUSPENSION_CHECK,
    ENABLE_T_PLUS_ONE,
    MIN_LOT_SIZE,
)


REQUIRED_ORDER_COLUMNS = [
    "symbol",
    "trade_date",
    "side",
    "target_shares",
    "price",
]


def normalize_order_frame(order_df):
    data = order_df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["side"] = data["side"].astype(str).str.lower()
    data["target_shares"] = pd.to_numeric(data["target_shares"], errors="coerce").fillna(0.0)
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    return data


def apply_a_share_constraints(
    order_df,
    *,
    enable_t_plus_one=ENABLE_T_PLUS_ONE,
    enable_price_limit_check=ENABLE_PRICE_LIMIT_CHECK,
    enable_suspension_check=ENABLE_SUSPENSION_CHECK,
    min_lot_size=MIN_LOT_SIZE,
):
    data = normalize_order_frame(order_df)

    data["lot_size_valid"] = (data["target_shares"] % min_lot_size == 0) | (data["target_shares"] == 0)
    data["t_plus_one_blocked"] = False
    data["price_limit_blocked"] = False
    data["suspension_blocked"] = False

    if enable_t_plus_one and "same_day_sell_blocked" in data.columns:
        data["t_plus_one_blocked"] = data["same_day_sell_blocked"].fillna(False).astype(bool)

    if enable_price_limit_check and "price_limit_blocked_flag" in data.columns:
        data["price_limit_blocked"] = data["price_limit_blocked_flag"].fillna(False).astype(bool)

    if enable_suspension_check and "suspension_blocked_flag" in data.columns:
        data["suspension_blocked"] = data["suspension_blocked_flag"].fillna(False).astype(bool)

    data["constraint_blocked"] = (
        (~data["lot_size_valid"])
        | data["t_plus_one_blocked"]
        | data["price_limit_blocked"]
        | data["suspension_blocked"]
    )
    return data
