"""Date-effective fee schedule used by research execution simulations."""
from __future__ import annotations

import pandas as pd


STAMP_DUTY_HALF_RATE_EFFECTIVE_DATE = pd.Timestamp("2023-08-28")


def stamp_duty_rate_for(trade_date, *, fallback_rate: float) -> float:
    if trade_date is None or pd.isna(trade_date):
        return float(fallback_rate)
    date = pd.Timestamp(trade_date).normalize()
    if date >= STAMP_DUTY_HALF_RATE_EFFECTIVE_DATE:
        return 0.0005
    return 0.001


def commission_cost(notional: float, *, rate: float, minimum: float = 0.0) -> float:
    amount = max(float(notional), 0.0)
    if amount <= 0.0:
        return 0.0
    return max(amount * max(float(rate), 0.0), max(float(minimum), 0.0))
