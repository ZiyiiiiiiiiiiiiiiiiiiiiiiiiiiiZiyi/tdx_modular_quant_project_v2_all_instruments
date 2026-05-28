# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from config import (
    FEATURE_DAILY_PARQUET,
    LIQUIDITY_LOCK_REPORT_CSV,
    MIN_LOT_SIZE,
    ORDER_LEDGER_PREFIX,
    RESULT_DIR,
)
from functions.execution.liquidity_lock_handler import (
    build_liquidity_lock_report,
    save_liquidity_lock_report,
)
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import build_delayed_order_queue, simulate_order_book
from functions.metrics import calc_backtest_metrics

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

LEARNING_METADATA_COLUMNS = [
    "learning_module",
    "reward_method",
    "profile_tier",
    "training_window_days",
    "feature_budget",
    "qubit_count",
    "fitted_feature_count",
    "feature_list",
]

_FEATURE_DATA_CACHE = None


def prepare_daily_returns(feature_data):
    """Calculate nominal close-to-close returns used by the execution ledger."""
    df = feature_data.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])
    trade_price_col = "close_nominal" if "close_nominal" in df.columns else "close"
    df["trade_close"] = pd.to_numeric(df[trade_price_col], errors="coerce")
    df["daily_symbol_return"] = df.groupby("symbol")["trade_close"].pct_change()
    return df[["date", "symbol", "daily_symbol_return", "trade_close"]].copy()


def run_backtest(
    df_selection,
    initial_cash=1.0,
    risk_free_rate=0.0,
    max_weight=0.2,
    show_plot=True,
    strategy_name="strategy",
    factor_description=None,
    compute_theoretical_upper_bound=True,
):
    """
    Backtest one strategy by expanding rebalance selections into daily holdings.

    A position selected on rebalance date R is held from the next trading day
    through the next rebalance date. Daily returns come from the full feature
    table, not from shifted rows inside the sparse selection table.
    """
    feature_data = _load_feature_data()
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
    feature_data["date"] = pd.to_datetime(feature_data["date"])
    df_sel = df_sel.sort_values(["rebalance_date", "symbol"]).copy()

    df_sel = _apply_weight_constraints(df_sel, max_weight=max_weight)

    rebalance_dates = pd.Series(df_sel["rebalance_date"].drop_duplicates().sort_values()).reset_index(drop=True)
    all_trade_dates = pd.Series(returns["date"].drop_duplicates().sort_values()).reset_index(drop=True)

    period_frames = []
    oracle_period_frames = []
    actual_weights = {}
    delayed_orders = []
    rebalance_cost_records = []
    order_ledger_parts = []
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
        rebalance_orders = _build_rebalance_orders(
            one_holdings=one_holdings,
            previous_weights=actual_weights,
            feature_data=feature_data,
            trade_date=rebalance_date,
            initial_cash=initial_cash,
        )
        simulated_orders = simulate_order_book(rebalance_orders)
        simulated_orders = _enforce_cash_weight_budget(actual_weights, simulated_orders)
        simulated_orders["rebalance_date"] = rebalance_date
        order_ledger_parts.append(simulated_orders)
        delayed_orders.append(build_delayed_order_queue(simulated_orders))
        rebalance_cost_records.append(
            {
                "rebalance_date": rebalance_date,
                "gross_turnover": float(simulated_orders["trade_notional"].sum()),
                "transaction_cost": float(simulated_orders["total_cost"].sum()),
                "blocked_order_count": int(
                    (simulated_orders["execution_status"] != "filled").sum()
                ),
            }
        )
        actual_weights = _apply_filled_orders_to_weights(actual_weights, simulated_orders)
        executed_holdings = pd.DataFrame(
            {"symbol": list(actual_weights.keys()), "weight": list(actual_weights.values())}
        )
        executed_holdings = executed_holdings[executed_holdings["weight"] > 1e-12]
        one_holding_count = executed_holdings["symbol"].nunique()
        if executed_holdings.empty:
            empty_period = pd.DataFrame(
                {
                    "date": period_dates,
                    "symbol": pd.NA,
                    "weight": 0.0,
                    "daily_symbol_return": 0.0,
                    "holding_count": 0,
                    "portfolio_ret_part": 0.0,
                }
            )
            period_frames.append(empty_period)
            continue
        one_returns = returns[returns["date"].isin(period_dates)][
            ["date", "symbol", "daily_symbol_return"]
        ]
        period_calendar = pd.MultiIndex.from_product(
            [period_dates.tolist(), executed_holdings["symbol"].tolist()],
            names=["date", "symbol"],
        ).to_frame(index=False)
        expanded = period_calendar.merge(
            executed_holdings[["symbol", "weight"]],
            on="symbol",
            how="left",
        )
        expanded = expanded.merge(
            one_returns,
            on=["date", "symbol"],
            how="left",
        )
        expanded["daily_symbol_return"] = pd.to_numeric(
            expanded["daily_symbol_return"],
            errors="coerce",
        ).fillna(0.0)
        expanded["weight"] = pd.to_numeric(expanded["weight"], errors="coerce").fillna(0.0)
        expanded["holding_count"] = one_holding_count
        expanded["portfolio_ret_part"] = expanded["daily_symbol_return"] * expanded["weight"]
        period_frames.append(expanded)

        if compute_theoretical_upper_bound:
            oracle_holdings = _build_oracle_holdings(
                feature_data=feature_data,
                returns=returns,
                rebalance_date=rebalance_date,
                period_dates=period_dates,
                holding_count=one_holding_count,
                allowed_instrument_types=df_sel.get("instrument_type"),
            )
        else:
            oracle_holdings = pd.DataFrame(columns=["symbol", "weight"])
        if compute_theoretical_upper_bound and not oracle_holdings.empty:
            oracle_calendar = pd.MultiIndex.from_product(
                [period_dates.tolist(), oracle_holdings["symbol"].tolist()],
                names=["date", "symbol"],
            ).to_frame(index=False)
            oracle_expanded = oracle_calendar.merge(
                oracle_holdings[["symbol", "weight"]],
                on="symbol",
                how="left",
            )
            oracle_expanded = oracle_expanded.merge(
                one_returns,
                on=["date", "symbol"],
                how="left",
            )
            oracle_expanded["daily_symbol_return"] = pd.to_numeric(
                oracle_expanded["daily_symbol_return"],
                errors="coerce",
            ).fillna(0.0)
            oracle_expanded["weight"] = pd.to_numeric(
                oracle_expanded["weight"],
                errors="coerce",
            ).fillna(0.0)
            oracle_expanded["holding_count"] = len(oracle_holdings)
            oracle_expanded["portfolio_ret_part"] = (
                oracle_expanded["daily_symbol_return"] * oracle_expanded["weight"]
            )
            oracle_period_frames.append(oracle_expanded)

    if not period_frames:
        raise ValueError(f"Strategy {strategy_name} has no matched daily returns after expansion")

    expanded_returns = pd.concat(period_frames, ignore_index=True)
    daily_result = (
        expanded_returns.groupby("date")
        .agg(
            portfolio_ret=("portfolio_ret_part", "sum"),
            holding_count=("holding_count", "max"),
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

    cost_frame = _expand_rebalance_costs(
        rebalance_cost_records=rebalance_cost_records,
        available_dates=daily_result["date"],
        initial_cash=initial_cash,
    )
    daily_result = daily_result.merge(cost_frame, on="date", how="left")
    daily_result["transaction_cost"] = pd.to_numeric(
        daily_result["transaction_cost"],
        errors="coerce",
    ).fillna(0.0)
    daily_result["gross_turnover"] = pd.to_numeric(
        daily_result["gross_turnover"],
        errors="coerce",
    ).fillna(0.0)
    daily_result["blocked_order_count"] = pd.to_numeric(
        daily_result["blocked_order_count"],
        errors="coerce",
    ).fillna(0).astype(int)
    daily_result["gross_daily_return"] = daily_result["daily_return"]
    daily_result["net_daily_return"] = daily_result["gross_daily_return"] - daily_result["transaction_cost"]
    daily_result["daily_return"] = daily_result["net_daily_return"]
    daily_result["nav"] = (1 + daily_result["daily_return"]).cumprod() * initial_cash
    daily_result["net_value"] = daily_result["nav"]
    daily_result["initial_cash"] = float(initial_cash)

    theoretical_summary = None
    if oracle_period_frames:
        theoretical_daily = _build_daily_result(
            period_frames=oracle_period_frames,
            initial_date=initial_date,
            initial_holding_count=initial_holding_count,
            initial_cash=initial_cash,
        )
        theoretical_metrics, _ = calc_backtest_metrics(
            daily_result=theoretical_daily,
            risk_free_rate=risk_free_rate,
        )
        theoretical_summary = _metrics_to_dict(theoretical_metrics)

    metrics, drawdown = calc_backtest_metrics(
        daily_result=daily_result,
        risk_free_rate=risk_free_rate,
    )
    gross_nav = (1 + daily_result["gross_daily_return"]).cumprod() * initial_cash
    execution_metrics = pd.DataFrame(
        {
            "metric": [
                "gross_total_return",
                "net_total_return",
                "turnover_ratio",
                "transaction_cost_ratio",
                "blocked_order_count",
            ],
            "value": [
                gross_nav.iloc[-1] / float(initial_cash) - 1 if len(gross_nav) else np.nan,
                daily_result["net_value"].iloc[-1] / float(initial_cash) - 1,
                daily_result["gross_turnover"].sum() / float(initial_cash),
                daily_result["transaction_cost"].sum(),
                int(daily_result["blocked_order_count"].sum()),
            ],
        }
    )
    metrics = pd.concat([metrics, execution_metrics], ignore_index=True)
    daily_result["drawdown"] = drawdown.values
    holdings_record = daily_result[["date", "holding_count"]].copy()
    liquidity_report = build_liquidity_lock_report(
        pd.concat(delayed_orders, ignore_index=True) if delayed_orders else pd.DataFrame()
    )

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    daily_csv = RESULT_DIR / f"backtest_daily_result_{strategy_name}.csv"
    daily_parquet = RESULT_DIR / f"backtest_daily_result_{strategy_name}.parquet"
    metrics_csv = RESULT_DIR / f"backtest_metrics_{strategy_name}.csv"
    holdings_csv = RESULT_DIR / f"backtest_holdings_{strategy_name}.csv"
    plot_file = RESULT_DIR / f"equity_curve_{strategy_name}.png"
    learning_meta_csv = RESULT_DIR / f"backtest_learning_metadata_{strategy_name}.csv"
    order_ledger_csv = RESULT_DIR / f"{ORDER_LEDGER_PREFIX}_{strategy_name}.csv"

    daily_result.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    daily_result.to_parquet(daily_parquet, index=False)
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    holdings_record.to_csv(holdings_csv, index=False, encoding="utf-8-sig")
    order_ledger = pd.concat(order_ledger_parts, ignore_index=True) if order_ledger_parts else pd.DataFrame()
    order_ledger.to_csv(order_ledger_csv, index=False, encoding="utf-8-sig")
    _save_learning_metadata(df_sel, learning_meta_csv)
    if not liquidity_report.empty:
        save_liquidity_lock_report(
            liquidity_report,
            output_path=LIQUIDITY_LOCK_REPORT_CSV,
        )

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
    if theoretical_summary is not None:
        print("\n========== Theoretical Upper Bound ==========")
        print(
            "Same rebalance dates and holding count, but each period picks the future best performers."
        )
        print(
            "Theoretical final net value:",
            _format_metric(theoretical_summary.get("final_net_value"), is_percent=False),
        )
        print(
            "Theoretical total return:",
            _format_metric(theoretical_summary.get("total_return"), is_percent=True),
        )
        print(
            "Theoretical annual return:",
            _format_metric(theoretical_summary.get("annual_return"), is_percent=True),
        )
        if "final_net_value" in theoretical_summary and "final_net_value" in _metrics_to_dict(metrics):
            realized_nav = float(_metrics_to_dict(metrics).get("final_net_value"))
            theoretical_nav = float(theoretical_summary.get("final_net_value"))
            if realized_nav != 0:
                print("Upper-bound multiple vs strategy:", f"{theoretical_nav / realized_nav:.2f}x")
    print("Saved daily CSV:", daily_csv)
    print("Saved daily Parquet:", daily_parquet)
    print("Saved metrics:", metrics_csv)
    print("Saved holdings:", holdings_csv)
    print("Saved order ledger:", order_ledger_csv)
    if learning_meta_csv.exists():
        print("Saved learning metadata:", learning_meta_csv)
    if not liquidity_report.empty:
        print("Saved liquidity lock report:", LIQUIDITY_LOCK_REPORT_CSV)
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
    if plt is None:
        print("Skip equity plot: matplotlib is not installed in current environment.")
        return

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


def _build_oracle_holdings(
    feature_data,
    returns,
    rebalance_date,
    period_dates,
    holding_count,
    allowed_instrument_types=None,
):
    candidates = feature_data[feature_data["date"] == rebalance_date].copy()
    if candidates.empty or holding_count <= 0:
        return pd.DataFrame(columns=["symbol", "weight"])

    if allowed_instrument_types is not None:
        allow_types = pd.Series(allowed_instrument_types).dropna().unique().tolist()
        if allow_types and "instrument_type" in candidates.columns:
            candidates = candidates[candidates["instrument_type"].isin(allow_types)]

    if "is_trading" in candidates.columns:
        candidates = candidates[candidates["is_trading"] == True]
    if "abnormal_jump" in candidates.columns:
        candidates = candidates[candidates["abnormal_jump"] == False]

    if candidates.empty:
        return pd.DataFrame(columns=["symbol", "weight"])

    period_returns = returns[
        (returns["date"].isin(period_dates)) & (returns["symbol"].isin(candidates["symbol"]))
    ].copy()

    if period_returns.empty:
        candidates = candidates[["symbol"]].drop_duplicates().head(holding_count).copy()
        candidates["weight"] = 1.0 / len(candidates)
        return candidates

    symbol_period_return = (
        period_returns.groupby("symbol")["daily_symbol_return"]
        .apply(lambda s: (1.0 + s.fillna(0.0)).prod() - 1.0)
        .rename("period_return")
        .reset_index()
    )
    ranked = candidates[["symbol"]].drop_duplicates().merge(
        symbol_period_return,
        on="symbol",
        how="left",
    )
    ranked["period_return"] = pd.to_numeric(ranked["period_return"], errors="coerce").fillna(0.0)
    ranked = ranked.sort_values(["period_return", "symbol"], ascending=[False, True]).head(holding_count)
    ranked["weight"] = 1.0 / len(ranked)
    return ranked[["symbol", "weight"]]


def _build_daily_result(period_frames, initial_date, initial_holding_count, initial_cash):
    daily_result = (
        pd.concat(period_frames, ignore_index=True)
        .groupby("date")
        .agg(
            portfolio_ret=("portfolio_ret_part", "sum"),
            holding_count=("holding_count", "max"),
        )
        .reset_index()
        .sort_values("date")
    )
    daily_result["daily_return"] = daily_result["portfolio_ret"]

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
    return daily_result


def _metrics_to_dict(metrics):
    return dict(zip(metrics["metric"], metrics["value"]))


def _format_metric(value, is_percent):
    numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric_value):
        return "nan"
    if is_percent:
        return f"{numeric_value:.2%}"
    return f"{numeric_value:.4f}"


def _save_learning_metadata(df_selection, output_file):
    meta_cols = [col for col in LEARNING_METADATA_COLUMNS if col in df_selection.columns]
    if not meta_cols:
        return

    meta = df_selection[meta_cols].dropna(how="all").drop_duplicates()
    if meta.empty:
        return

    meta.to_csv(output_file, index=False, encoding="utf-8-sig")


def _load_feature_data():
    global _FEATURE_DATA_CACHE
    if _FEATURE_DATA_CACHE is None:
        wanted_columns = [
            "date",
            "symbol",
            "instrument_type",
            "close",
            "close_nominal",
            "is_trading",
            "abnormal_jump",
            "rough_limit_up",
            "rough_limit_down",
        ]
        available_columns = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
        columns = [col for col in wanted_columns if col in available_columns]
        _FEATURE_DATA_CACHE = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=columns)
    return _FEATURE_DATA_CACHE.copy()


def _build_rebalance_orders(one_holdings, previous_weights, feature_data, trade_date, initial_cash):
    current_weights = dict(zip(one_holdings["symbol"], one_holdings["weight"]))
    symbols = sorted(set(previous_weights) | set(current_weights))
    if not symbols:
        return pd.DataFrame(columns=["symbol", "trade_date", "side", "target_shares", "price"])

    price_col = "close_nominal" if "close_nominal" in feature_data.columns else "close"
    optional_cols = [
        col for col in ["is_trading", "rough_limit_up", "rough_limit_down"]
        if col in feature_data.columns
    ]
    price_frame = feature_data[feature_data["date"] == trade_date][
        ["symbol", price_col] + optional_cols
    ].drop_duplicates("symbol")
    price_map = dict(zip(price_frame["symbol"], price_frame[price_col]))
    state_map = price_frame.set_index("symbol").to_dict(orient="index")
    rows = []
    for symbol in symbols:
        prev_weight = float(previous_weights.get(symbol, 0.0))
        new_weight = float(current_weights.get(symbol, 0.0))
        delta_weight = new_weight - prev_weight
        if abs(delta_weight) < 1e-12:
            continue
        price = float(price_map.get(symbol, 0.0) or 0.0)
        if price <= 0:
            continue
        notional = abs(delta_weight) * float(initial_cash)
        raw_shares = notional / price
        target_shares = int(raw_shares // MIN_LOT_SIZE) * MIN_LOT_SIZE
        if target_shares <= 0:
            continue
        side = "buy" if delta_weight > 0 else "sell"
        trading_state = state_map.get(symbol, {})
        suspension_blocked = (
            "is_trading" in trading_state
            and not bool(trading_state.get("is_trading"))
        )
        price_limit_blocked = (
            bool(trading_state.get("rough_limit_up", False)) if side == "buy"
            else bool(trading_state.get("rough_limit_down", False))
        )
        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "side": side,
                "target_shares": target_shares,
                "price": price,
                "previous_weight": prev_weight,
                "target_weight": new_weight,
                "delta_weight": delta_weight,
                "same_day_sell_blocked": False,
                "price_limit_blocked_flag": price_limit_blocked,
                "suspension_blocked_flag": suspension_blocked,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["symbol", "trade_date", "side", "target_shares", "price"])
    return pd.DataFrame(rows)


def _apply_filled_orders_to_weights(previous_weights, simulated_orders):
    weights = dict(previous_weights)
    if simulated_orders.empty:
        return weights
    for _, order in simulated_orders.iterrows():
        if order["execution_status"] != "filled":
            continue
        symbol = order["symbol"]
        weights[symbol] = float(order.get("target_weight", weights.get(symbol, 0.0)))
        if weights[symbol] <= 1e-12:
            weights.pop(symbol, None)
    return weights


def _enforce_cash_weight_budget(previous_weights, simulated_orders):
    """Reject buys requiring proceeds from a blocked sell."""
    if simulated_orders.empty:
        return simulated_orders
    orders = simulated_orders.copy()
    weights = dict(previous_weights)
    filled_sells = orders[
        (orders["execution_status"] == "filled") & (orders["side"] == "sell")
    ]
    for _, order in filled_sells.iterrows():
        weights[order["symbol"]] = float(order["target_weight"])
    available_weight = max(1.0 - sum(weights.values()), 0.0)
    buy_rows = orders[
        (orders["execution_status"] == "filled") & (orders["side"] == "buy")
    ].index
    for row_index in buy_rows:
        required = max(float(orders.at[row_index, "delta_weight"]), 0.0)
        if required <= available_weight + 1e-12:
            available_weight -= required
            continue
        orders.at[row_index, "execution_status"] = "pending_cash"
        orders.at[row_index, "constraint_blocked"] = True
        orders.at[row_index, "executed_shares"] = 0.0
        orders.at[row_index, "remaining_shares"] = orders.at[row_index, "target_shares"]
    return estimate_trade_costs(orders, shares_col="executed_shares")


def _apply_weight_constraints(df_selection, max_weight):
    data = df_selection.copy()
    counts = data.groupby("rebalance_date")["symbol"].transform("count")
    default_weight = 1.0 / counts
    if "weight" not in data.columns:
        data["weight"] = default_weight
    else:
        data["weight"] = pd.to_numeric(data["weight"], errors="coerce").fillna(default_weight)

    group_total = data.groupby("rebalance_date")["weight"].transform("sum")
    group_total = group_total.where(group_total > 0, 1.0)
    data["weight"] = (data["weight"] / group_total).clip(lower=0.0, upper=max_weight)
    return data


def _expand_rebalance_costs(rebalance_cost_records, available_dates, initial_cash):
    if not rebalance_cost_records:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(available_dates),
                "transaction_cost": 0.0,
                "gross_turnover": 0.0,
                "blocked_order_count": 0,
            }
        )

    cost_frame = pd.DataFrame(rebalance_cost_records).copy()
    cost_frame["date"] = pd.to_datetime(cost_frame["rebalance_date"])
    divisor = float(initial_cash) if float(initial_cash) != 0 else 1.0
    cost_frame["transaction_cost"] = cost_frame["transaction_cost"] / divisor
    return cost_frame[["date", "transaction_cost", "gross_turnover", "blocked_order_count"]]


if __name__ == "__main__":
    raise SystemExit("Call run_backtest(df_selection=...) from main.py")
