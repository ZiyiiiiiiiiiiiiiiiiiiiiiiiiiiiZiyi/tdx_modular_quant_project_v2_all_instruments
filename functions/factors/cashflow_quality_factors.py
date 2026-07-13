"""Cashflow quality composite factors."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.growth_quality_factors import grouped_apply


CASHFLOW_FACTOR_COLUMNS = [
    "ocf_to_net_profit",
    "ocf_to_revenue",
    "fcf_yield",
    "ocf_growth",
    "ocf_growth_accel",
    "accruals_neg",
    "cash_profit_quality",
    "capex_intensity_neg",
    "cashflow_stability",
    "ocf_margin_delta",
]


def append_cashflow_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    group_key = "stock_code" if "stock_code" in frame.columns else "symbol"
    frame = frame.sort_values([group_key, "trade_date"])
    ocf = _num(frame.get("operating_cashflow"))
    revenue = _num(frame.get("revenue"))
    profit = _num(frame.get("net_profit"))
    deducted = _num(frame.get("deducted_net_profit"))
    market_cap = _num(frame.get("market_cap"))
    capex = _num(frame.get("capex", pd.Series(np.nan, index=frame.index)))
    frame["ocf_to_net_profit"] = ocf / profit.replace(0.0, np.nan)
    frame["ocf_to_revenue"] = ocf / revenue.replace(0.0, np.nan)
    fcf = ocf - capex.fillna(0.0)
    frame["fcf_yield"] = fcf / market_cap.replace(0.0, np.nan)
    ocf_yoy = ocf / ocf.groupby(frame[group_key], sort=False).shift(252).replace(0.0, np.nan) - 1.0
    frame["ocf_growth"] = ocf_yoy
    frame["ocf_growth_accel"] = ocf_yoy - grouped_apply(ocf_yoy, frame, group_key, 63, "shift")
    assets = _num(frame.get("total_assets"))
    frame["accruals_neg"] = -((profit - ocf) / assets.replace(0.0, np.nan))
    frame["cash_profit_quality"] = ocf / deducted.replace(0.0, np.nan)
    frame["capex_intensity_neg"] = -(capex / revenue.replace(0.0, np.nan))
    frame["cashflow_stability"] = -grouped_apply(frame["ocf_to_revenue"], frame, group_key, 252, "std")
    frame["ocf_margin_delta"] = frame["ocf_to_revenue"] - grouped_apply(frame["ocf_to_revenue"], frame, group_key, 63, "shift")
    return frame


def _num(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")
