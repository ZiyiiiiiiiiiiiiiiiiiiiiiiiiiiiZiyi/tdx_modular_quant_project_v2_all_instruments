"""Double-NAV accounting and five-day governance reward."""
from __future__ import annotations

import pandas as pd

from config import (
    GOVERNANCE_LOCK_HAIRCUT_DAYS,
    GOVERNANCE_LOCK_HAIRCUT_RATIO,
    GOVERNANCE_REWARD_DRAWDOWN_BUDGET,
    GOVERNANCE_REWARD_DRAWDOWN_PENALTY,
    GOVERNANCE_REWARD_TURNOVER_PENALTY,
)


def build_exposure_snapshot(
    positions: pd.DataFrame,
    *,
    cash: float,
    target_exposure: float,
    unresolved_safety_exposure: float = 0.0,
    constraint_cash_reserve: float = 0.0,
    haircut_days: int = GOVERNANCE_LOCK_HAIRCUT_DAYS,
    haircut_ratio: float = GOVERNANCE_LOCK_HAIRCUT_RATIO,
) -> dict:
    data = positions.copy()
    for col in ("shares", "price", "lock_days", "stale_haircut_ratio"):
        data[col] = pd.to_numeric(
            data.get(col, pd.Series(0.0, index=data.index)),
            errors="coerce",
        ).fillna(0.0)
    data["nominal_value"] = data["shares"] * data["price"]
    locked = data["lock_days"] > int(haircut_days)
    data["lock_haircut"] = data["nominal_value"].where(locked, 0.0) * float(haircut_ratio)
    data["stale_price_haircut"] = data["nominal_value"] * data["stale_haircut_ratio"].clip(0.0, 1.0)
    data["effective_haircut"] = data[["lock_haircut", "stale_price_haircut"]].max(axis=1)
    nominal_nav = float(cash) + float(data["nominal_value"].sum())
    lock_haircut = float(data["lock_haircut"].sum())
    stale_price_haircut = float(data["stale_price_haircut"].sum())
    effective_haircut = float(data["effective_haircut"].sum())
    liquidatable_nav = max(nominal_nav - effective_haircut, 0.0)
    nominal_position_value = float(data["nominal_value"].sum())
    liquidatable_position_value = max(nominal_position_value - effective_haircut, 0.0)
    return {
        "target_exposure": float(target_exposure),
        "nominal_exposure": nominal_position_value / nominal_nav if nominal_nav > 0 else 0.0,
        "liquidatable_exposure": liquidatable_position_value / liquidatable_nav if liquidatable_nav > 0 else 0.0,
        "unresolved_safety_exposure": float(unresolved_safety_exposure),
        "nominal_nav": nominal_nav,
        "liquidatable_nav": liquidatable_nav,
        "lock_haircut": lock_haircut,
        "stale_price_haircut": stale_price_haircut,
        "effective_liquidatable_haircut": effective_haircut,
        "pending_locked_weight": lock_haircut / nominal_nav if nominal_nav > 0 else 0.0,
        "cash_weight": float(cash) / nominal_nav if nominal_nav > 0 else 0.0,
        "constraint_cash_reserve": float(constraint_cash_reserve),
    }


def calculate_five_day_reward(
    liquidatable_nav: pd.Series,
    *,
    executed_turnover_5d: float,
    drawdown_budget: float = GOVERNANCE_REWARD_DRAWDOWN_BUDGET,
) -> dict:
    nav = pd.to_numeric(liquidatable_nav, errors="coerce").dropna()
    if len(nav) < 2 or float(nav.iloc[0]) <= 0:
        raise ValueError("At least two positive liquidatable NAV observations are required")
    nav_return = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    running_peak = nav.cummax()
    realized_drawdown = float(((running_peak - nav) / running_peak).max())
    reward = (
        nav_return
        - GOVERNANCE_REWARD_TURNOVER_PENALTY * float(executed_turnover_5d)
        - GOVERNANCE_REWARD_DRAWDOWN_PENALTY * max(0.0, realized_drawdown - float(drawdown_budget))
    )
    return {
        "liquidatable_nav_return_5d": nav_return,
        "executed_turnover_5d": float(executed_turnover_5d),
        "realized_max_drawdown_5d": realized_drawdown,
        "reward": reward,
    }
