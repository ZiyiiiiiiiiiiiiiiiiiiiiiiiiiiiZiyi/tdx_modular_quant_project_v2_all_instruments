# -*- coding: utf-8 -*-
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import FEATURE_DAILY_PARQUET, RESULT_DIR
from functions.metrics import calc_backtest_metrics


def prepare_daily_returns(feature_data):
    """Calculate close-to-close daily returns for each instrument."""
    df = feature_data.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])
    df["daily_symbol_return"] = df.groupby("symbol")["close"].pct_change()
    return df[["date", "symbol", "daily_symbol_return", "close"]].copy()


def run_backtest(
    df_selection,
    initial_cash=1.0,
    risk_free_rate=0.0,
    max_weight=0.2,
    show_plot=True,
    strategy_name="strategy",
    factor_description=None,
):
    """
    Backtest one strategy by expanding rebalance selections into daily holdings.

    A position selected on rebalance date R is held from the next trading day
    through the next rebalance date. Daily returns come from the full feature
    table, not from shifted rows inside the sparse selection table.
    """
    feature_data = pd.read_parquet(FEATURE_DAILY_PARQUET)
    returns = prepare_daily_returns(feature_data)

    df_sel = df_selection.copy()
    required_cols = ["symbol", "rebalance_date"]
    missing_cols = [col for col in required_cols if col not in df_sel.columns]
    if missing_cols:
        raise ValueError(f"df_selection missing required columns: {missing_cols}")
    if df_sel.empty:
        raise ValueError(f"Strategy {strategy_name} selection is empty")

    df_sel["rebalance_date"] = pd.to_datetime(df_sel["rebalance_date"])
    returns["date"] = pd.to_datetime(returns["date"])
    df_sel = df_sel.sort_values(["rebalance_date", "symbol"]).copy()

    if "weight" not in df_sel.columns:
        df_sel["weight"] = 1.0 / df_sel.groupby("rebalance_date")["symbol"].transform("count")

    default_weight = 1.0 / df_sel.groupby("rebalance_date")["symbol"].transform("count")
    df_sel["weight"] = pd.to_numeric(df_sel["weight"], errors="coerce").fillna(default_weight)
    df_sel["weight"] = df_sel["weight"].clip(upper=max_weight)
    df_sel["weight"] = df_sel["weight"] / df_sel.groupby("rebalance_date")["weight"].transform("sum")

    rebalance_dates = pd.Series(df_sel["rebalance_date"].drop_duplicates().sort_values()).reset_index(drop=True)
    all_trade_dates = pd.Series(returns["date"].drop_duplicates().sort_values()).reset_index(drop=True)

    period_frames = []
    for idx, rebalance_date in rebalance_dates.items():
        next_rebalance = (
            rebalance_dates.iloc[idx + 1]
            if idx + 1 < len(rebalance_dates)
            else all_trade_dates.max()
        )
        period_dates = all_trade_dates[
            (all_trade_dates > rebalance_date) & (all_trade_dates <= next_rebalance)
        ]
        if period_dates.empty:
            continue

        one_holdings = df_sel[df_sel["rebalance_date"] == rebalance_date][
            ["rebalance_date", "symbol", "weight"]
        ].copy()
        one_returns = returns[returns["date"].isin(period_dates)][
            ["date", "symbol", "daily_symbol_return"]
        ]
        expanded = one_returns.merge(one_holdings, on="symbol", how="inner")
        expanded = expanded.dropna(subset=["daily_symbol_return", "weight"])
        if expanded.empty:
            continue

        expanded["portfolio_ret_part"] = expanded["daily_symbol_return"] * expanded["weight"]
        period_frames.append(expanded)

    if not period_frames:
        raise ValueError(f"Strategy {strategy_name} has no matched daily returns after expansion")

    expanded_returns = pd.concat(period_frames, ignore_index=True)
    daily_result = (
        expanded_returns.groupby("date")
        .agg(
            portfolio_ret=("portfolio_ret_part", "sum"),
            holding_count=("symbol", "nunique"),
        )
        .reset_index()
        .sort_values("date")
    )
    daily_result["daily_return"] = daily_result["portfolio_ret"]

    initial_date = rebalance_dates.min()
    initial_holding_count = df_sel[df_sel["rebalance_date"] == initial_date]["symbol"].nunique()
    if daily_result.empty or initial_date < daily_result["date"].min():
        initial_row = pd.DataFrame(
            {
                "date": [initial_date],
                "portfolio_ret": [0.0],
                "holding_count": [initial_holding_count],
                "daily_return": [0.0],
            }
        )
        daily_result = pd.concat([initial_row, daily_result], ignore_index=True)
        daily_result = daily_result.sort_values("date").reset_index(drop=True)

    daily_result["nav"] = (1 + daily_result["daily_return"]).cumprod() * initial_cash
    daily_result["net_value"] = daily_result["nav"]

    metrics, drawdown = calc_backtest_metrics(
        daily_result=daily_result,
        risk_free_rate=risk_free_rate,
    )
    daily_result["drawdown"] = drawdown.values
    holdings_record = daily_result[["date", "holding_count"]].copy()

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

    _plot_equity_curve(
        daily_result,
        drawdown,
        metrics=metrics,
        strategy_name=strategy_name,
        factor_description=factor_description,
        show_plot=show_plot,
        output_file=plot_file,
        holdings_record=holdings_record,
    )

    print("\n========== Backtest Result ==========")
    print(metrics)
    print("Saved daily CSV:", daily_csv)
    print("Saved daily Parquet:", daily_parquet)
    print("Saved metrics:", metrics_csv)
    print("Saved holdings:", holdings_csv)
    print("Saved equity curve:", plot_file)

    return daily_result, metrics, holdings_record


def _plot_equity_curve(
    daily_result,
    drawdown,
    metrics=None,
    strategy_name="strategy",
    factor_description=None,
    show_plot=True,
    output_file=None,
    holdings_record=None,
):
    """Plot net value, drawdown, and holding count with Chinese labels."""
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax1 = plt.subplots(figsize=(12, 6))

    net_value_line = ax1.plot(
        daily_result["date"],
        daily_result.get("nav", pd.Series(np.zeros(len(daily_result)))),
        color="blue",
        label="净值曲线：组合累计收益表现",
    )
    ax1.set_xlabel("日期")
    ax1.set_ylabel("组合净值 / 持仓数量")
    ax1.grid(True)

    ax2 = ax1.twinx()
    drawdown_area = ax2.fill_between(
        daily_result["date"],
        drawdown,
        0,
        color="red",
        alpha=0.3,
        label="回撤区域：相对历史最高净值的跌幅",
    )
    ax2.set_ylabel("回撤")
    ax2.set_ylim(min(drawdown.min(), -0.1), 0.05)

    holding_line = []
    if holdings_record is not None:
        holding_line = ax1.plot(
            holdings_record["date"],
            holdings_record.get("holding_count", pd.Series(np.zeros(len(holdings_record)))),
            color="green",
            linestyle="--",
            label="持仓数量：当日实际持有标的数",
        )

    factor_text = factor_description or "未配置因子组合说明"
    ax1.set_title(f"策略回测：{strategy_name}\n因子组合：{factor_text}")

    if metrics is not None:
        total_return = _metric_value(metrics, "total_return")
        annual_return = _metric_value(metrics, "annual_return")
        sharpe = _metric_value(metrics, "sharpe")
        max_drawdown = _metric_value(metrics, "max_drawdown")
        text_str = (
            f"策略名称：{strategy_name}\n"
            f"因子组合：{factor_text}\n"
            f"累计收益：{total_return:.2%}\n"
            f"年化收益：{annual_return:.2%}\n"
            f"夏普比率：{sharpe:.4f}\n"
            f"最大回撤：{max_drawdown:.2%}"
        )
        ax1.text(
            0.02,
            0.95,
            text_str,
            transform=ax1.transAxes,
            verticalalignment="top",
            bbox=dict(boxstyle="round", alpha=0.2),
        )

    handles = net_value_line + holding_line + [drawdown_area]
    labels = [handle.get_label() for handle in handles]
    ax1.legend(handles, labels, loc="lower left")

    fig.tight_layout()
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close(fig)


def _metric_value(metrics, metric_name):
    if metric_name not in metrics["metric"].values:
        return np.nan
    return metrics.loc[metrics["metric"] == metric_name, "value"].iloc[0]


if __name__ == "__main__":
    raise SystemExit("Call run_backtest(df_selection=...) from main.py")
