# -*- coding: utf-8 -*-
"""Conservative valuation ledger for blocked daily orders."""
from __future__ import annotations

import pandas as pd

from config import (
    LIMIT_DOWN_LIQUIDITY_DISCOUNT,
    VALUATION_ASSUMPTION,
    VALUATION_MODEL_VERSION,
)


VALUATION_LEDGER_COLUMNS = [
    "trade_date",
    "symbol",
    "freeze_type",
    "nominal_value",
    "economic_value",
    "valuation_discount",
    "valuation_model_version",
    "valuation_assumption",
]


def build_blocked_order_valuation_ledger(order_ledger: pd.DataFrame) -> pd.DataFrame:
    if order_ledger.empty:
        return pd.DataFrame(columns=VALUATION_LEDGER_COLUMNS)
    data = order_ledger[order_ledger.get("execution_status", "") != "filled"].copy()
    if data.empty:
        return pd.DataFrame(columns=VALUATION_LEDGER_COLUMNS)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["nominal_value"] = (
        pd.to_numeric(data.get("remaining_shares"), errors="coerce").fillna(0.0)
        * pd.to_numeric(data.get("price"), errors="coerce").fillna(0.0)
    )
    data["freeze_type"] = data.apply(_freeze_type, axis=1)
    data["valuation_discount"] = data["freeze_type"].map(
        {
            "limit_down_liquidity_freeze": float(LIMIT_DOWN_LIQUIDITY_DISCOUNT),
            "trading_suspension_freeze": float(LIMIT_DOWN_LIQUIDITY_DISCOUNT),
            "corporate_action_freeze": 0.0,
            "unsupported_event_freeze": float(LIMIT_DOWN_LIQUIDITY_DISCOUNT),
        }
    ).fillna(0.0)
    data["economic_value"] = data["nominal_value"] * (1.0 - data["valuation_discount"])
    data["valuation_model_version"] = VALUATION_MODEL_VERSION
    data["valuation_assumption"] = VALUATION_ASSUMPTION
    return data[VALUATION_LEDGER_COLUMNS].copy()


def valuation_discount_by_date(valuation_ledger: pd.DataFrame) -> pd.DataFrame:
    if valuation_ledger.empty:
        return pd.DataFrame(columns=["date", "valuation_discount_amount"])
    data = valuation_ledger.copy()
    data["valuation_discount_amount"] = data["nominal_value"] - data["economic_value"]
    return (
        data.groupby("trade_date", as_index=False)["valuation_discount_amount"]
        .sum()
        .rename(columns={"trade_date": "date"})
    )


def _freeze_type(row):
    if bool(row.get("suspension_blocked", False)):
        return "trading_suspension_freeze"
    if bool(row.get("price_limit_blocked", False)) and str(row.get("side", "")) == "sell":
        return "limit_down_liquidity_freeze"
    if str(row.get("execution_status", "")) == "pending_cash":
        return "corporate_action_freeze"
    return "unsupported_event_freeze"
