"""Bounded V6 government, ML ratchet, liquidity, and capacity controls."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import (
    POSITION_LIQUIDITY_ADV_QUANTILE,
    POSITION_LIQUIDITY_ALERT_DAYS,
    POSITION_LIQUIDITY_AMIHUD_QUANTILE,
    V6_LIQUIDITY_PARTICIPATION_RATE,
    V6_ML_INITIAL_WEIGHT,
    V6_ML_MAX_WEIGHT,
    V6_ML_REQUIRED_CONSECUTIVE_WINDOWS,
    V6_ML_WEIGHT_STEP,
)


@dataclass(frozen=True)
class GovernmentDecision:
    market_discount: float
    portfolio_exposure_cap: float
    trading_freeze_flag: bool
    emergency_deleveraging_flag: bool
    model_mode: str


@dataclass(frozen=True)
class MLWeightState:
    weight: float = V6_ML_INITIAL_WEIGHT
    consecutive_passes: int = 0


def continuous_market_discount(
    *,
    volatility_percentile: float,
    market_breadth: float,
    index_trend: float,
    portfolio_drawdown: float,
    prior_discounts: pd.Series | None = None,
    coefficients: tuple[float, float, float, float, float] = (0.5, 1.2, 0.8, 0.8, 2.0),
) -> GovernmentDecision:
    """Return a smooth 0.5-1.0 discount without changing stock-level Kelly."""
    intercept, b_vol, b_breadth, b_trend, b_drawdown = coefficients
    linear = (
        intercept
        - b_vol * float(np.clip(volatility_percentile, 0.0, 1.0))
        + b_breadth * float(np.clip(market_breadth, -1.0, 1.0))
        + b_trend * float(np.clip(index_trend, -1.0, 1.0))
        - b_drawdown * abs(min(float(portfolio_drawdown), 0.0))
    )
    raw = float(np.clip(1.0 / (1.0 + np.exp(-linear)), 0.5, 1.0))
    history = (
        pd.to_numeric(prior_discounts, errors="coerce").dropna()
        if prior_discounts is not None
        else pd.Series(dtype=float)
    )
    smoothed = float(
        pd.concat([history.tail(4), pd.Series([raw])])
        .ewm(span=5, adjust=False)
        .mean()
        .iloc[-1]
    )
    drawdown = abs(min(float(portfolio_drawdown), 0.0))
    emergency = drawdown >= 0.12
    freeze = emergency or float(volatility_percentile) >= 0.98
    exposure_cap = min(smoothed, 0.50 if emergency else 1.0)
    return GovernmentDecision(
        smoothed,
        float(exposure_cap),
        freeze,
        emergency,
        "continuous_sigmoid_v1",
    )


def update_ml_weight(
    state: MLWeightState,
    *,
    brier_improved: bool,
    calibration_not_worse: bool,
    ranking_improved: bool,
    net_return_improved: bool,
    risk_not_worse: bool,
) -> MLWeightState:
    passed = all(
        [
            brier_improved,
            calibration_not_worse,
            ranking_improved,
            net_return_improved,
            risk_not_worse,
        ]
    )
    if not passed:
        return MLWeightState(weight=V6_ML_INITIAL_WEIGHT, consecutive_passes=0)
    passes = int(state.consecutive_passes) + 1
    weight = float(state.weight)
    if passes >= V6_ML_REQUIRED_CONSECUTIVE_WINDOWS:
        weight = min(weight + V6_ML_WEIGHT_STEP, V6_ML_MAX_WEIGHT)
        passes = 0
    return MLWeightState(weight=weight, consecutive_passes=passes)


def calculate_capacity(
    orders: pd.DataFrame,
    *,
    participation_rate: float = V6_LIQUIDITY_PARTICIPATION_RATE,
) -> pd.DataFrame:
    required = {"symbol", "order_value", "adv20"}
    missing = sorted(required - set(orders.columns))
    if missing:
        raise ValueError(f"orders missing capacity columns: {missing}")
    data = orders.copy()
    data["order_value"] = (
        pd.to_numeric(data["order_value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    data["adv20"] = (
        pd.to_numeric(data["adv20"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    data["daily_capacity"] = data["adv20"] * float(participation_rate)
    data["days_to_trade"] = np.where(
        data["daily_capacity"] > 0.0,
        data["order_value"] / data["daily_capacity"],
        np.inf,
    )
    data["capacity_passed"] = np.isfinite(data["days_to_trade"]) & (
        data["days_to_trade"] <= 1.0
    )
    return data


def detect_liquidity_deterioration(history: pd.DataFrame) -> pd.DataFrame:
    """Use each stock's trailing distribution, not a market-relative threshold."""
    required = {"symbol", "date", "adv20", "amihud"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError(f"history missing liquidity columns: {missing}")
    data = history.copy().sort_values(["symbol", "date"])
    grouped = data.groupby("symbol", group_keys=False)
    data["adv_floor"] = grouped["adv20"].transform(
        lambda s: s.shift(1)
        .rolling(252, min_periods=60)
        .quantile(POSITION_LIQUIDITY_ADV_QUANTILE)
    )
    data["amihud_ceiling"] = grouped["amihud"].transform(
        lambda s: s.shift(1)
        .rolling(252, min_periods=60)
        .quantile(POSITION_LIQUIDITY_AMIHUD_QUANTILE)
    )
    data["liquidity_bad"] = (data["adv20"] < data["adv_floor"]) | (
        data["amihud"] > data["amihud_ceiling"]
    )
    data["liquidity_bad_streak"] = grouped["liquidity_bad"].transform(
        _consecutive_true
    )
    data["liquidity_alert"] = (
        data["liquidity_bad_streak"] >= POSITION_LIQUIDITY_ALERT_DAYS
    )
    return data


def _consecutive_true(values: pd.Series) -> pd.Series:
    result = []
    streak = 0
    for value in values.fillna(False).astype(bool):
        streak = streak + 1 if value else 0
        result.append(streak)
    return pd.Series(result, index=values.index)
