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
        ]
    })

    return metrics, drawdown
