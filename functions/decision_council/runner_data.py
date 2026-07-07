"""Feature preparation helpers for governance backtest runners."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_ALPHA_MODEL_FEATURES


def prepare_features(feature_df, *, copy: bool = True):
    data = feature_df.copy() if copy else feature_df
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for target, fallback in (("open_nominal", "open"), ("close_nominal", "close")):
        if target not in data.columns:
            data[target] = data[fallback]
    for column in ("rough_limit_up", "rough_limit_down", "abnormal_jump"):
        if column not in data.columns:
            data[column] = False
    if "is_trading" not in data.columns:
        data["is_trading"] = True
    data.sort_values(["date", "symbol"], inplace=True)
    data.reset_index(drop=True, inplace=True)
    return data


def governance_feature_columns():
    columns = [
        "date",
        "symbol",
        "instrument_type",
        "open",
        "close",
        "open_nominal",
        "close_nominal",
        "amount",
        "amount_ma20",
        "is_trading",
        "rough_limit_up",
        "rough_limit_down",
        "abnormal_jump",
        "ret_5",
        "ret_20",
        "score_mom_lowvol",
        "close_to_ma20",
        "volatility_20",
        "index_pool_codes",
        "in_target_index_pool",
        "score_orderflow_amount_shock",
        "score_orderflow_close_drive",
        "score_orderflow_accumulation",
        "score_orderflow_efficiency",
        "score_eod_close_strength",
    ]
    columns.extend(GOVERNANCE_ALPHA_MODEL_FEATURES.values())
    return list(dict.fromkeys(columns))
