"""Growth quality composite factors."""
from __future__ import annotations

import numpy as np
import pandas as pd


GROWTH_FACTOR_COLUMNS = [
    "revenue_yoy_accel",
    "profit_yoy_accel",
    "deducted_profit_yoy",
    "growth_consistency",
    "revenue_profit_sync",
    "margin_supported_growth",
    "asset_light_growth",
    "growth_stability",
    "growth_surprise",
    "growth_value_combo",
]


def append_growth_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame = frame.sort_values(["stock_code", "trade_date"] if "stock_code" in frame.columns else ["symbol", "trade_date"])
    group_key = "stock_code" if "stock_code" in frame.columns else "symbol"
    grouped = frame.groupby(group_key, sort=False)
    revenue = _num(frame.get("revenue"))
    profit = _num(frame.get("net_profit"))
    deducted = _num(frame.get("deducted_net_profit"))
    assets = _num(frame.get("total_assets"))
    market_cap = _num(frame.get("market_cap"))
    revenue_yoy = revenue / grouped["revenue"].shift(252).replace(0.0, np.nan) - 1.0 if "revenue" in frame.columns else pd.Series(np.nan, index=frame.index)
    profit_yoy = profit / grouped["net_profit"].shift(252).replace(0.0, np.nan) - 1.0 if "net_profit" in frame.columns else pd.Series(np.nan, index=frame.index)
    frame["revenue_yoy_accel"] = revenue_yoy - grouped_apply(revenue_yoy, frame, group_key, 63, "shift")
    frame["profit_yoy_accel"] = profit_yoy - grouped_apply(profit_yoy, frame, group_key, 63, "shift")
    frame["deducted_profit_yoy"] = deducted / grouped["deducted_net_profit"].shift(252).replace(0.0, np.nan) - 1.0 if "deducted_net_profit" in frame.columns else np.nan
    frame["growth_consistency"] = grouped_apply((revenue_yoy > 0).astype(float), frame, group_key, 252, "mean")
    frame["revenue_profit_sync"] = (np.sign(revenue_yoy) == np.sign(profit_yoy)).astype(float)
    margin = profit / revenue.replace(0.0, np.nan)
    frame["margin_supported_growth"] = revenue_yoy.where(margin >= grouped_apply(margin, frame, group_key, 252, "mean"))
    asset_growth = assets / grouped["total_assets"].shift(252).replace(0.0, np.nan) - 1.0 if "total_assets" in frame.columns else pd.Series(np.nan, index=frame.index)
    frame["asset_light_growth"] = revenue_yoy / (asset_growth.abs() + 1e-6)
    frame["growth_stability"] = -grouped_apply(revenue_yoy, frame, group_key, 252, "std")
    frame["growth_surprise"] = revenue_yoy - grouped_apply(revenue_yoy, frame, group_key, 252, "mean")
    frame["growth_value_combo"] = revenue_yoy / (market_cap.rank(pct=True) + 0.05)
    return frame


def grouped_apply(values, frame, group_key: str, window: int, op: str):
    grouped = pd.Series(values, index=frame.index).groupby(frame[group_key], sort=False)
    if op == "mean":
        return grouped.transform(lambda s: s.rolling(window, min_periods=max(20, min(window, 60))).mean())
    if op == "std":
        return grouped.transform(lambda s: s.rolling(window, min_periods=max(20, min(window, 60))).std())
    if op == "shift":
        return grouped.shift(window)
    raise ValueError(op)


def _num(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")
