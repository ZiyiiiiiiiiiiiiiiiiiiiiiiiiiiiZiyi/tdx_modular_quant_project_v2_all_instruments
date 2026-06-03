# -*- coding: utf-8 -*-
import pandas as pd


PRICE_BASE_COLUMNS = ["open", "high", "low", "close"]
NOMINAL_PRICE_COLUMNS = [f"{name}_nominal" for name in PRICE_BASE_COLUMNS]
ADJUSTED_PRICE_COLUMNS = [f"{name}_adj_forward" for name in PRICE_BASE_COLUMNS]
POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS = [f"{name}_adj_pti" for name in PRICE_BASE_COLUMNS]


def attach_nominal_price_columns(df):
    data = df.copy()
    for source_col, nominal_col in zip(PRICE_BASE_COLUMNS, NOMINAL_PRICE_COLUMNS):
        if source_col in data.columns:
            data[nominal_col] = pd.to_numeric(data[source_col], errors="coerce")
        else:
            data[nominal_col] = pd.NA
    return data


def attach_forward_adjusted_price_columns(df, factor_col="forward_factor"):
    data = df.copy()
    factors = pd.to_numeric(data.get(factor_col), errors="coerce")
    data["adj_factor_available"] = factors.notna()
    for source_col, adjusted_col in zip(PRICE_BASE_COLUMNS, ADJUSTED_PRICE_COLUMNS):
        source_values = pd.to_numeric(data.get(source_col), errors="coerce")
        data[adjusted_col] = source_values * factors
    return data


def attach_point_in_time_adjusted_price_columns(df, factor_col="backward_factor"):
    """Build a signal-price view using factors observable no later than each bar."""
    data = df.copy()
    factors = pd.to_numeric(data.get(factor_col), errors="coerce")
    data["adj_factor_available"] = factors.notna() & factors.gt(0)
    for source_col, adjusted_col in zip(PRICE_BASE_COLUMNS, POINT_IN_TIME_ADJUSTED_PRICE_COLUMNS):
        source_values = pd.to_numeric(data.get(source_col), errors="coerce")
        data[adjusted_col] = source_values * factors
    return data


def build_dual_price_view(df, factor_col="forward_factor"):
    data = attach_nominal_price_columns(df)
    data = attach_forward_adjusted_price_columns(data, factor_col=factor_col)
    return data


def validate_dual_price_columns(df):
    missing = []
    for col in NOMINAL_PRICE_COLUMNS + ADJUSTED_PRICE_COLUMNS:
        if col not in df.columns:
            missing.append(col)
    return missing
