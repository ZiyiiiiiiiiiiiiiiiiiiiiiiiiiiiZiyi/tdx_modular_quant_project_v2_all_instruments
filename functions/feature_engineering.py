"""
我已经根据你现有的 feature 生成代码，整理了一个 多策略选股框架，可以生成大约 10 个不同策略顾问，每个策略使用不同的因子组合，同时提供回测接口。注释里包含未来修改说明。

示例策略组合：

纯动量策略：使用 ret_20、ret_60
反转策略：使用 ret_5、ret_10 反向排序
波动率低买策略：volatility_20、volatility_60
成交量异常策略：volume_ma_20、amount_ratio_20
均线突破策略：close_to_ma20、close_to_ma60
K线形态策略：amplitude、intraday_ret、upper_shadow、lower_shadow
综合动量低波动策略：score_mom_lowvol
模拟事件因子策略：earnings_surprise、analyst_update
另类舆情策略：sentiment、supply_chain、social
ML 综合策略：score_ml

核心接口：

每个策略通过 select_instruments_by_score(df_features, score_col, top_n) 选择标的
回测接口 run_backtest(df_features, selected_symbols, initial_cash=1.0)

修改方式示例：

新增策略组合：添加新的因子组合，增加到策略列表
修改因子权重：在 feature_engineering.py 或对应因子文件调整计算逻辑
调整选股数量：修改 top_n 参数
调整调仓频率：增加 freq 参数处理逻辑
"""
# -*- coding: utf-8 -*-
import sys
import os

# 确保 functions 文件夹在 Python 搜索路径里
sys.path.append(os.path.dirname(__file__))  # 添加 functions/
sys.path.append(os.path.join(os.path.dirname(__file__), 'factors'))  # 添加 functions/factors/
import pandas as pd
import numpy as np
from config import FEATURE_DAILY_PARQUET, CLEAN_DAILY_PARQUET
from functions.factors.factor_ml import compute_factor as compute_ml_factor

GROUP_COL = 'symbol'

def generate_daily_features_multi():
    df = pd.read_parquet(CLEAN_DAILY_PARQUET)
    df = df.sort_values([GROUP_COL,'date'])
    g = df.groupby(GROUP_COL, group_keys=False)

    # 价量因子
    for n in [1,5,10,20,60]:
        df[f'ret_{n}'] = g['close'].pct_change(n)
    for n in [5,10,20,60,120]:
        df[f'ma_{n}'] = g['close'].transform(lambda x: x.rolling(n,min_periods=n).mean())
        df[f'volume_ma_{n}'] = g['volume'].transform(lambda x: x.rolling(n,min_periods=n).mean())
    df['close_to_ma20'] = df['close']/df['ma_20'] - 1
    df['close_to_ma60'] = df['close']/df['ma_60'] - 1

    # 波动率
    for n in [10,20,60]:
        df[f'volatility_{n}'] = g['ret_1'].transform(lambda x: x.rolling(n,min_periods=n).std())

    # K线形态
    df['amplitude'] = df['high']/df['low'] - 1
    df['intraday_ret'] = df['close']/df['open'] - 1
    max_open_close = df[['open','close']].max(axis=1)
    min_open_close = df[['open','close']].min(axis=1)
    df['upper_shadow'] = df['high']/max_open_close - 1
    df['lower_shadow'] = min_open_close/df['low'] - 1
    price_range = (df['high'] - df['low']).replace(0,np.nan)
    df['body_ratio'] = (df['close'] - df['open']).abs() / price_range

    # 成交额
    df['amount_ma20'] = g['amount'].transform(lambda x: x.rolling(20,min_periods=20).mean())
    df['amount_ratio_20'] = df['amount']/df['amount_ma20'] - 1

    # 简单综合分数
    df['score_mom_lowvol'] = df['ret_20'] - df['volatility_20']

    # TODO: 可以加入事件/另类/ML 因子

    df.to_parquet(FEATURE_DAILY_PARQUET, index=False)

    print('Feature shape:', df.shape)
    return df


def select_instruments_by_score(df, score_col, top_n=5):
    '''
    策略选股函数，按 score_col 排序
    返回每期前 top_n 标的
    '''
    df_sel = df.copy()
    df_sel = df_sel.sort_values(['date', score_col], ascending=[True, False])
    df_sel['rank'] = df_sel.groupby('date')[score_col].rank(method='first', ascending=False)
    df_sel = df_sel[df_sel['rank'] <= top_n]
    df_sel['rebalance_date'] = df_sel['date']#✅ 添加 rebalance_date 列
    # 新增列：rebalance_date & 初始等权 weight
    df_sel['rebalance_date'] = df_sel['date']
    df_sel['weight'] = 1.0 / top_n
    return df_sel




def generate_multi_strategies(df, top_n):
    """
    定义多个策略组合（示例10个策略）
    df: 包含所有价量因子和其他因子列
    top_n: 每个调仓日选择前 N 个标的
    """
    strategies = {}

    # 1. 动量策略
    strategies['momentum'] = select_instruments_by_score(df, 'ret_20', top_n=top_n)

    # 2. 短期反转策略
    strategies['reversal'] = select_instruments_by_score(df, 'ret_5', top_n=top_n)

    # 3. 波动率低买策略
    strategies['low_vol'] = select_instruments_by_score(df, 'volatility_20', top_n=top_n)

    # 4. 成交量异常策略
    strategies['volume_extreme'] = select_instruments_by_score(df, 'volume_ma_20', top_n=top_n)

    # 5. 均线突破策略
    strategies['ma_break'] = select_instruments_by_score(df, 'close_to_ma20', top_n=top_n)

    # 6. K线形态策略
    strategies['kline_shape'] = select_instruments_by_score(df, 'amplitude', top_n=top_n)

    # 7. 综合动量低波动策略
    strategies['mom_lowvol'] = select_instruments_by_score(df, 'score_mom_lowvol', top_n=top_n)

    # 8-10 ML策略，分别使用 ElasticNet、XGBoost、LightGBM
    df_ml_en = compute_ml_factor(df, model_type='elasticnet')
    df_ml_xgb = compute_ml_factor(df, model_type='xgboost')
    df_ml_lgb = compute_ml_factor(df, model_type='lightgbm')

    strategies['ml_elasticnet'] = select_instruments_by_score(df_ml_en, 'score_ml', top_n=top_n)
    strategies['ml_xgboost'] = select_instruments_by_score(df_ml_xgb, 'score_ml', top_n=top_n)
    strategies['ml_lightgbm'] = select_instruments_by_score(df_ml_lgb, 'score_ml', top_n=top_n)

    # 占位事件/另类因子（未来可替换真实因子）
    strategies['event_factor'] = select_instruments_by_score(df, 'ret_20', top_n=top_n)  # TODO
    strategies['alternative_factor'] = select_instruments_by_score(df, 'ret_20', top_n=top_n)  # TODO

    return strategies


def run_backtest(df_features, strategies, initial_cash=1.0):
    '''
    简化回测示例：每个策略等权持仓，按每日收益累加
    '''
    results = {}
    for name, df_sel in strategies.items():
        df_sel = df_sel.copy()
        df_sel = df_sel.sort_values(['symbol','date'])
        df_sel['daily_ret'] = df_sel.groupby('symbol')['ret_1'].shift(-1)  # 下一日收益
        df_sel = df_sel.dropna(subset=['daily_ret'])
        df_sel['weight'] = 1 / df_sel.groupby('date')['symbol'].transform('count')
        df_sel['portfolio_ret'] = df_sel['daily_ret'] * df_sel['weight']
        df_daily = df_sel.groupby('date')['portfolio_ret'].sum().reset_index()
        df_daily['nav'] = (1 + df_daily['portfolio_ret']).cumprod() * initial_cash
        results[name] = df_daily
    return results