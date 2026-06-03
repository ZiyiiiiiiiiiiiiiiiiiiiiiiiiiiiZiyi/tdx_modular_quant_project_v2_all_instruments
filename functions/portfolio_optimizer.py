# -*- coding: utf-8 -*-
import pandas as pd


def equal_weight_portfolio(selection_df, max_weight=1.0):
    frame = selection_df.copy()
    if frame.empty:
        frame["target_weight"] = []
        return frame
    n = len(frame)
    frame["target_weight"] = min(1.0 / n, max_weight)
    return frame


def inverse_vol_portfolio(selection_df, volatility_col="volatility_20", max_weight=1.0):
    frame = selection_df.copy()
    if frame.empty:
        frame["target_weight"] = []
        return frame
    inv_vol = 1.0 / frame[volatility_col].replace(0, pd.NA).fillna(frame[volatility_col].median())
    raw_weight = inv_vol / inv_vol.sum()
    frame["target_weight"] = raw_weight.clip(upper=max_weight)
    frame["target_weight"] = frame["target_weight"] / frame["target_weight"].sum()
    return frame


def apply_sector_cap(selection_df, sector_col="sector_parent", cap=0.4):
    frame = selection_df.copy()
    if frame.empty or sector_col not in frame.columns or "target_weight" not in frame.columns:
        return frame
    sector_sum = frame.groupby(sector_col)["target_weight"].transform("sum")
    scale = (cap / sector_sum).clip(upper=1.0)
    frame["target_weight"] = frame["target_weight"] * scale
    if frame["target_weight"].sum() > 0:
        frame["target_weight"] = frame["target_weight"] / frame["target_weight"].sum()
    return frame
