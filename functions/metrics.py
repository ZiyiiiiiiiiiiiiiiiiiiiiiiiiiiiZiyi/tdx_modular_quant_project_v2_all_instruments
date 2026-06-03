# -*- coding: utf-8 -*-
"""
回测指标计算模块。

作用：
    根据每日组合收益率，计算：
        1. 累计收益
        2. 年化收益
        3. 年化波动率
        4. 夏普比率
        5. 最大回撤
"""

import numpy as np
import pandas as pd


def calc_max_drawdown(net_value):
    """
    计算最大回撤。
    """
    running_max = net_value.cummax()
    drawdown = net_value / running_max - 1
    max_drawdown = drawdown.min()

    return max_drawdown, drawdown


def calc_backtest_metrics(daily_result, risk_free_rate=0.0):
    """
    计算回测指标。
    """
    data = daily_result.copy()
    data = data.dropna(subset=["daily_return", "net_value"])
    data = data.sort_values("date")

    if data.empty:
        metrics = pd.DataFrame({
            "metric": ["error"],
            "value": ["daily_result is empty"]
        })
        return metrics, pd.Series(dtype=float)

    start_date = data["date"].min()
    end_date = data["date"].max()
    trading_days = len(data)

    initial_value = (
        float(data["initial_cash"].iloc[0])
        if "initial_cash" in data.columns and pd.notna(data["initial_cash"].iloc[0])
        else data["net_value"].iloc[0]
    )
    total_return = data["net_value"].iloc[-1] / initial_value - 1

    if trading_days > 1:
        annual_return = (1 + total_return) ** (252 / trading_days) - 1
    else:
        annual_return = np.nan

    annual_volatility = data["daily_return"].std() * np.sqrt(252)

    if annual_volatility and annual_volatility != 0:
        sharpe = (annual_return - risk_free_rate) / annual_volatility
    else:
        sharpe = np.nan

    max_drawdown, drawdown = calc_max_drawdown(data["net_value"])

    win_rate = (data["daily_return"] > 0).mean()
    downside = data.loc[data["daily_return"] < 0, "daily_return"]
    downside_volatility = downside.std() * np.sqrt(252) if len(downside) else np.nan
    sortino = (annual_return - risk_free_rate) / downside_volatility if downside_volatility and downside_volatility != 0 else np.nan
    calmar = annual_return / abs(max_drawdown) if max_drawdown and max_drawdown != 0 else np.nan
    drawdown_duration = _max_drawdown_duration(drawdown)
    monthly = data.set_index("date")["daily_return"].resample("ME").apply(lambda s: (1.0 + s).prod() - 1.0)
    monthly_win_rate = (monthly > 0).mean() if len(monthly) else np.nan
    max_consecutive_loss_days = _max_consecutive_losses(data["daily_return"])

    metrics = pd.DataFrame({
        "metric": [
            "start_date",
            "end_date",
            "trading_days",
            "final_net_value",
            "total_return",
            "annual_return",
            "annual_volatility",
            "sharpe",
            "max_drawdown",
            "win_rate",
            "sortino",
            "calmar",
            "max_drawdown_duration_days",
            "monthly_win_rate",
            "max_consecutive_loss_days",
        ],
        "value": [
            start_date,
            end_date,
            trading_days,
            data["net_value"].iloc[-1],
            total_return,
            annual_return,
            annual_volatility,
            sharpe,
            max_drawdown,
            win_rate,
            sortino,
            calmar,
            drawdown_duration,
            monthly_win_rate,
            max_consecutive_loss_days,
        ]
    })

    return metrics, drawdown


def _max_drawdown_duration(drawdown):
    duration = 0
    max_duration = 0
    for value in drawdown.fillna(0.0):
        if value < 0:
            duration += 1
            max_duration = max(max_duration, duration)
        else:
            duration = 0
    return max_duration


def _max_consecutive_losses(returns):
    streak = 0
    max_streak = 0
    for value in pd.to_numeric(returns, errors="coerce").fillna(0.0):
        if value < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak
