# -*- coding: utf-8 -*-
import pandas as pd

from config import COMMISSION_RATE, SLIPPAGE_RATE, STAMP_DUTY_RATE


def estimate_trade_costs(
    order_df,
    *,
    commission_rate=COMMISSION_RATE,
    stamp_duty_rate=STAMP_DUTY_RATE,
    slippage_rate=SLIPPAGE_RATE,
    shares_col=None,
):
    data = order_df.copy()
    data["price"] = pd.to_numeric(data["price"], errors="coerce").fillna(0.0)
    data["target_shares"] = pd.to_numeric(data["target_shares"], errors="coerce").fillna(0.0)
    data["side"] = data["side"].astype(str).str.lower()

    share_source = shares_col or "target_shares"
    if share_source not in data.columns:
        raise ValueError(f"Cost share column is missing: {share_source}")
    charged_shares = pd.to_numeric(data[share_source], errors="coerce").fillna(0.0)
    notional = (data["price"] * charged_shares.abs()).fillna(0.0)
    data["trade_notional"] = notional
    data["commission_cost"] = notional * float(commission_rate)
    data["slippage_cost"] = notional * float(slippage_rate)
    data["stamp_duty_cost"] = notional.where(data["side"] == "sell", 0.0) * float(stamp_duty_rate)
    data["total_cost"] = (
        data["commission_cost"]
        + data["slippage_cost"]
        + data["stamp_duty_cost"]
    )
    return data
