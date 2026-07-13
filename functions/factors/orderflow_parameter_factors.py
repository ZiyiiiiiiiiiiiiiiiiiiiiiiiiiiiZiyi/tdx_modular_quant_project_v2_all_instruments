"""Executable daily OHLCV proxy factors used by parameter research.

These are explicitly proxies. They do not represent tick-level order flow.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd


WINDOWS = (5, 10, 20, 40)
SMOOTHING_WINDOWS = (1, 3, 5)
FAMILIES = ("amount_shock", "close_drive", "accumulation", "efficiency")
BREAKOUT_FAMILIES = ("price_volume_breakout", "turtle_breakout")
_COLUMN_RE = re.compile(
    r"^cand_(?P<family>orderflow_(?:amount_shock|close_drive|accumulation|efficiency)|"
    r"(?:price_volume|turtle)_breakout)_w(?P<window>\d+)_s(?P<smooth>\d+)$"
)


def parameter_factor_specs() -> list[dict]:
    rows = []
    for family in FAMILIES:
        for window in WINDOWS:
            for smooth in SMOOTHING_WINDOWS:
                name = f"orderflow_{family}_w{window}_s{smooth}"
                rows.append(_spec(name, role="liquidity_filter", family="orderflow_proxy"))
    for family in BREAKOUT_FAMILIES:
        for window in WINDOWS:
            for smooth in SMOOTHING_WINDOWS:
                name = f"{family}_w{window}_s{smooth}"
                rows.append(_spec(name, role="timing_filter", family="breakout"))
    return rows


def _spec(name: str, *, role: str, family: str) -> dict:
    economic_family = name.rsplit("_w", 1)[0]
    return {
        "factor_name": name,
        "raw_column": f"cand_{name}",
        "module": family,
        "factor_family": family,
        "economic_family": economic_family,
        "role": role,
        "direction": "higher_better",
        "parameter_version": "daily_ohlcv_proxy_grid_v1",
    }


def parameter_raw_columns() -> set[str]:
    return {row["raw_column"] for row in parameter_factor_specs()}


def append_parameterized_orderflow_factors(
    frame: pd.DataFrame,
    *,
    include_columns: set[str] | list[str] | tuple[str, ...] | None = None,
    close_col: str = "close",
) -> pd.DataFrame:
    requested = parameter_raw_columns() if include_columns is None else set(include_columns) & parameter_raw_columns()
    if frame is None or frame.empty or not requested:
        return frame
    data = frame.copy(deep=False).sort_values(["symbol", "date"])
    close = _num(data.get(close_col, data.get("close")))
    open_ = _num(data.get(_price_col(close_col, "open"), data.get("open")))
    high = _num(data.get(_price_col(close_col, "high"), data.get("high")))
    low = _num(data.get(_price_col(close_col, "low"), data.get("low")))
    amount = _num(data.get("amount", pd.Series(np.nan, index=data.index))).clip(lower=0.0)
    volume = _num(data.get("volume", pd.Series(np.nan, index=data.index))).clip(lower=0.0)
    grouped_close = close.groupby(data["symbol"], sort=False)
    grouped_amount = amount.groupby(data["symbol"], sort=False)
    grouped_volume = volume.groupby(data["symbol"], sort=False)
    ret_1 = grouped_close.pct_change(fill_method=None)
    price_range = (high - low).replace(0.0, np.nan)
    close_location = ((close - low) / price_range - 0.5) * 2.0
    intraday_return = close / open_.replace(0.0, np.nan) - 1.0
    body_ratio = (close - open_).abs() / price_range
    generated = {}
    for column in sorted(requested):
        match = _COLUMN_RE.match(column)
        if not match:
            continue
        family = match.group("family")
        window = int(match.group("window"))
        smooth = int(match.group("smooth"))
        amount_mean = grouped_amount.transform(lambda s, w=window: s.rolling(w, min_periods=w).mean())
        volume_mean = grouped_volume.transform(lambda s, w=window: s.rolling(w, min_periods=w).mean())
        intensity = amount / amount_mean.replace(0.0, np.nan)
        if family == "orderflow_amount_shock":
            base = np.log1p(amount) - np.log1p(amount).groupby(data["symbol"], sort=False).transform(
                lambda s, w=window: s.rolling(w, min_periods=w).mean()
            )
        elif family == "orderflow_close_drive":
            base = close_location * intensity
        elif family == "orderflow_accumulation":
            base = intraday_return * body_ratio * intensity
        elif family == "orderflow_efficiency":
            volatility = ret_1.groupby(data["symbol"], sort=False).transform(
                lambda s, w=window: s.rolling(w, min_periods=w).std()
            )
            base = ret_1 / (volatility.abs() + 0.01) * intensity
        else:
            prior_high = grouped_close.transform(
                lambda s, w=window: s.shift(1).rolling(w, min_periods=w).max()
            )
            breakout = close / prior_high.replace(0.0, np.nan) - 1.0
            if family == "price_volume_breakout":
                volume_ratio = volume / volume_mean.replace(0.0, np.nan)
                base = (breakout * volume_ratio).where((breakout > 0.0) & (volume_ratio >= 1.2))
            else:
                base = breakout.where(breakout > 0.0)
        if smooth > 1:
            base = base.groupby(data["symbol"], sort=False).transform(
                lambda s, w=smooth: s.rolling(w, min_periods=w).mean()
            )
        generated[column] = pd.to_numeric(base, errors="coerce").astype("float32")
    if not generated:
        return data
    return pd.concat([data, pd.DataFrame(generated, index=data.index)], axis=1)


def _price_col(close_col: str, prefix: str) -> str:
    suffix = str(close_col).removeprefix("close")
    return f"{prefix}{suffix}"


def _num(value) -> pd.Series:
    return pd.to_numeric(value, errors="coerce")
