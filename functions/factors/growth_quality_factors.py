"""Growth-quality factors sourced exclusively from PIT report-period metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.fundamental_pit_factors import prepare_financial_report_factors


GROWTH_FACTOR_COLUMNS = [
    "revenue_yoy_accel", "profit_yoy_accel", "deducted_profit_yoy",
    "growth_consistency", "revenue_profit_sync", "margin_supported_growth",
    "asset_light_growth", "growth_stability", "growth_surprise",
    "growth_value_combo",
]


def append_growth_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = _prepared(df)
    for column in GROWTH_FACTOR_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    if "asset_growth" in frame.columns and "revenue_yoy" in frame.columns:
        asset_growth = pd.to_numeric(frame["asset_growth"], errors="coerce")
        frame["asset_light_growth"] = (
            pd.to_numeric(frame["revenue_yoy"], errors="coerce")
            / (asset_growth.abs() + 1e-6)
        )
    # The value leg is added only after a PIT valuation join. Market-cap rank is
    # deliberately not used as a substitute for valuation.
    if "earnings_yield_ttm" in frame.columns:
        frame["growth_value_combo"] = (
            pd.to_numeric(frame["profit_yoy_accel"], errors="coerce")
            * pd.to_numeric(frame["earnings_yield_ttm"], errors="coerce")
        )
    return frame


def _prepared(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if {"symbol", "known_at", "effective_from", "period_value_basis"}.issubset(df.columns):
        return prepare_financial_report_factors(df)
    return df.copy()
