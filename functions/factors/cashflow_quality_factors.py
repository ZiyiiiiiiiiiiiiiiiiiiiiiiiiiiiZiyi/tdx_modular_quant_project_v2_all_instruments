"""Cash-flow quality factors from explicit PIT TTM inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.fundamental_pit_factors import prepare_financial_report_factors


CASHFLOW_FACTOR_COLUMNS = [
    "ocf_to_net_profit", "ocf_to_revenue", "fcf_yield", "ocf_growth",
    "ocf_growth_accel", "accruals_neg", "cash_profit_quality",
    "capex_intensity_neg", "cashflow_stability", "ocf_margin_delta",
]


def append_cashflow_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = _prepared(df)
    for column in CASHFLOW_FACTOR_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    if "capex_to_assets" in frame.columns:
        frame["capex_intensity_neg"] = -pd.to_numeric(frame["capex_to_assets"], errors="coerce")
    # FCF yield is intentionally not recomputed here: it requires an explicit
    # PIT market-cap join and is produced by append_daily_fundamental_factors.
    return frame


def _prepared(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if {"symbol", "known_at", "effective_from", "period_value_basis"}.issubset(df.columns):
        return prepare_financial_report_factors(df)
    return df.copy()
