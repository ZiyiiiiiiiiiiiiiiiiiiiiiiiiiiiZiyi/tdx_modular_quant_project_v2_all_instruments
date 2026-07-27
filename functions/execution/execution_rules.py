# -*- coding: utf-8 -*-
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP

from config import (
    ALLOW_BSE_MARKET,
    ALLOW_STAR_MARKET,
    ENABLE_PRICE_LIMIT_CHECK,
    ENABLE_SUSPENSION_CHECK,
    ENABLE_T_PLUS_ONE,
    MIN_LOT_SIZE,
)
from functions.execution.security_trading_rules import (
    date_effective_price_limit_rule,
    is_legal_order_quantity,
    permission_allows,
)


REQUIRED_ORDER_COLUMNS = [
    "symbol",
    "trade_date",
    "side",
    "target_shares",
    "price",
]


def normalize_a_share_symbol(symbol) -> str:
    return str(symbol).strip().lower()


def infer_a_share_board(symbol) -> str:
    normalized = normalize_a_share_symbol(symbol)
    code = normalized[2:]
    market = normalized[:2]
    if market == "bj":
        return "bse"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    return "main_board"


def infer_st_flag(*, is_st=None, name=None) -> bool:
    if pd.notna(is_st):
        if isinstance(is_st, str):
            normalized = is_st.strip().lower()
            if normalized in {"1", "true", "yes", "y", "st"}:
                return True
            if normalized in {"0", "false", "no", "n", ""}:
                return False
        return bool(is_st)
    if pd.isna(name):
        return False
    normalized_name = str(name).strip().upper().replace(" ", "")
    return normalized_name.startswith("ST") or normalized_name.startswith("*ST")


def a_share_price_limit_ratio(symbol, *, is_st=False):
    """Return configured daily price-limit ratio for common A-share boards."""
    code = normalize_a_share_symbol(symbol)[2:]
    market = normalize_a_share_symbol(symbol)[:2]
    if is_st:
        return 0.05
    if market == "bj":
        return 0.30
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def build_price_limit_metadata(symbol, *, is_st=None, name=None) -> dict:
    st_flag = infer_st_flag(is_st=is_st, name=name)
    board = infer_a_share_board(symbol)
    return {
        "board_type": board,
        "is_st": bool(st_flag),
        "price_limit_ratio": float(a_share_price_limit_ratio(symbol, is_st=st_flag)),
    }


def build_date_effective_price_limit_metadata(
    symbol,
    *,
    trade_date,
    is_st=None,
    name=None,
    listing_date=None,
    trading_sessions_since_listing=None,
    security_status="normal",
) -> dict:
    st_flag = infer_st_flag(is_st=is_st, name=name)
    rule = date_effective_price_limit_rule(
        symbol,
        trade_date=trade_date,
        is_st=st_flag,
        listing_date=listing_date,
        trading_sessions_since_listing=trading_sessions_since_listing,
        security_status=security_status,
    )
    return {
        "board_type": rule.board_type,
        "is_st": bool(st_flag),
        "price_limit_ratio": rule.price_limit_ratio,
        "has_daily_price_limit": rule.has_daily_price_limit,
        "price_limit_rule_state": rule.rule_state,
        "price_limit_rule_degraded": rule.degraded,
        "price_limit_rule_version": rule.rule_version,
    }


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


def open_price_limit_blocked(*, side, open_price, limit_up_price=None, limit_down_price=None) -> bool:
    """Conservative open-only limit check without using execution-day close data."""
    try:
        opening = float(open_price)
    except (TypeError, ValueError):
        return True
    if str(side).lower() == "buy":
        if limit_up_price is None or pd.isna(limit_up_price):
            return False
        return opening >= float(limit_up_price) - 1e-9
    if limit_down_price is None or pd.isna(limit_down_price):
        return False
    return opening <= float(limit_down_price) + 1e-9


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
    allow_star_market=ALLOW_STAR_MARKET,
    allow_bse_market=ALLOW_BSE_MARKET,
):
    data = normalize_order_frame(order_df)

    del min_lot_size  # retained in the public signature for compatibility
    data["lot_size_valid"] = data.apply(
        lambda row: is_legal_order_quantity(
            row.get("symbol"),
            row.get("side"),
            row.get("target_shares"),
            trade_date=row.get("trade_date"),
            current_position_shares=row.get("current_position_shares"),
        ),
        axis=1,
    )
    data["market_permission_blocked"] = ~data["symbol"].map(
        lambda symbol: permission_allows(
            symbol,
            allow_star_market=allow_star_market,
            allow_bse_market=allow_bse_market,
        )
    )
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
        | data["market_permission_blocked"]
        | data["t_plus_one_blocked"]
        | data["price_limit_blocked"]
        | data["suspension_blocked"]
    )
    return data
