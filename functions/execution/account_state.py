# -*- coding: utf-8 -*-
"""Minimal account state machine with explicit A-share cash boundaries."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date


@dataclass(frozen=True)
class CashState:
    settled_cash: float
    unsettled_available_cash: float = 0.0
    withdrawable_cash: float = 0.0
    frozen_cash: float = 0.0
    pending_receivable_cash: float = 0.0
    eligible_receivables: float = 0.0

    @property
    def available_cash(self) -> float:
        return (
            self.settled_cash
            + self.unsettled_available_cash
            - self.frozen_cash
            + self.eligible_receivables
        )


@dataclass(frozen=True)
class PositionState:
    symbol: str
    position_shares: int
    sellable_shares: int
    locked_shares: int = 0
    odd_lot_shares: int = 0
    cost_basis: float = 0.0
    acquisition_trade_date: date | None = None
    locked_until: date | None = None


@dataclass(frozen=True)
class RightsIssueState:
    symbol: str
    entitlement_shares: int
    payment_deadline: date
    subscribed_shares: int = 0
    abandoned_shares: int = 0
    status: str = "open"


def receive_cash_dividend(cash: CashState, amount: float) -> CashState:
    """Record dividend as pending until its explicit payment timestamp."""
    return replace(cash, pending_receivable_cash=cash.pending_receivable_cash + float(amount))


def settle_cash_dividend(cash: CashState, amount: float) -> CashState:
    amount = float(amount)
    if amount > cash.pending_receivable_cash + 1e-12:
        raise ValueError("Dividend settlement exceeds pending receivable cash")
    return replace(
        cash,
        settled_cash=cash.settled_cash + amount,
        withdrawable_cash=cash.withdrawable_cash + amount,
        pending_receivable_cash=cash.pending_receivable_cash - amount,
    )


def record_sale_proceeds(cash: CashState, amount: float) -> CashState:
    """Sale proceeds are buyable on trade date but not withdrawable."""
    return replace(
        cash,
        unsettled_available_cash=cash.unsettled_available_cash + float(amount),
    )


def settle_sale_proceeds(cash: CashState) -> CashState:
    amount = cash.unsettled_available_cash
    return replace(
        cash,
        settled_cash=cash.settled_cash + amount,
        withdrawable_cash=cash.withdrawable_cash + amount,
        unsettled_available_cash=0.0,
    )


def freeze_rights_issue_cash(cash: CashState, amount: float) -> CashState:
    amount = float(amount)
    if amount > cash.available_cash + 1e-12:
        raise ValueError("Insufficient available cash for rights-issue subscription")
    return replace(cash, frozen_cash=cash.frozen_cash + amount)


def release_frozen_cash(cash: CashState, amount: float) -> CashState:
    amount = float(amount)
    if amount > cash.frozen_cash + 1e-12:
        raise ValueError("Released cash exceeds frozen cash")
    return replace(cash, frozen_cash=cash.frozen_cash - amount)


def subscribe_rights_issue(
    cash: CashState,
    rights: RightsIssueState,
    *,
    shares: int,
    price: float,
    order_date: date,
    order_accepted: bool = True,
) -> tuple[CashState, RightsIssueState]:
    if order_date > rights.payment_deadline:
        raise ValueError("Rights-issue payment window has expired")
    if rights.status not in {"open", "partial_subscribed", "order_failed"}:
        raise ValueError("Rights issue is not open for subscription")
    remaining = rights.entitlement_shares - rights.subscribed_shares - rights.abandoned_shares
    requested = min(max(int(shares), 0), remaining)
    if not order_accepted:
        return cash, replace(rights, status="order_failed")
    affordable = int(cash.available_cash // float(price))
    subscribed = min(requested, affordable)
    abandoned = requested - subscribed
    frozen_amount = subscribed * float(price)
    next_cash = freeze_rights_issue_cash(cash, frozen_amount) if frozen_amount else cash
    total_subscribed = rights.subscribed_shares + subscribed
    total_abandoned = rights.abandoned_shares + abandoned
    status = (
        "fully_subscribed"
        if total_subscribed == rights.entitlement_shares
        else "partial_subscribed"
    )
    return next_cash, replace(
        rights,
        subscribed_shares=total_subscribed,
        abandoned_shares=total_abandoned,
        status=status,
    )


def expire_rights_issue(rights: RightsIssueState, as_of: date) -> RightsIssueState:
    if as_of <= rights.payment_deadline:
        return rights
    remaining = rights.entitlement_shares - rights.subscribed_shares - rights.abandoned_shares
    return replace(
        rights,
        abandoned_shares=rights.abandoned_shares + remaining,
        status="expired",
    )


def buy_stock(position: PositionState | None, symbol: str, shares: int, price: float, trade_date: date) -> PositionState:
    """Stock bought today increases position shares but remains T+1 locked."""
    shares = int(shares)
    if shares <= 0:
        raise ValueError("Buy shares must be positive")
    current = position or PositionState(symbol=symbol, position_shares=0, sellable_shares=0)
    if current.symbol != symbol:
        raise ValueError("Position symbol mismatch")
    total_cost = current.cost_basis * current.position_shares + float(price) * shares
    new_total = current.position_shares + shares
    return replace(
        current,
        position_shares=new_total,
        locked_shares=current.locked_shares + shares,
        cost_basis=total_cost / new_total,
        acquisition_trade_date=trade_date,
        locked_until=trade_date,
    )


def unlock_t_plus_one(position: PositionState) -> PositionState:
    return replace(
        position,
        sellable_shares=position.sellable_shares + position.locked_shares,
        locked_shares=0,
        locked_until=None,
    )


def sell_stock(position: PositionState, shares: int) -> PositionState:
    shares = int(shares)
    if shares <= 0:
        raise ValueError("Sell shares must be positive")
    if shares > position.sellable_shares:
        raise ValueError("T+1 or other lock prevents selling requested shares")
    return replace(
        position,
        position_shares=position.position_shares - shares,
        sellable_shares=position.sellable_shares - shares,
        odd_lot_shares=max(position.odd_lot_shares - min(position.odd_lot_shares, shares), 0),
    )


def apply_stock_dividend(position: PositionState, ratio: float, lot_size: int = 100) -> PositionState:
    """Apply stock dividend shares and preserve odd-lot visibility."""
    added_shares = int(position.position_shares * float(ratio))
    new_total = position.position_shares + added_shares
    return replace(
        position,
        position_shares=new_total,
        sellable_shares=position.sellable_shares + added_shares,
        odd_lot_shares=new_total % int(lot_size),
    )
