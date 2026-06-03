"""Leakage-aware governance labels for later supervised safety training."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_MOMENTUM_REBOUND_DRAWDOWN, GOVERNANCE_MOMENTUM_REBOUND_RETURN


def apply_governance_labels(feature_df: pd.DataFrame, *, price_col: str = "close") -> pd.DataFrame:
    """Attach future labels as targets only; callers must exclude them from features."""
    data = feature_df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.sort_values(["symbol", "date"])
    grouped = data.groupby("symbol", group_keys=False)
    close = pd.to_numeric(data[price_col], errors="coerce")
    for horizon in (5, 10, 20):
        future_close = grouped[price_col].shift(-horizon)
        data[f"future_ret_{horizon}"] = pd.to_numeric(future_close, errors="coerce") / close - 1.0
    future_path = [close]
    for offset in range(1, 6):
        future_path.append(pd.to_numeric(grouped[price_col].shift(-offset), errors="coerce"))
    path = pd.concat(future_path, axis=1)
    path.columns = [f"t_plus_{offset}" for offset in range(6)]
    running_peak = path.cummax(axis=1)
    data["future_max_drawdown_5"] = ((running_peak - path) / running_peak).max(axis=1)
    data["market_crash_label_5d"] = (data["future_max_drawdown_5"] >= 0.05).astype("Int64")
    if "rough_limit_down" in data.columns or "is_trading" in data.columns:
        locked = (
            data.get("rough_limit_down", pd.Series(False, index=data.index)).fillna(False).astype(bool)
            | ~data.get("is_trading", pd.Series(True, index=data.index)).fillna(False).astype(bool)
        )
        future_locked = [
            locked.groupby(data["symbol"]).shift(-offset).astype("boolean").fillna(False)
            for offset in range(1, 6)
        ]
        data["liquidity_lock_label_5d"] = pd.concat(future_locked, axis=1).any(axis=1).astype("Int64")
    else:
        data["liquidity_lock_label_5d"] = pd.Series(pd.NA, index=data.index, dtype="Int64")
    data["label_window_start"] = data["date"] + pd.offsets.BDay(1)
    data["label_window_end"] = data["date"] + pd.offsets.BDay(20)
    return data


def apply_momentum_rebound_regime(market_daily: pd.DataFrame, *, price_col="market_proxy_close") -> pd.DataFrame:
    """Mark post-drawdown rebound states where momentum strategies require a veto review."""
    data = market_daily.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    price = pd.to_numeric(data[price_col], errors="coerce")
    data["market_return_5d"] = price.pct_change(5, fill_method=None)
    data["market_return_20d"] = price.pct_change(20, fill_method=None)
    data["momentum_rebound_regime"] = (
        (data["market_return_20d"].shift(5) <= GOVERNANCE_MOMENTUM_REBOUND_DRAWDOWN)
        & (data["market_return_5d"] >= GOVERNANCE_MOMENTUM_REBOUND_RETURN)
    ).astype(int)
    return data
