"""Persistent pending-order state machine with one liquidation intent per symbol."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd

from config import GOVERNANCE_LOCK_ALERT_DAYS, GOVERNANCE_LOCK_HAIRCUT_DAYS


PENDING_ORDER_COLUMNS = [
    "order_id",
    "decision_id",
    "symbol",
    "side",
    "reason",
    "priority",
    "created_date",
    "last_retry_date",
    "target_shares",
    "executed_shares",
    "remaining_shares",
    "retry_count",
    "lock_days",
    "status",
    "block_reason",
    "expired_reason",
    "superseded_by_order_id",
]

SELL_RETRY_REASONS = {"safety_deleveraging", "qualification_exit", "alpha_collapse_consensus"}


class PendingOrderBook:
    """Maintain active orders without duplicating locked sell intents."""

    def __init__(self, orders: pd.DataFrame | None = None):
        self.orders = _ensure_columns(orders)

    def add_order(self, payload: dict) -> str:
        order = {column: pd.NA for column in PENDING_ORDER_COLUMNS}
        order.update(payload)
        order["order_id"] = str(order.get("order_id") if pd.notna(order.get("order_id")) else uuid4())
        order["side"] = str(order["side"]).lower()
        order["created_date"] = pd.Timestamp(order["created_date"])
        order["last_retry_date"] = pd.Timestamp(_value_or(order.get("last_retry_date"), order["created_date"]))
        order["target_shares"] = float(_value_or(order.get("target_shares"), 0.0))
        order["executed_shares"] = float(_value_or(order.get("executed_shares"), 0.0))
        order["remaining_shares"] = float(_value_or(order.get("remaining_shares"), order["target_shares"]))
        order["retry_count"] = int(_value_or(order.get("retry_count"), 0))
        order["lock_days"] = int(_value_or(order.get("lock_days"), 0))
        order["status"] = str(_value_or(order.get("status"), "pending"))
        new_row = pd.DataFrame([order], columns=PENDING_ORDER_COLUMNS)
        self.orders = new_row if self.orders.empty else pd.concat([self.orders, new_row], ignore_index=True)
        return order["order_id"]

    def upsert_sell_intent(self, payload: dict) -> str:
        symbol = str(payload["symbol"])
        active = self.orders[
            (self.orders["symbol"].astype(str) == symbol)
            & (self.orders["side"].astype(str) == "sell")
            & (self.orders["status"].isin(["pending", "pending_locked"]))
        ]
        if active.empty:
            return self.add_order({**payload, "side": "sell"})
        index = active.index[0]
        self.orders.at[index, "target_shares"] = max(
            float(self.orders.at[index, "target_shares"]),
            float(payload.get("target_shares", 0.0)),
        )
        self.orders.at[index, "remaining_shares"] = max(
            float(self.orders.at[index, "remaining_shares"]),
            float(payload.get("target_shares", 0.0)),
        )
        if int(payload.get("priority", 999)) < int(self.orders.at[index, "priority"]):
            self.orders.at[index, "priority"] = int(payload["priority"])
            self.orders.at[index, "reason"] = payload["reason"]
            self.orders.at[index, "decision_id"] = payload["decision_id"]
        return str(self.orders.at[index, "order_id"])

    def settle_day(self, trade_date, fills: dict[str, float] | None = None, blocked_symbols=()) -> pd.DataFrame:
        trade_date = pd.Timestamp(trade_date)
        before = self.orders.copy(deep=True).set_index("order_id", drop=False)
        fills = fills or {}
        blocked = {str(symbol) for symbol in blocked_symbols}
        for index, order in self.orders.iterrows():
            if order["status"] not in {"pending", "pending_locked"}:
                continue
            symbol = str(order["symbol"])
            if symbol in blocked:
                if str(order["side"]) == "buy":
                    self.orders.at[index, "status"] = "expired"
                    self.orders.at[index, "expired_reason"] = "daily_expiry"
                    self.orders.at[index, "block_reason"] = "liquidity_locked"
                    continue
                lock_days = int(order["lock_days"]) + 1
                self.orders.at[index, "lock_days"] = lock_days
                self.orders.at[index, "block_reason"] = "liquidity_locked"
                if str(order["side"]) == "sell" and lock_days > GOVERNANCE_LOCK_HAIRCUT_DAYS:
                    self.orders.at[index, "status"] = "pending_locked"
                continue
            if order["status"] == "pending_locked":
                self.orders.at[index, "status"] = "pending"
                self.orders.at[index, "last_retry_date"] = trade_date
                continue
            executed = min(
                float(fills.get(str(order["order_id"]), fills.get(symbol, 0.0))),
                float(order["remaining_shares"]),
            )
            self.orders.at[index, "executed_shares"] = float(order["executed_shares"]) + executed
            self.orders.at[index, "remaining_shares"] = float(order["remaining_shares"]) - executed
            self.orders.at[index, "last_retry_date"] = trade_date
            self.orders.at[index, "retry_count"] = int(order["retry_count"]) + 1
            if float(self.orders.at[index, "remaining_shares"]) <= 1e-12:
                self.orders.at[index, "status"] = "filled"
            elif str(order["side"]) == "buy":
                self.orders.at[index, "status"] = "expired"
                self.orders.at[index, "expired_reason"] = "daily_expiry"
        changed = []
        for _, order in self.orders.iterrows():
            order_id = str(order["order_id"])
            if order_id not in before.index or not order.equals(before.loc[order_id]):
                payload = order.to_dict()
                payload["snapshot_date"] = trade_date
                payload["event_type"] = "order_state_change"
                changed.append(payload)
        return pd.DataFrame(changed)

    def locked_symbols(self) -> frozenset[str]:
        locked = self.orders[self.orders["status"] == "pending_locked"]["symbol"].astype(str)
        return frozenset(locked)

    def lock_alerts(self) -> pd.DataFrame:
        return self.orders[
            (self.orders["status"] == "pending_locked")
            & (pd.to_numeric(self.orders["lock_days"], errors="coerce") > GOVERNANCE_LOCK_ALERT_DAYS)
        ].copy()


def _ensure_columns(orders: pd.DataFrame | None) -> pd.DataFrame:
    if orders is None or orders.empty:
        return pd.DataFrame(columns=PENDING_ORDER_COLUMNS)
    data = orders.copy()
    for column in PENDING_ORDER_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    return data[PENDING_ORDER_COLUMNS].copy()


def _value_or(value, default):
    return default if value is None or pd.isna(value) else value
