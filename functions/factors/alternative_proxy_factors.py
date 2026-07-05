"""Alternative-data proxy factors.

These proxies use only price/volume/turnover/event-density fields already
available in the project. They do not pretend to be real news, research, search,
or social-media datasets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


ALTERNATIVE_PROXY_COLUMNS = [
    "attention_volume_spike",
    "attention_turnover_spike",
    "attention_amount_spike",
    "crowding_short_term_return_turnover",
    "crowding_volatility_turnover",
    "disagreement_amplitude_turnover",
    "limit_up_attention",
    "limit_up_failure_risk",
    "announcement_density_proxy",
    "industry_heat_proxy",
]


def append_alternative_proxy_factors(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    frame = df.copy()
    symbol_col = "symbol" if "symbol" in frame.columns else "stock_code"
    date_col = "date" if "date" in frame.columns else "trade_date"
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.sort_values([symbol_col, date_col])
    grouped = frame.groupby(symbol_col, sort=False)
    volume = _num(frame.get("volume"))
    amount = _num(frame.get("amount"))
    turnover = _num(frame.get("turnover_rate", amount / _num(frame.get("market_cap")).replace(0.0, np.nan)))
    close = _num(frame.get("close_nominal", frame.get("close")))
    high = _num(frame.get("high_nominal", frame.get("high", close)))
    low = _num(frame.get("low_nominal", frame.get("low", close)))
    ret_5 = close / grouped[close.name if close.name in frame.columns else frame.columns[0]].shift(5).replace(0.0, np.nan) - 1.0 if close.name in frame.columns else pd.Series(np.nan, index=frame.index)
    frame["attention_volume_spike"] = volume / grouped_apply(volume, frame, symbol_col, 20, "mean").replace(0.0, np.nan) - 1.0
    frame["attention_turnover_spike"] = turnover / grouped_apply(turnover, frame, symbol_col, 20, "mean").replace(0.0, np.nan) - 1.0
    frame["attention_amount_spike"] = amount / grouped_apply(amount, frame, symbol_col, 20, "mean").replace(0.0, np.nan) - 1.0
    frame["crowding_short_term_return_turnover"] = ret_5 * _rank_by_date(turnover, frame[date_col])
    vol20 = grouped_apply(close.pct_change().abs(), frame, symbol_col, 20, "mean")
    frame["crowding_volatility_turnover"] = vol20 * _rank_by_date(turnover, frame[date_col])
    amplitude = (high - low) / close.replace(0.0, np.nan)
    frame["disagreement_amplitude_turnover"] = amplitude * _rank_by_date(turnover, frame[date_col])
    limit_up = _num(frame.get("limit_up_flag", pd.Series(0, index=frame.index))).fillna(0.0)
    frame["limit_up_attention"] = limit_up * (1.0 + frame["attention_amount_spike"].clip(lower=0.0))
    frame["limit_up_failure_risk"] = _num(frame.get("limit_up_open_break", pd.Series(0, index=frame.index))).fillna(0.0)
    frame["announcement_density_proxy"] = _num(frame.get("announcement_density", pd.Series(np.nan, index=frame.index)))
    if "industry" in frame.columns:
        frame["industry_heat_proxy"] = _rank_by_date(amount.groupby([frame[date_col], frame["industry"]], sort=False).transform("mean"), frame[date_col])
    else:
        frame["industry_heat_proxy"] = np.nan
    return frame


def grouped_apply(values, frame, group_key: str, window: int, op: str):
    grouped = pd.Series(values, index=frame.index).groupby(frame[group_key], sort=False)
    if op == "mean":
        return grouped.transform(lambda s: s.rolling(window, min_periods=max(5, min(window, 10))).mean())
    raise ValueError(op)


def _rank_by_date(values, dates):
    return pd.Series(values).groupby(dates, sort=False).rank(pct=True)


def _num(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")
