# -*- coding: utf-8 -*-
import pandas as pd
from pathlib import Path

from functions.backtest_engine import run_backtest
from functions.feature_engineering import FEATURE_DAILY_PARQUET

# 回测参数
BACKTEST_INITIAL_CASH = 1.0
BACKTEST_RISK_FREE_RATE = 0.0
BACKTEST_SHOW_PLOT = True

# -------------------------
# 测试回测函数
# -------------------------
def test_backtest(top_n=5):
    # 读取策略选股结果
    selection_file = Path("data/processed/strategy_selection.parquet")
    if not selection_file.exists():
        raise FileNotFoundError(f"策略选股文件不存在: {selection_file}")

    df_selection = pd.read_parquet(selection_file)

    # 取最近一个策略和日期作为测试
    latest_date = df_selection['rebalance_date'].max()
    df_test = df_selection[df_selection['rebalance_date'] == latest_date].copy()
    df_test = df_test.head(top_n)  # 前 top_n 个股票

    # -------------------------
    # 生成每日收益 ret_1
    # -------------------------
    feature_data = pd.read_parquet(FEATURE_DAILY_PARQUET)
    feature_data = feature_data.sort_values(['symbol','date'])
    feature_data['ret_1'] = feature_data.groupby('symbol')['close'].pct_change(1)

    # 合并每日收益
    df_test = df_test.merge(
        feature_data[['symbol','date','ret_1']],
        left_on=['symbol','rebalance_date'],
        right_on=['symbol','date'],
        how='left'
    )
    df_test = df_test.drop(columns=['date'])  # 删除重复列

    # 检查必要列
    required_cols = ['symbol','rebalance_date','ret_1']
    for col in required_cols:
        if col not in df_test.columns:
            raise ValueError(f"测试回测缺少必要列: {col}")

    # -------------------------
    # 执行回测
    # -------------------------
    daily_result, metrics, holdings = run_backtest(
        df_selection=df_test,
        initial_cash=BACKTEST_INITIAL_CASH,
        risk_free_rate=BACKTEST_RISK_FREE_RATE,
        max_weight=0.2,
        show_plot=BACKTEST_SHOW_PLOT,
        strategy_name="test_momentum"
    )

    print("\n===== 测试回测每日结果 =====")
    print(daily_result.head())
    print("\n===== 测试回测指标 =====")
    print(metrics.head())
    print("\n===== 测试持仓记录 =====")
    print(holdings.head())

# -------------------------
# 执行测试
# -------------------------
if __name__ == "__main__":
    test_backtest()