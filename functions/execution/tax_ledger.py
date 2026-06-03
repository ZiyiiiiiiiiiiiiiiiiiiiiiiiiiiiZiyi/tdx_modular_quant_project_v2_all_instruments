# -*- coding: utf-8 -*-
"""Exploratory tax ledger with explicit policy assumptions."""
from __future__ import annotations

import pandas as pd

from config import (
    DIVIDEND_TAX_ASSUMPTION,
    TAX_MODEL_LIMITATIONS,
    TAX_POLICY_VERSION,
    TRANSFER_FEE_RATE,
)


TAX_LEDGER_COLUMNS = [
    "trade_date",
    "symbol",
    "tax_type",
    "tax_amount",
    "tax_policy_version",
    "dividend_tax_assumption",
    "tax_model_limitations",
]


def build_trade_tax_ledger(order_ledger: pd.DataFrame) -> pd.DataFrame:
    if order_ledger.empty:
        return pd.DataFrame(columns=TAX_LEDGER_COLUMNS)
    data = order_ledger.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["trade_notional"] = pd.to_numeric(data.get("trade_notional"), errors="coerce").fillna(0.0)
    data["stamp_duty_cost"] = pd.to_numeric(data.get("stamp_duty_cost"), errors="coerce").fillna(0.0)
    filled = data[data.get("execution_status", "") == "filled"].copy()
    rows = []
    for _, order in filled.iterrows():
        if float(order["stamp_duty_cost"]) > 0:
            rows.append(_tax_row(order, "stamp_duty", float(order["stamp_duty_cost"])))
        transfer_fee = float(order.get("transfer_fee_cost", float(order["trade_notional"]) * float(TRANSFER_FEE_RATE)))
        if transfer_fee > 0:
            rows.append(_tax_row(order, "transfer_fee", transfer_fee))
    return pd.DataFrame(rows, columns=TAX_LEDGER_COLUMNS)


def tax_ledger_total(tax_ledger: pd.DataFrame) -> float:
    if tax_ledger.empty:
        return 0.0
    return float(pd.to_numeric(tax_ledger["tax_amount"], errors="coerce").fillna(0.0).sum())


def _tax_row(order, tax_type, amount):
    return {
        "trade_date": order["trade_date"],
        "symbol": order["symbol"],
        "tax_type": tax_type,
        "tax_amount": amount,
        "tax_policy_version": TAX_POLICY_VERSION,
        "dividend_tax_assumption": DIVIDEND_TAX_ASSUMPTION,
        "tax_model_limitations": TAX_MODEL_LIMITATIONS,
    }
