# -*- coding: utf-8 -*-
"""Normalized corporate-action ledger for exploratory accounting."""
from __future__ import annotations

import pandas as pd


CORPORATE_ACTION_LEDGER_COLUMNS = [
    "symbol",
    "action_type",
    "announcement_date",
    "record_date",
    "ex_date",
    "payment_date",
    "rights_payment_start_date",
    "rights_payment_end_date",
    "cash_dividend",
    "stock_dividend_ratio",
    "rights_issue_ratio",
    "rights_issue_price",
    "revision_timestamp",
    "pit_complete",
    "unsupported_event_type",
]

SUPPORTED_ACTION_TYPES = {
    "cash_dividend",
    "dividend",
    "stock_dividend",
    "capitalization",
    "rights_issue",
    "split",
    "reverse_split",
}


def build_corporate_action_ledger(actions: pd.DataFrame) -> pd.DataFrame:
    if actions.empty:
        return pd.DataFrame(columns=CORPORATE_ACTION_LEDGER_COLUMNS)
    data = actions.copy()
    result = pd.DataFrame(index=data.index)
    result["symbol"] = data.get("symbol")
    result["action_type"] = data.get("action_type", "").astype(str).str.strip().str.lower()
    result["announcement_date"] = _date_column(data, "announcement_date")
    result["record_date"] = _date_column(data, "record_date")
    result["ex_date"] = _date_column(data, "ex_date", fallback="action_date")
    result["payment_date"] = _date_column(data, "payment_date")
    result["rights_payment_start_date"] = _date_column(data, "rights_payment_start_date")
    result["rights_payment_end_date"] = _date_column(data, "rights_payment_end_date")
    for column in ["cash_dividend", "stock_dividend_ratio", "rights_issue_ratio", "rights_issue_price"]:
        result[column] = pd.to_numeric(data.get(column), errors="coerce")
    result["revision_timestamp"] = pd.to_datetime(data.get("revision_timestamp"), errors="coerce")
    result["pit_complete"] = (
        result["announcement_date"].notna()
        & result["ex_date"].notna()
        & result["revision_timestamp"].notna()
    )
    result["unsupported_event_type"] = ~result["action_type"].isin(SUPPORTED_ACTION_TYPES)
    return result[CORPORATE_ACTION_LEDGER_COLUMNS].copy()


def _date_column(data, column, fallback=None):
    source = data.get(column)
    if source is None and fallback is not None:
        source = data.get(fallback)
    return pd.to_datetime(source, errors="coerce")
