"""Daily OHLCV capital-flow proxies; these do not claim investor identity."""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_flow_state_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    high = _num(data, "high_nominal", "high")
    low = _num(data, "low_nominal", "low")
    close = _num(data, "close_nominal", "close")
    amount = _num(data, "amount")
    amount_ma = _num(data, "amount_ma20")
    spread = (high - low).replace(0.0, np.nan)
    clv = (((close - low) - (high - close)) / spread).clip(-1.0, 1.0).fillna(0.0)
    amount_ratio = (amount / amount_ma.replace(0.0, np.nan)).clip(lower=1e-6)
    amount_shock = np.log(amount_ratio).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-4.0, 4.0)
    ret_1 = _num(data, "ret_1").fillna(0.0)
    vol_5 = _num(data, "volatility_5")
    vol_20 = _num(data, "volatility_20")
    compression = (1.0 - vol_5 / vol_20.replace(0.0, np.nan)).clip(-1.0, 1.0).fillna(0.0)

    data["flow_close_location_value"] = clv
    data["flow_signed_amount_proxy"] = clv * amount
    data["flow_amount_log_shock"] = amount_shock
    data["flow_volatility_compression"] = compression
    data["flow_accumulation_proxy"] = (clv.clip(lower=0.0) * amount_shock.clip(lower=0.0) * (1.0 + compression.clip(lower=0.0))).clip(0.0, 8.0)
    data["flow_distribution_proxy"] = ((-clv).clip(lower=0.0) * amount_shock.clip(lower=0.0) * (1.0 + (-ret_1).clip(lower=0.0))).clip(0.0, 8.0)
    data["flow_proxy_identity_contract"] = "ohlcv_behavior_proxy_not_investor_identity_v1"
    return data


def _num(data: pd.DataFrame, *columns: str) -> pd.Series:
    for column in columns:
        if column in data.columns:
            return pd.to_numeric(data[column], errors="coerce")
    return pd.Series(float("nan"), index=data.index, dtype=float)
