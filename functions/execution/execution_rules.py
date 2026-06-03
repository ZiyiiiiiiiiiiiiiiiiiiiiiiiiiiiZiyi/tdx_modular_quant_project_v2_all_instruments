# -*- coding: utf-8 -*-
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP

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


def a_share_price_limit_ratio(symbol, *, is_st=False):
    """Return configured daily price-limit ratio for common A-share boards."""
    code = str(symbol).strip().lower()[2:]
    market = str(symbol).strip().lower()[:2]
    if is_st:
        return 0.05
    if market == "bj":
        return 0.30
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def rounded_price_limit(previous_close, ratio, direction):
    """Exchange-style decimal rounding for displayed price limits."""
    base = Decimal(str(previous_close))
    multiplier = Decimal("1") + Decimal(str(ratio)) * (Decimal("1") if direction == "up" else Decimal("-1"))
    return float((base * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def classify_daily_limit_feasibility(
    *,
    side,
    open_price,
    high_price,
    low_price,
    close_price,
    limit_price,
    amount,
    rolling_amount,
    extreme_amount_ratio=0.02,
):
    """Classify daily-bar limit execution without pretending intraday certainty."""
    prices = [open_price, high_price, low_price, close_price]
    at_limit = [abs(float(price) - float(limit_price)) < 1e-9 for price in prices]
    amount_ratio = float(amount) / float(rolling_amount) if float(rolling_amount) > 0 else 0.0
    if all(at_limit) and amount_ratio <= float(extreme_amount_ratio):
        return "blocked_limit_buy" if str(side).lower() == "buy" else "blocked_limit_sell"
    if bool(at_limit[0]) and bool(at_limit[3]):
        return "high_uncertainty_limit_event"
    return "tradable_daily_proxy"


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
