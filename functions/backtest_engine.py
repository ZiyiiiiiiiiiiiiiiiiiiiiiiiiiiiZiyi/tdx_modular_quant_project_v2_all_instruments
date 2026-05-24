# -*- coding: utf-8 -*-
"""
回测模块：backtest_engine.py

作用：
    读取策略选股结果和行情因子数据，
    计算组合每日收益、净值曲线、回测指标，
    并保存数据表和图片。

输入：
    data/processed/tdx_daily_features.parquet
    data/processed/strategy_selection.parquet

输出：
    results/backtest_daily_result.csv
    results/backtest_daily_result.parquet
    results/backtest_metrics.csv
    results/backtest_holdings.csv
    results/equity_curve.png
    - 单标的最大权重约束 max_weight
    - Spyder 右侧直接显示图 show_plot
    - 图上显示净值 + 最大回撤 + 持仓数量 + 夏普比率
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from config import (
    FEATURE_DAILY_PARQUET,
    PROCESSED_DIR,
    RESULT_DIR,
)
from functions.metrics import calc_backtest_metrics


def prepare_daily_returns(feature_data):
    """
    从行情数据中计算每个标的的每日收益率。
    """
    df = feature_data.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])
    df["daily_symbol_return"] = df.groupby("symbol")["close"].pct_change()
    returns = df[["date", "symbol", "daily_symbol_return", "close"]].copy()
    return returns

def run_backtest(df_selection, initial_cash=1.0, risk_free_rate=0.0,
                 max_weight=0.2, show_plot=True, strategy_name="strategy"):
    """
    回测单策略（安全版）。
    df_selection: 每期选股表，必须包含 'symbol','rebalance_date','ret_1' 等列
    """
    # 读取因子数据计算每日收益
    feature_data = pd.read_parquet(FEATURE_DAILY_PARQUET)

    # 确保 df_selection 有必需列
    df_sel = df_selection.copy()
    for col in ["symbol", "rebalance_date", "ret_1"]:
        if col not in df_sel.columns:
            raise ValueError(f"df_selection 缺少列: {col}")

    # 按日期排序
    df_sel = df_sel.sort_values(['rebalance_date', 'symbol'])

    # 计算等权组合收益
    df_sel['weight'] = 1.0 / df_sel.groupby('rebalance_date')['symbol'].transform('count')
    df_sel['weight'] = df_sel['weight'].clip(upper=max_weight)
    df_sel['weight'] = df_sel['weight'] / df_sel.groupby('rebalance_date')['weight'].transform('sum')
    df_sel['daily_ret'] = df_sel.groupby('symbol')['ret_1'].shift(-1)
    df_sel['daily_ret'] = df_sel['daily_ret'].fillna(0)
    df_sel['portfolio_ret'] = df_sel['daily_ret'] * df_sel['weight']

    # 日净值
    daily_result = df_sel.groupby('rebalance_date')['portfolio_ret'].sum().reset_index()
    daily_result = daily_result.rename(columns={'rebalance_date': 'date'})
    daily_result['nav'] = (1 + daily_result['portfolio_ret']).cumprod() * initial_cash
    daily_result['net_value'] = daily_result['nav']
    daily_result['daily_return'] = daily_result['portfolio_ret']
    metrics, drawdown = calc_backtest_metrics(daily_result=daily_result, risk_free_rate=risk_free_rate)
    daily_result['drawdown'] = drawdown.values

    # 持仓数量
    holdings_record = df_sel.groupby('rebalance_date')['symbol'].count().reset_index()
    holdings_record = holdings_record.rename(columns={'rebalance_date': 'date', 'symbol': 'holding_count'})

    # 计算回测指标
    daily_result['daily_return'] = daily_result['portfolio_ret']
    metrics, drawdown = calc_backtest_metrics(daily_result=daily_result, risk_free_rate=risk_free_rate)
    daily_result['drawdown'] = drawdown.values

    # 保存
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    daily_csv = RESULT_DIR / f"backtest_daily_result_{strategy_name}.csv"
    daily_parquet = RESULT_DIR / f"backtest_daily_result_{strategy_name}.parquet"
    metrics_csv = RESULT_DIR / f"backtest_metrics_{strategy_name}.csv"
    holdings_csv = RESULT_DIR / f"backtest_holdings_{strategy_name}.csv"
    plot_file = RESULT_DIR / f"equity_curve_{strategy_name}.png"

    daily_result.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    daily_result.to_parquet(daily_parquet, index=False)
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    holdings_record.to_csv(holdings_csv, index=False, encoding="utf-8-sig")

    # 绘制净值曲线+回撤+持仓数量+夏普比率
    _plot_equity_curve(daily_result, drawdown, metrics=metrics,
                       strategy_name=strategy_name,
                       show_plot=show_plot,
                       output_file=plot_file,
                       holdings_record=holdings_record)

    print("\n========== 回测结果 ==========")
    print(metrics)
    print("\n已保存每日回测结果 CSV：", daily_csv)
    print("已保存每日回测结果 Parquet：", daily_parquet)
    print("已保存回测指标：", metrics_csv)
    print("已保存持仓记录：", holdings_csv)
    print("已保存净值曲线图片：", plot_file)

    return daily_result, metrics, holdings_record


def _plot_equity_curve(daily_result, drawdown, metrics=None, strategy_name="strategy",
                       show_plot=True, output_file=None, holdings_record=None):
    """
    绘制净值曲线 + 回撤 + 持仓数量 + 夏普比率（安全版）
    """
    fig, ax1 = plt.subplots(figsize=(12, 6))

    # 净值曲线
    ax1.plot(daily_result['date'], daily_result.get('nav', pd.Series(np.zeros(len(daily_result)))), 
             color='blue', label='Net Value')
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Net Value")
    ax1.grid(True)

    # 回撤
    ax2 = ax1.twinx()
    ax2.fill_between(daily_result['date'], drawdown, 0, color='red', alpha=0.3, label='Drawdown')
    ax2.set_ylabel("Drawdown")
    ax2.set_ylim(min(drawdown.min(), -0.1), 0.05)

    # 持仓数量
    if holdings_record is not None:
        ax1.plot(holdings_record['date'], holdings_record.get('holding_count', pd.Series(np.zeros(len(holdings_record)))), 
                 color='green', linestyle='--', label='Holding Count')

    # 指标文本
    if metrics is not None:
        total_return = metrics['value'][metrics['metric']=='total_return'].iloc[0] if 'total_return' in metrics['metric'].values else np.nan
        annual_return = metrics['value'][metrics['metric']=='annual_return'].iloc[0] if 'annual_return' in metrics['metric'].values else np.nan
        sharpe = metrics['value'][metrics['metric']=='sharpe'].iloc[0] if 'sharpe' in metrics['metric'].values else np.nan
        max_drawdown = metrics['value'][metrics['metric']=='max_drawdown'].iloc[0] if 'max_drawdown' in metrics['metric'].values else np.nan

        text_str = (
            f"Strategy: {strategy_name}\n"
            f"Total Return: {total_return:.2%}\n"
            f"Annual Return: {annual_return:.2%}\n"
            f"Sharpe: {sharpe:.4f}\n"
            f"Max Drawdown: {max_drawdown:.2%}"
        )
        ax1.text(0.02, 0.95, text_str, transform=ax1.transAxes,
                 verticalalignment='top', bbox=dict(boxstyle='round', alpha=0.2))

    fig.tight_layout()
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    run_backtest(initial_cash=1.0, risk_free_rate=0.0, max_weight=0.2, show_plot=True)