"""Profitability quality composite factors."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.growth_quality_factors import grouped_apply


PROFITABILITY_FACTOR_COLUMNS = [
    "roe_ttm_ind_neutral",
    "roa_ttm_ind_neutral",
    "gross_margin_ttm",
    "gross_margin_delta",
    "operating_margin_delta",
    "net_margin_stability",
    "roe_delta_qoq",
    "roe_vol_neg",
    "deducted_profit_ratio",
    "piotroski_f_score_proxy",
]


def append_profitability_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    group_key = "stock_code" if "stock_code" in frame.columns else "symbol"
    frame = frame.sort_values([group_key, "trade_date"])
    revenue = _num(frame.get("revenue"))
    profit = _num(frame.get("net_profit"))
    deducted = _num(frame.get("deducted_net_profit"))
    equity = _num(frame.get("total_equity"))
    assets = _num(frame.get("total_assets"))
    roe = profit / equity.replace(0.0, np.nan)
    roa = profit / assets.replace(0.0, np.nan)
    frame["roe_ttm_ind_neutral"] = _industry_neutral(frame, roe)
    frame["roa_ttm_ind_neutral"] = _industry_neutral(frame, roa)
    gross_profit = _num(frame.get("gross_profit", profit))
    operating_profit = _num(frame.get("operating_profit", profit))
    frame["gross_margin_ttm"] = gross_profit / revenue.replace(0.0, np.nan)
    frame["gross_margin_delta"] = frame["gross_margin_ttm"] - grouped_apply(frame["gross_margin_ttm"], frame, group_key, 63, "shift")
    operating_margin = operating_profit / revenue.replace(0.0, np.nan)
    frame["operating_margin_delta"] = operating_margin - grouped_apply(operating_margin, frame, group_key, 63, "shift")
    net_margin = profit / revenue.replace(0.0, np.nan)
    frame["net_margin_stability"] = -grouped_apply(net_margin, frame, group_key, 252, "std")
    frame["roe_delta_qoq"] = roe - grouped_apply(roe, frame, group_key, 63, "shift")
    frame["roe_vol_neg"] = -grouped_apply(roe, frame, group_key, 252, "std")
    frame["deducted_profit_ratio"] = deducted / profit.replace(0.0, np.nan)
    frame["piotroski_f_score_proxy"] = (
        (profit > 0).astype(float)
        + (_num(frame.get("operating_cashflow")) > 0).astype(float)
        + (frame["roe_delta_qoq"] > 0).astype(float)
        + (frame["gross_margin_delta"] > 0).astype(float)
        + (frame["deducted_profit_ratio"] > 0.8).astype(float)
    )
    return frame


def _industry_neutral(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    if "industry" not in frame.columns:
        return values
    return values - values.groupby([frame["trade_date"], frame["industry"]], sort=False).transform("median")


def _num(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")
