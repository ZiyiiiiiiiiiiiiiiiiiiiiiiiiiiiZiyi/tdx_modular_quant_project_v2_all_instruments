# -*- coding: utf-8 -*-
import pandas as pd


def compute_advanced_price_volume_features(df):
    data = df.copy()
    data = data.sort_values(["symbol", "date"]).copy()
    grouped = data.groupby("symbol", group_keys=False)

    prev_close = grouped["close"].shift(1)
    prev_high_20 = grouped["high"].transform(lambda s: s.shift(1).rolling(20).max())
    prev_low_20 = grouped["low"].transform(lambda s: s.shift(1).rolling(20).min())
    volume_ma_20 = grouped["volume"].transform(lambda s: s.rolling(20).mean())

    data["gap_1"] = data["open"] / prev_close - 1
    data["breakout_strength_20"] = data["close"] / prev_high_20 - 1
    data["pullback_depth_20"] = data["close"] / prev_low_20 - 1
    data["volume_shock_20"] = data["volume"] / volume_ma_20 - 1
    return data
