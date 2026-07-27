"""Date-effective A-share trading quantity and permission rules.

The governance runner previously treated every equity as a 100-share-lot
instrument.  That is not executable for STAR Market buys, whose minimum
order quantity is 200 shares.  Keep the rule lookup small and deterministic
so all sizing and execution paths share the same contract.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SecurityTradingRule:
    board_type: str
    minimum_buy_quantity: int
    buy_quantity_step: int
    standard_sell_step: int
    odd_lot_full_exit_allowed: bool
    permission_required: str = ""
    rule_version: str = "a_share_board_quantity_v1"


@dataclass(frozen=True)
class DateEffectivePriceLimitRule:
    board_type: str
    price_limit_ratio: float | None
    has_daily_price_limit: bool
    rule_state: str
    degraded: bool
    rule_version: str = "a_share_price_limit_date_effective_v2"


def normalize_symbol(symbol) -> str:
    return str(symbol or "").strip().lower()


def infer_board_type(symbol) -> str:
    normalized = normalize_symbol(symbol)
    market, code = normalized[:2], normalized[2:]
    if market == "bj":
        return "bse"
    if market == "sh" and code.startswith(("688", "689")):
        return "star"
    if market == "sz" and code.startswith(("300", "301")):
        return "chinext"
    return "main_board"


def trading_rule_for(symbol, *, trade_date=None) -> SecurityTradingRule:
    """Return the rule known to be applicable to the requested equity.

    ``trade_date`` is accepted deliberately even where the first registry
    version has no date transition.  Callers must pass it so future exchange
    rule changes can be added without changing the sizing interface.
    """
    if trade_date is not None:
        pd.Timestamp(trade_date)  # validate date-like inputs at the boundary
    board = infer_board_type(symbol)
    if board == "star":
        return SecurityTradingRule(
            board_type=board,
            minimum_buy_quantity=200,
            buy_quantity_step=1,
            standard_sell_step=1,
            odd_lot_full_exit_allowed=True,
            permission_required="star_market",
        )
    return SecurityTradingRule(
        board_type=board,
        minimum_buy_quantity=100,
        buy_quantity_step=100,
        standard_sell_step=100,
        odd_lot_full_exit_allowed=True,
        permission_required="bse_market" if board == "bse" else "",
    )


def legal_buy_quantity(symbol, requested_shares, *, trade_date=None) -> float:
    rule = trading_rule_for(symbol, trade_date=trade_date)
    requested = max(int(float(requested_shares or 0.0)), 0)
    if requested < rule.minimum_buy_quantity:
        return 0.0
    increments = (requested - rule.minimum_buy_quantity) // rule.buy_quantity_step
    return float(rule.minimum_buy_quantity + increments * rule.buy_quantity_step)


def is_legal_order_quantity(
    symbol,
    side,
    shares,
    *,
    trade_date=None,
    current_position_shares=None,
) -> bool:
    rule = trading_rule_for(symbol, trade_date=trade_date)
    quantity = int(abs(float(shares or 0.0)))
    if quantity == 0:
        return True
    if str(side).lower() == "buy":
        return bool(
            quantity >= rule.minimum_buy_quantity
            and (quantity - rule.minimum_buy_quantity) % rule.buy_quantity_step == 0
        )
    if current_position_shares is not None:
        position = int(abs(float(current_position_shares or 0.0)))
        if quantity == position and rule.odd_lot_full_exit_allowed:
            return True
    if rule.board_type == "star":
        return quantity >= 200
    return quantity % rule.standard_sell_step == 0


def permission_allows(symbol, *, allow_star_market=False, allow_bse_market=False) -> bool:
    requirement = trading_rule_for(symbol).permission_required
    if requirement == "star_market":
        return bool(allow_star_market)
    if requirement == "bse_market":
        return bool(allow_bse_market)
    return True


def date_effective_price_limit_rule(
    symbol,
    *,
    trade_date,
    is_st: bool = False,
    listing_date=None,
    trading_sessions_since_listing=None,
    security_status: str = "normal",
) -> DateEffectivePriceLimitRule:
    """Return a conservative date-effective board rule.

    The no-limit opening period is used only when listing age is explicitly
    available. Missing listing/status data falls back to the ordinary board
    ratio and is marked degraded, so formal admission can fail closed.
    """
    date = pd.Timestamp(trade_date)
    board = infer_board_type(symbol)
    status = str(security_status or "unknown").strip().lower()
    sessions = pd.to_numeric(
        pd.Series([trading_sessions_since_listing]), errors="coerce"
    ).iloc[0]
    listing = pd.to_datetime(listing_date, errors="coerce")
    if pd.isna(sessions) and pd.notna(listing):
        # Calendar age is not silently treated as trading-session age. It is
        # retained only as evidence that the security is not pre-listing.
        sessions = pd.NA
    degraded = pd.isna(sessions) or status in {"", "unknown"}
    registration_main_board = (
        board == "main_board" and date >= pd.Timestamp("2023-04-10")
    )
    opening_no_limit_regime = (
        board in {"star", "bse"}
        or (board == "chinext" and date >= pd.Timestamp("2020-08-24"))
        or registration_main_board
    )
    if (
        opening_no_limit_regime
        and pd.notna(sessions)
        and 1 <= int(sessions) <= 5
    ):
        return DateEffectivePriceLimitRule(
            board_type=board,
            price_limit_ratio=None,
            has_daily_price_limit=False,
            rule_state="initial_listing_no_daily_limit",
            degraded=False,
        )
    if bool(is_st):
        ratio = 0.05
    elif board == "bse":
        ratio = 0.30
    elif board in {"star", "chinext"}:
        ratio = 0.20
    else:
        ratio = 0.10
    if status in {"delisted", "pre_listing"}:
        return DateEffectivePriceLimitRule(
            board_type=board,
            price_limit_ratio=None,
            has_daily_price_limit=False,
            rule_state=f"not_tradable:{status}",
            degraded=False,
        )
    return DateEffectivePriceLimitRule(
        board_type=board,
        price_limit_ratio=ratio,
        has_daily_price_limit=True,
        rule_state="ordinary_daily_limit" if not degraded else "degraded_static_fallback",
        degraded=bool(degraded),
    )
