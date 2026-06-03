# -*- coding: utf-8 -*-
import pandas as pd

import numpy as np

from config import (
    COMMISSION_RATE,
    GOVERNANCE_IMPACT_MAX_RATE,
    GOVERNANCE_IMPACT_MODEL_VERSION,
    GOVERNANCE_IMPACT_SQRT_COEFFICIENT,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    TRANSFER_FEE_RATE,
)


def estimate_trade_costs(
    order_df,
    *,
    commission_rate=COMMISSION_RATE,
    stamp_duty_rate=STAMP_DUTY_RATE,
    slippage_rate=SLIPPAGE_RATE,
    transfer_fee_rate=TRANSFER_FEE_RATE,
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
    data["transfer_fee_cost"] = notional * float(transfer_fee_rate)
    market_amount = pd.to_numeric(
        data.get("market_amount", pd.Series(0.0, index=data.index)),
        errors="coerce",
    ).fillna(0.0)
    data["participation_rate"] = (notional / market_amount.where(market_amount > 0.0)).fillna(0.0)
    data["market_impact_rate"] = (
        float(GOVERNANCE_IMPACT_SQRT_COEFFICIENT)
        * np.sqrt(data["participation_rate"].clip(lower=0.0))
    ).clip(upper=float(GOVERNANCE_IMPACT_MAX_RATE))
    data["market_impact_cost"] = notional * data["market_impact_rate"]
    data["impact_model_version"] = GOVERNANCE_IMPACT_MODEL_VERSION
    data["arrival_price"] = pd.to_numeric(data.get("arrival_price", data["price"]), errors="coerce").fillna(data["price"])
    data["implementation_shortfall_proxy"] = data["slippage_cost"] + data["market_impact_cost"]
    data["opportunity_cost"] = pd.to_numeric(
        data.get("opportunity_cost", pd.Series(0.0, index=data.index)),
        errors="coerce",
    ).fillna(0.0)
    data["total_cost"] = (
        data["commission_cost"]
        + data["slippage_cost"]
        + data["stamp_duty_cost"]
        + data["transfer_fee_cost"]
        + data["market_impact_cost"]
    )
    return data
