# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from config import (
    DEFAULT_BACKTEST_CAPITAL_PROFILE,
    FEATURE_DAILY_PARQUET,
    LIQUIDITY_LOCK_REPORT_CSV,
    MIN_LOT_SIZE,
    OPEN_POSITION_LEDGER_PREFIX,
    ORDER_LEDGER_PREFIX,
    RESULT_DIR,
    TRADE_PAIR_LEDGER_PREFIX,
    CASH_LEDGER_PREFIX,
    TAX_LEDGER_PREFIX,
    VALUATION_LEDGER_PREFIX,
    backtest_profile_suffix,
    get_backtest_capital_profile,
)
from functions.execution.liquidity_lock_handler import (
    build_liquidity_lock_report,
    save_liquidity_lock_report,
)
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import build_delayed_order_queue, simulate_order_book
from functions.execution.tax_ledger import build_trade_tax_ledger, tax_ledger_total
from functions.execution.trade_pairing import build_trade_pairing_ledgers
from functions.execution.valuation import (
    build_blocked_order_valuation_ledger,
    valuation_discount_by_date,
)
from functions.benchmark import build_benchmark_return_frame
from functions.governance import research_status_dict
from functions.event_and_hedge import estimate_static_alpha_beta
from functions.metrics import calc_backtest_metrics
from functions.performance_charts import save_performance_diagnostics
from functions.date_window import assert_date_window, filter_date_window, normalize_date_window

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
RISK_MONITOR_FEATURE_COLUMNS = [
    "sector_parent",
    "is_hot_sector",
    "ret_20",
    "volatility_20",
    "close_to_ma20",
    "amount_ratio_20",
]


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
    start_date=None,
    end_date=None,
    capital_profile_name=DEFAULT_BACKTEST_CAPITAL_PROFILE,
    capital_profile=None,
):
    """
    Backtest one strategy by expanding rebalance selections into daily holdings.

    A position selected on rebalance date R is held from the next trading day
    through the next rebalance date. Daily returns come from the full feature
    table, not from shifted rows inside the sparse selection table.
    """
    feature_data = _load_feature_data()
    returns = prepare_daily_returns(feature_data)
    capital_profile = capital_profile or get_backtest_capital_profile(capital_profile_name)

    df_sel = df_selection.copy()
    required_cols = ["symbol", "rebalance_date"]
    missing_cols = [col for col in required_cols if col not in df_sel.columns]
    if missing_cols:
        raise ValueError(f"df_selection missing required columns: {missing_cols}")
    if df_sel.empty:
        raise ValueError(f"Strategy {strategy_name} selection is empty")

    backtest_start_date, backtest_end_date = normalize_date_window(start_date, end_date)
    df_sel = filter_date_window(
        df_sel,
        "rebalance_date",
        start_date=backtest_start_date,
        end_date=backtest_end_date,
    )
    if df_sel.empty:
        raise ValueError(
            f"Strategy {strategy_name} has no selections inside configured date window "
            f"{backtest_start_date.date() if backtest_start_date is not None else '-'} -> "
            f"{backtest_end_date.date() if backtest_end_date is not None else '-'}"
        )
    assert_date_window(
        df_sel,
        "rebalance_date",
        start_date=backtest_start_date,
        end_date=backtest_end_date,
        label=f"backtest selection {strategy_name}",
    )
    returns["date"] = pd.to_datetime(returns["date"])
    feature_data["date"] = pd.to_datetime(feature_data["date"])
    df_sel = df_sel.sort_values(["rebalance_date", "symbol"]).copy()
    selection_meta = _build_selection_metadata(df_sel, strategy_name=strategy_name)

    df_sel = _apply_weight_constraints(df_sel, max_weight=max_weight)

    rebalance_dates = pd.Series(df_sel["rebalance_date"].drop_duplicates().sort_values()).reset_index(drop=True)
    all_trade_dates = pd.Series(returns["date"].drop_duplicates().sort_values()).reset_index(drop=True)
    if backtest_start_date is not None:
        all_trade_dates = all_trade_dates[all_trade_dates >= backtest_start_date].reset_index(drop=True)
        rebalance_dates = rebalance_dates[rebalance_dates >= backtest_start_date].reset_index(drop=True)
    if backtest_end_date is not None:
        all_trade_dates = all_trade_dates[all_trade_dates <= backtest_end_date].reset_index(drop=True)
        rebalance_dates = rebalance_dates[rebalance_dates <= backtest_end_date].reset_index(drop=True)
        if rebalance_dates.empty:
            raise ValueError(f"Strategy {strategy_name} has no rebalance dates on or before {backtest_end_date.date() if backtest_end_date is not None else '-'}")
        if all_trade_dates.empty:
            raise ValueError(f"Strategy {strategy_name} has no trade dates on or before {backtest_end_date.date() if backtest_end_date is not None else '-'}")
    df_sel = _apply_capital_profile_selection_constraints(
        df_sel,
        capital_profile=capital_profile,
        feature_data=feature_data,
        all_trade_dates=all_trade_dates,
    )
    if df_sel.empty:
        raise ValueError(f"Strategy {strategy_name} has no affordable selections for capital profile {capital_profile['name']}")
    rebalance_dates = pd.Series(df_sel["rebalance_date"].drop_duplicates().sort_values()).reset_index(drop=True)

    period_frames = []
    oracle_period_frames = []
    actual_weights = {}
    actual_shares = {}
    delayed_orders = []
    rebalance_cost_records = []
    order_ledger_parts = []
    for idx, rebalance_date in rebalance_dates.items():
        next_rebalance = (
            rebalance_dates.iloc[idx + 1]
            if idx + 1 < len(rebalance_dates)
            else all_trade_dates.max()
        )
        if backtest_end_date is not None:
            next_rebalance = min(pd.Timestamp(next_rebalance), backtest_end_date)
        period_dates = all_trade_dates[
            (all_trade_dates > rebalance_date) & (all_trade_dates <= next_rebalance)
        ]
        if period_dates.empty:
            continue

        one_holdings = df_sel[df_sel["rebalance_date"] == rebalance_date][
            ["rebalance_date", "symbol", "weight"]
        ].copy()
        execution_date = pd.Timestamp(period_dates.iloc[0])
        rebalance_orders = _build_rebalance_orders(
            one_holdings=one_holdings,
            previous_weights=actual_weights,
            previous_shares=actual_shares,
            feature_data=feature_data,
            trade_date=execution_date,
            initial_cash=initial_cash,
        )
        simulated_orders = simulate_order_book(rebalance_orders)
        simulated_orders = _enforce_cash_weight_budget(
            actual_weights,
            simulated_orders,
            min_cash_buffer_ratio=(
                capital_profile["min_cash_buffer"] / max(float(initial_cash), 1e-12)
            ),
        )
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
        actual_shares = _apply_filled_orders_to_shares(actual_shares, simulated_orders)
        actual_weights = _weights_from_shares(
            actual_shares,
            feature_data=feature_data,
            trade_date=execution_date,
            initial_cash=initial_cash,
        )
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
    # The live exploratory engine has not integrated an independent frozen-position
    # valuation model yet. Keep both views explicit and disclose the fallback.
    daily_result["liquidatable_nav"] = daily_result["nav"]
    daily_result["economic_nav"] = daily_result["nav"]
    daily_result["valuation_model_version"] = "conservative_liquidity_discount_v1"
    daily_result["initial_cash"] = float(initial_cash)
    for key, value in research_status_dict().items():
        daily_result[key] = value

    benchmark_frame, benchmark_meta = build_benchmark_return_frame(feature_data)
    benchmark_frame = benchmark_frame.copy()
    if not benchmark_frame.empty:
        daily_result = daily_result.merge(benchmark_frame, on="date", how="left")
        daily_result["benchmark_return"] = pd.to_numeric(
            daily_result["benchmark_return"], errors="coerce"
        ).fillna(0.0)
        daily_result["benchmark_nav"] = pd.to_numeric(
            daily_result["benchmark_nav"], errors="coerce"
        ).ffill()
        if daily_result["benchmark_nav"].dropna().empty:
            daily_result["benchmark_nav"] = (1.0 + daily_result["benchmark_return"]).cumprod() * initial_cash
        else:
            daily_result["benchmark_nav"] = daily_result["benchmark_nav"].fillna(
                (1.0 + daily_result["benchmark_return"]).cumprod()
            ) * initial_cash
        daily_result["excess_daily_return"] = daily_result["daily_return"] - daily_result["benchmark_return"]
        benchmark_stats = estimate_static_alpha_beta(
            daily_result[["date", "daily_return"]],
            daily_result[["date", "benchmark_return"]],
        )
        benchmark_excess_return = benchmark_stats["excess_return"]
        benchmark_status = benchmark_meta["benchmark_status"]
    else:
        daily_result["benchmark_return"] = np.nan
        daily_result["benchmark_nav"] = np.nan
        daily_result["excess_daily_return"] = np.nan
        benchmark_excess_return = np.nan
        benchmark_status = f"blocked: {benchmark_meta['benchmark_status']}"

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
    metrics = pd.concat(
        [
            metrics,
            pd.DataFrame(
                {
                    "metric": ["configured_start_date", "configured_end_date"],
                    "value": [
                        backtest_start_date.date().isoformat() if backtest_start_date is not None else None,
                        backtest_end_date.date().isoformat() if backtest_end_date is not None else None,
                    ],
                }
            ),
        ],
        ignore_index=True,
    )
    gross_nav = (1 + daily_result["gross_daily_return"]).cumprod() * initial_cash
    order_ledger = pd.concat(order_ledger_parts, ignore_index=True) if order_ledger_parts else pd.DataFrame()
    trade_pairs, open_positions, trade_summary = build_trade_pairing_ledgers(
        order_ledger,
        returns[["date", "symbol", "trade_close"]],
        capital_profile=capital_profile["name"],
    )
    tax_ledger = build_trade_tax_ledger(order_ledger)
    valuation_ledger = build_blocked_order_valuation_ledger(order_ledger)
    valuation_discount = valuation_discount_by_date(valuation_ledger)
    if not valuation_discount.empty:
        daily_result = daily_result.merge(valuation_discount, on="date", how="left")
    if "valuation_discount_amount" not in daily_result.columns:
        daily_result["valuation_discount_amount"] = 0.0
    daily_result["valuation_discount_amount"] = pd.to_numeric(
        daily_result["valuation_discount_amount"], errors="coerce"
    ).fillna(0.0)
    daily_result["economic_nav"] = (
        daily_result["liquidatable_nav"] - daily_result["valuation_discount_amount"]
    ).clip(lower=0.0)
    total_orders = len(order_ledger)
    blocked_orders = (
        int((order_ledger["execution_status"] != "filled").sum())
        if total_orders and "execution_status" in order_ledger.columns
        else 0
    )
    tax_impact = tax_ledger_total(tax_ledger)
    if total_orders:
        frozen_orders = order_ledger.copy()
        frozen_orders["frozen_notional"] = (
            pd.to_numeric(frozen_orders.get("remaining_shares"), errors="coerce").fillna(0.0)
            * pd.to_numeric(frozen_orders.get("price"), errors="coerce").fillna(0.0)
        )
        frozen_notional = float(
            frozen_orders.groupby("trade_date")["frozen_notional"].sum().max()
        )
    else:
        frozen_notional = 0.0
    frozen_aum_ratio = frozen_notional / float(initial_cash)
    final_cash_drag = max(1.0 - sum(actual_weights.values()), 0.0)
    base_cost_ratio = float(daily_result["transaction_cost"].sum())
    gross_total_return = gross_nav.iloc[-1] / float(initial_cash) - 1 if len(gross_nav) else np.nan
    status = research_status_dict()
    risk_monitor_summary, risk_monitor_detail = _build_risk_monitoring_outputs(df_sel, feature_data)
    final_degradation_parts = [
        flag for flag in str(selection_meta.get("degradation_flags", "")).split("|")
        if str(flag).strip()
    ]
    if benchmark_frame.empty and "benchmark_unavailable" not in final_degradation_parts:
        final_degradation_parts.append("benchmark_unavailable")

    execution_metrics = pd.DataFrame(
        {
            "metric": [
                "gross_total_return",
                "net_total_return",
                "turnover_ratio",
                "transaction_cost_ratio",
                "blocked_order_count",
                "failed_order_ratio",
                "tax_impact_ratio",
                "frozen_aum_ratio",
                "cash_drag",
                "liquidatable_total_return",
                "economic_total_return",
                "benchmark_excess_return",
                "benchmark_status",
                "capital_profile",
                "capital_initial_cash",
                "capital_min_cash_buffer",
                "capital_max_positions",
                "trade_win_rate",
                "realized_trade_count",
                "winning_trade_count",
                "losing_trade_count",
                "realized_pnl_amount",
                "unrealized_pnl_amount",
                "open_position_count",
                "inventory_underflow_count",
                "crowding_top_sector_weight",
                "crowding_hot_sector_weight",
                "crowding_unique_sector_count",
                "exposure_ret_20_tilt",
                "exposure_volatility_20_tilt",
                "exposure_close_to_ma20_tilt",
                "exposure_amount_ratio_20_tilt",
                "cost_sensitivity_low_return",
                "cost_sensitivity_base_return",
                "cost_sensitivity_high_return",
                "strategy_source",
                "weighting_mode",
                "price_basis",
                "neutralization_mode",
                "ml_runtime_mode",
                "requested_model",
                "runtime_model",
                "date_window",
                "strategy_params_version",
                "strategy_params_hash",
                "training_window_days",
                "training_sample_count",
                "label_purge_periods",
                "prior_p",
                "prior_strength",
                "prior_source",
                "posterior_alpha",
                "posterior_beta",
                "posterior_sample_count",
                "signal_candidate_count",
                "signal_trigger_count",
                "signal_trigger_rate",
                "adjustment_coverage_ratio",
                "adjustment_coverage_threshold",
                "price_basis_selection_mode",
                "degradation_flags",
                "degradation_count",
                "top1_weight",
                "top5_weight_sum",
                "effective_n",
                "research_mode",
                "formal_status",
                "formal_eligible",
                "formal_block_reason_code",
                "execution_model_version",
            ],
            "value": [
                gross_total_return,
                daily_result["net_value"].iloc[-1] / float(initial_cash) - 1,
                daily_result["gross_turnover"].sum() / float(initial_cash),
                base_cost_ratio,
                blocked_orders,
                blocked_orders / total_orders if total_orders else 0.0,
                tax_impact / float(initial_cash),
                frozen_aum_ratio,
                final_cash_drag,
                daily_result["liquidatable_nav"].iloc[-1] / float(initial_cash) - 1,
                daily_result["economic_nav"].iloc[-1] / float(initial_cash) - 1,
                benchmark_excess_return,
                benchmark_status,
                capital_profile["name"],
                capital_profile["initial_cash"],
                capital_profile["min_cash_buffer"],
                capital_profile["max_positions"] if capital_profile["max_positions"] is not None else np.nan,
                trade_summary["trade_win_rate"],
                trade_summary["realized_trade_count"],
                trade_summary["winning_trade_count"],
                trade_summary["losing_trade_count"],
                trade_summary["realized_pnl_amount"],
                trade_summary["unrealized_pnl_amount"],
                trade_summary["open_position_count"],
                trade_summary["inventory_underflow_count"],
                risk_monitor_summary.get("crowding_top_sector_weight", np.nan),
                risk_monitor_summary.get("crowding_hot_sector_weight", np.nan),
                risk_monitor_summary.get("crowding_unique_sector_count", np.nan),
                risk_monitor_summary.get("exposure_ret_20_tilt", np.nan),
                risk_monitor_summary.get("exposure_volatility_20_tilt", np.nan),
                risk_monitor_summary.get("exposure_close_to_ma20_tilt", np.nan),
                risk_monitor_summary.get("exposure_amount_ratio_20_tilt", np.nan),
                gross_total_return - 0.5 * base_cost_ratio,
                gross_total_return - base_cost_ratio,
                gross_total_return - 2.0 * base_cost_ratio,
                selection_meta["strategy_source"],
                selection_meta["weighting_mode"],
                selection_meta["price_basis"],
                selection_meta["neutralization_mode"],
                selection_meta["ml_runtime_mode"],
                selection_meta["requested_model"],
                selection_meta["runtime_model"],
                selection_meta["date_window"],
                selection_meta["strategy_params_version"],
                selection_meta["strategy_params_hash"],
                selection_meta["training_window_days"],
                selection_meta["training_sample_count"],
                selection_meta["label_purge_periods"],
                selection_meta["prior_p"],
                selection_meta["prior_strength"],
                selection_meta["prior_source"],
                selection_meta["posterior_alpha"],
                selection_meta["posterior_beta"],
                selection_meta["posterior_sample_count"],
                selection_meta["signal_candidate_count"],
                selection_meta["signal_trigger_count"],
                selection_meta["signal_trigger_rate"],
                selection_meta["adjustment_coverage_ratio"],
                selection_meta["adjustment_coverage_threshold"],
                selection_meta["price_basis_selection_mode"],
                "|".join(final_degradation_parts),
                len(final_degradation_parts),
                selection_meta["top1_weight"],
                selection_meta["top5_weight_sum"],
                selection_meta["effective_n"],
                status["research_mode"],
                status["formal_status"],
                status["formal_eligible"],
                status["formal_block_reason_code"],
                status["execution_model_version"],
            ],
        }
    )
    metrics = pd.concat([metrics, execution_metrics], ignore_index=True)
    daily_result["drawdown"] = drawdown.reindex(daily_result.index).fillna(0.0).values
    for key in [
        "strategy_source",
        "weighting_mode",
        "price_basis",
        "neutralization_mode",
        "ml_runtime_mode",
        "requested_model",
        "runtime_model",
        "date_window",
        "strategy_params_version",
        "strategy_params_hash",
        "price_basis_selection_mode",
        "prior_source",
        "degradation_flags",
    ]:
        if key == "degradation_flags":
            daily_result[key] = "|".join(final_degradation_parts)
        else:
            daily_result[key] = selection_meta[key]
    daily_result["benchmark_status"] = benchmark_status
    daily_result["benchmark_excess_return"] = benchmark_excess_return
    daily_result["benchmark_id"] = benchmark_meta.get("benchmark_id", "")
    daily_result["benchmark_symbol"] = benchmark_meta.get("benchmark_symbol", "")
    holdings_record = daily_result[["date", "holding_count"]].copy()
    suffix = backtest_profile_suffix(capital_profile["name"])
    liquidity_report_csv = (
        LIQUIDITY_LOCK_REPORT_CSV.with_name(
            f"{LIQUIDITY_LOCK_REPORT_CSV.stem}{suffix}{LIQUIDITY_LOCK_REPORT_CSV.suffix}"
        )
        if suffix
        else LIQUIDITY_LOCK_REPORT_CSV
    )
    liquidity_report = build_liquidity_lock_report(
        pd.concat(delayed_orders, ignore_index=True) if delayed_orders else pd.DataFrame()
    )

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    daily_csv = RESULT_DIR / f"backtest_daily_result_{strategy_name}{suffix}.csv"
    daily_parquet = RESULT_DIR / f"backtest_daily_result_{strategy_name}{suffix}.parquet"
    metrics_csv = RESULT_DIR / f"backtest_metrics_{strategy_name}{suffix}.csv"
    holdings_csv = RESULT_DIR / f"backtest_holdings_{strategy_name}{suffix}.csv"
    plot_file = RESULT_DIR / f"equity_curve_{strategy_name}{suffix}.png"
    learning_meta_csv = RESULT_DIR / f"backtest_learning_metadata_{strategy_name}{suffix}.csv"
    order_ledger_csv = RESULT_DIR / f"{ORDER_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    trade_pair_csv = RESULT_DIR / f"{TRADE_PAIR_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    open_position_csv = RESULT_DIR / f"{OPEN_POSITION_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    tax_ledger_csv = RESULT_DIR / f"{TAX_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    cash_ledger_csv = RESULT_DIR / f"{CASH_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    valuation_ledger_csv = RESULT_DIR / f"{VALUATION_LEDGER_PREFIX}_{strategy_name}{suffix}.csv"
    risk_monitor_csv = RESULT_DIR / f"risk_monitoring_{strategy_name}{suffix}.csv"

    daily_result.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    daily_result.to_parquet(daily_parquet, index=False)
    metrics.to_csv(metrics_csv, index=False, encoding="utf-8-sig")
    holdings_record.to_csv(holdings_csv, index=False, encoding="utf-8-sig")
    order_ledger.to_csv(order_ledger_csv, index=False, encoding="utf-8-sig")
    trade_pairs.to_csv(trade_pair_csv, index=False, encoding="utf-8-sig")
    open_positions.to_csv(open_position_csv, index=False, encoding="utf-8-sig")
    tax_ledger.to_csv(tax_ledger_csv, index=False, encoding="utf-8-sig")
    daily_result[
        ["date", "initial_cash", "net_value", "liquidatable_nav", "economic_nav", "valuation_discount_amount"]
    ].to_csv(cash_ledger_csv, index=False, encoding="utf-8-sig")
    valuation_ledger.to_csv(valuation_ledger_csv, index=False, encoding="utf-8-sig")
    risk_monitor_detail.to_csv(risk_monitor_csv, index=False, encoding="utf-8-sig")
    _save_learning_metadata(df_sel, learning_meta_csv)
    if not liquidity_report.empty:
        save_liquidity_lock_report(
            liquidity_report,
            output_path=liquidity_report_csv,
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
    diagnostic_outputs = save_performance_diagnostics(
        daily_result=daily_result,
        strategy_name=f"{strategy_name}{suffix}",
        output_dir=RESULT_DIR,
        selection=df_sel,
        feature_data=feature_data,
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
    print("Saved trade pairs:", trade_pair_csv)
    print("Saved open positions:", open_position_csv)
    print("Saved tax ledger:", tax_ledger_csv)
    print("Saved cash ledger:", cash_ledger_csv)
    print("Saved valuation ledger:", valuation_ledger_csv)
    print("Saved risk monitoring:", risk_monitor_csv)
    if learning_meta_csv.exists():
        print("Saved learning metadata:", learning_meta_csv)
    if not liquidity_report.empty:
        print("Saved liquidity lock report:", liquidity_report_csv)
    print("Saved equity curve:", plot_file)
    for label, path in diagnostic_outputs.items():
        print(f"Saved {label}:", path)

    return daily_result, metrics, holdings_record


def _build_selection_metadata(df_selection, *, strategy_name: str) -> dict:
    def _first_non_empty(column_name, default):
        if column_name not in df_selection.columns:
            return default
        series = df_selection[column_name].dropna().astype(str)
        series = series[series.str.len() > 0]
        return series.iloc[0] if not series.empty else default

    def _grouped_numeric_average(column_name, default=np.nan):
        if column_name not in df_selection.columns:
            return default
        values = []
        if "rebalance_date" in df_selection.columns and not df_selection.empty:
            for _, group in df_selection.groupby("rebalance_date", sort=False):
                series = pd.to_numeric(group[column_name], errors="coerce").dropna()
                if not series.empty:
                    values.append(float(series.iloc[0]))
        else:
            series = pd.to_numeric(df_selection[column_name], errors="coerce").dropna()
            if not series.empty:
                values.extend(series.astype(float).tolist())
        return float(np.mean(values)) if values else default

    weights = pd.to_numeric(df_selection.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    grouped_weights = []
    if "rebalance_date" in df_selection.columns and not df_selection.empty:
        for _, group in df_selection.groupby("rebalance_date", sort=False):
            group_weights = pd.to_numeric(group.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            if group_weights.empty:
                continue
            sorted_weights = group_weights.sort_values(ascending=False).reset_index(drop=True)
            top1 = float(sorted_weights.iloc[0]) if len(sorted_weights) else 0.0
            top5 = float(sorted_weights.head(5).sum())
            effective_n = float(1.0 / np.square(sorted_weights).sum()) if np.square(sorted_weights).sum() > 0 else 0.0
            grouped_weights.append((top1, top5, effective_n))
    if grouped_weights:
        top1_weight = float(np.mean([item[0] for item in grouped_weights]))
        top5_weight_sum = float(np.mean([item[1] for item in grouped_weights]))
        effective_n = float(np.mean([item[2] for item in grouped_weights]))
    else:
        top1_weight = float(weights.max()) if not weights.empty else 0.0
        top5_weight_sum = float(weights.sort_values(ascending=False).head(5).sum()) if not weights.empty else 0.0
        effective_n = float(1.0 / np.square(weights).sum()) if np.square(weights).sum() > 0 else 0.0

    degradation_parts = []
    if "degradation_flags" in df_selection.columns:
        for value in df_selection["degradation_flags"].fillna("").astype(str):
            for flag in value.split("|"):
                flag = flag.strip()
                if flag and flag not in degradation_parts:
                    degradation_parts.append(flag)

    return {
        "strategy": strategy_name,
        "strategy_source": _first_non_empty("strategy_source", "unknown"),
        "weighting_mode": _first_non_empty("weighting_mode", "equal_weight"),
        "price_basis": _first_non_empty("price_basis", _first_non_empty("feature_price_source", "nominal_unadjusted")),
        "neutralization_mode": _first_non_empty("neutralization_mode", "winsor_only"),
        "ml_runtime_mode": _first_non_empty("ml_runtime_mode", "not_applicable"),
        "requested_model": _first_non_empty("requested_model", ""),
        "runtime_model": _first_non_empty("runtime_model", ""),
        "date_window": _first_non_empty("date_window", ""),
        "strategy_params_version": _first_non_empty("strategy_params_version", ""),
        "strategy_params_hash": _first_non_empty("strategy_params_hash", ""),
        "training_window_days": _grouped_numeric_average("training_window_days"),
        "training_sample_count": _grouped_numeric_average("training_sample_count"),
        "label_purge_periods": _grouped_numeric_average("label_purge_periods"),
        "prior_p": _grouped_numeric_average("prior_p"),
        "prior_strength": _grouped_numeric_average("prior_strength"),
        "prior_source": _first_non_empty("prior_source", ""),
        "posterior_alpha": _grouped_numeric_average("posterior_alpha"),
        "posterior_beta": _grouped_numeric_average("posterior_beta"),
        "posterior_sample_count": _grouped_numeric_average("posterior_sample_count"),
        "signal_candidate_count": _grouped_numeric_average("signal_candidate_count"),
        "signal_trigger_count": _grouped_numeric_average("signal_trigger_count"),
        "signal_trigger_rate": _grouped_numeric_average("signal_trigger_rate"),
        "adjustment_coverage_ratio": _grouped_numeric_average("adjustment_coverage_ratio"),
        "adjustment_coverage_threshold": _grouped_numeric_average("adjustment_coverage_threshold"),
        "price_basis_selection_mode": _first_non_empty("price_basis_selection_mode", ""),
        "degradation_flags": "|".join(degradation_parts),
        "degradation_count": len(degradation_parts),
        "top1_weight": top1_weight,
        "top5_weight_sum": top5_weight_sum,
        "effective_n": effective_n,
    }


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
            "open",
            "open_nominal",
            "is_trading",
            "abnormal_jump",
            "rough_limit_up",
            "rough_limit_down",
        ]
        wanted_columns.extend(RISK_MONITOR_FEATURE_COLUMNS)
        available_columns = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
        wanted_columns.extend(
            sorted(
                col
                for col in available_columns
                if str(col).startswith("future_ret_")
            )
        )
        columns = [col for col in wanted_columns if col in available_columns]
        _FEATURE_DATA_CACHE = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=columns)
    return _FEATURE_DATA_CACHE.copy()


def _build_risk_monitoring_outputs(df_selection, feature_data):
    columns = [
        "rebalance_date",
        "symbol",
        "weight",
        "sector_parent",
        "is_hot_sector",
        "ret_20",
        "volatility_20",
        "close_to_ma20",
        "amount_ratio_20",
        "universe_ret_20_mean",
        "universe_volatility_20_mean",
        "universe_close_to_ma20_mean",
        "universe_amount_ratio_20_mean",
        "top_sector_weight",
        "hot_sector_weight",
        "unique_sector_count",
        "exposure_ret_20_tilt",
        "exposure_volatility_20_tilt",
        "exposure_close_to_ma20_tilt",
        "exposure_amount_ratio_20_tilt",
    ]
    if df_selection is None or df_selection.empty or "rebalance_date" not in df_selection.columns:
        return {key: np.nan for key in columns if key != "rebalance_date" and key != "symbol"}, pd.DataFrame(columns=columns)

    selection = df_selection.copy()
    selection["rebalance_date"] = pd.to_datetime(selection["rebalance_date"], errors="coerce")
    selection["symbol"] = selection["symbol"].astype(str)
    selection["weight"] = pd.to_numeric(selection.get("weight"), errors="coerce").fillna(0.0)

    feature_cols = ["date", "symbol", *[col for col in RISK_MONITOR_FEATURE_COLUMNS if col in feature_data.columns]]
    snapshot = feature_data.loc[:, feature_cols].copy()
    snapshot["date"] = pd.to_datetime(snapshot["date"], errors="coerce")
    snapshot["symbol"] = snapshot["symbol"].astype(str)

    merged = selection.merge(
        snapshot,
        left_on=["rebalance_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
    )
    universe = snapshot[snapshot["date"].isin(merged["rebalance_date"].dropna().unique())].copy()

    exposure_rows = []
    for rebalance_date, group in merged.groupby("rebalance_date", sort=True):
        weights = pd.to_numeric(group["weight"], errors="coerce").fillna(0.0)
        if float(weights.sum()) > 0:
            weights = weights / float(weights.sum())
        day_universe = universe[universe["date"] == rebalance_date]
        sector_column = _monitor_column_name(group, "sector_parent")
        hot_column = _monitor_column_name(group, "is_hot_sector")
        sector_series = (
            group.get(sector_column, pd.Series("", index=group.index))
            .fillna("")
            .astype(str)
            .replace("", pd.NA)
        )
        if sector_series.dropna().empty:
            top_sector_weight = np.nan
            unique_sector_count = np.nan
        else:
            sector_weight = group.assign(weight=weights).groupby(sector_series)["weight"].sum()
            top_sector_weight = float(sector_weight.max()) if not sector_weight.empty else np.nan
            unique_sector_count = float(sector_series.dropna().nunique())

        hot_series = group.get(hot_column, pd.Series(pd.NA, index=group.index))
        hot_numeric = pd.Series(hot_series).astype("boolean")
        hot_sector_weight = (
            float(weights[hot_numeric.fillna(False).astype(bool)].sum())
            if hot_numeric.notna().any()
            else np.nan
        )

        row = {
            "rebalance_date": rebalance_date,
            "symbol": "",
            "weight": float(weights.sum()),
            "sector_parent": "",
            "is_hot_sector": pd.NA,
            "ret_20": pd.NA,
            "volatility_20": pd.NA,
            "close_to_ma20": pd.NA,
            "amount_ratio_20": pd.NA,
            "top_sector_weight": top_sector_weight,
            "hot_sector_weight": hot_sector_weight,
            "unique_sector_count": unique_sector_count,
        }
        for col in ["ret_20", "volatility_20", "close_to_ma20", "amount_ratio_20"]:
            selected_mean = _weighted_average(group.get(_monitor_column_name(group, col)), weights)
            universe_mean = pd.to_numeric(day_universe.get(col), errors="coerce").dropna().mean() if col in day_universe.columns else np.nan
            row[f"universe_{col}_mean"] = universe_mean
            row[f"exposure_{col}_tilt"] = selected_mean - universe_mean if pd.notna(selected_mean) and pd.notna(universe_mean) else np.nan
        exposure_rows.append(row)

    detail = pd.DataFrame(exposure_rows, columns=columns)
    summary = {
        "crowding_top_sector_weight": float(pd.to_numeric(detail.get("top_sector_weight"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "crowding_hot_sector_weight": float(pd.to_numeric(detail.get("hot_sector_weight"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "crowding_unique_sector_count": float(pd.to_numeric(detail.get("unique_sector_count"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "exposure_ret_20_tilt": float(pd.to_numeric(detail.get("exposure_ret_20_tilt"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "exposure_volatility_20_tilt": float(pd.to_numeric(detail.get("exposure_volatility_20_tilt"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "exposure_close_to_ma20_tilt": float(pd.to_numeric(detail.get("exposure_close_to_ma20_tilt"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
        "exposure_amount_ratio_20_tilt": float(pd.to_numeric(detail.get("exposure_amount_ratio_20_tilt"), errors="coerce").dropna().mean()) if not detail.empty else np.nan,
    }
    return summary, detail


def _weighted_average(values, weights):
    if values is None:
        return np.nan
    series = pd.to_numeric(pd.Series(values), errors="coerce")
    weight_series = pd.to_numeric(pd.Series(weights), errors="coerce")
    valid = series.notna() & weight_series.notna()
    if not valid.any():
        return np.nan
    clean_weights = weight_series[valid].fillna(0.0)
    denom = float(clean_weights.sum())
    if denom <= 0:
        return np.nan
    return float((series[valid] * clean_weights).sum() / denom)


def _monitor_column_name(frame: pd.DataFrame, base_name: str) -> str:
    if base_name in frame.columns:
        return base_name
    for suffix in ("_y", "_x"):
        candidate = f"{base_name}{suffix}"
        if candidate in frame.columns:
            return candidate
    return base_name


def _build_rebalance_orders(one_holdings, previous_weights, previous_shares, feature_data, trade_date, initial_cash):
    current_weights = dict(zip(one_holdings["symbol"], one_holdings["weight"]))
    symbols = sorted(set(previous_weights) | set(current_weights) | set(previous_shares))
    if not symbols:
        return pd.DataFrame(columns=["symbol", "trade_date", "side", "target_shares", "price"])

    price_col = next(
        (col for col in ["open_nominal", "open", "close_nominal", "close"] if col in feature_data.columns),
        None,
    )
    if price_col is None:
        raise ValueError("No nominal execution price column is available")
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
        price = float(price_map.get(symbol, 0.0) or 0.0)
        if price <= 0:
            continue
        previous_position_shares = float(previous_shares.get(symbol, 0.0) or 0.0)
        target_position_shares = int((max(new_weight, 0.0) * float(initial_cash)) // price // MIN_LOT_SIZE) * MIN_LOT_SIZE
        delta_shares = float(target_position_shares - previous_position_shares)
        if abs(delta_shares) < 1e-12:
            continue
        trade_shares = abs(delta_shares)
        if trade_shares <= 0:
            continue
        side = "buy" if delta_shares > 0 else "sell"
        if side == "sell":
            trade_shares = min(trade_shares, previous_position_shares)
            if trade_shares <= 0:
                continue
        delta_weight = new_weight - prev_weight
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
                "target_shares": trade_shares,
                "price": price,
                "previous_weight": prev_weight,
                "target_weight": new_weight,
                "delta_weight": delta_weight,
                "previous_position_shares": previous_position_shares,
                "target_position_shares": float(target_position_shares),
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


def _apply_filled_orders_to_shares(previous_shares, simulated_orders):
    shares = {
        str(symbol): float(value)
        for symbol, value in dict(previous_shares).items()
        if float(value) > 1e-12
    }
    if simulated_orders.empty:
        return shares
    for _, order in simulated_orders.iterrows():
        if order["execution_status"] != "filled":
            continue
        symbol = str(order["symbol"])
        executed = float(order.get("executed_shares", 0.0) or 0.0)
        if executed <= 0.0:
            continue
        if str(order["side"]).lower() == "buy":
            shares[symbol] = shares.get(symbol, 0.0) + executed
        else:
            shares[symbol] = max(shares.get(symbol, 0.0) - executed, 0.0)
            if shares[symbol] <= 1e-12:
                shares.pop(symbol, None)
    return shares


def _weights_from_shares(position_shares, *, feature_data, trade_date, initial_cash):
    if not position_shares:
        return {}
    price_col = next(
        (col for col in ["open_nominal", "open", "close_nominal", "close"] if col in feature_data.columns),
        None,
    )
    if price_col is None:
        return {}
    price_frame = feature_data[feature_data["date"] == trade_date][["symbol", price_col]].drop_duplicates("symbol")
    price_map = dict(zip(price_frame["symbol"], pd.to_numeric(price_frame[price_col], errors="coerce").fillna(0.0)))
    weights = {}
    for symbol, shares in position_shares.items():
        price = float(price_map.get(symbol, 0.0) or 0.0)
        if price <= 0.0:
            continue
        weight = float(shares) * price / max(float(initial_cash), 1e-12)
        if weight > 1e-12:
            weights[str(symbol)] = weight
    return weights


def _enforce_cash_weight_budget(previous_weights, simulated_orders, *, min_cash_buffer_ratio=0.0):
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
    available_weight = max(1.0 - sum(weights.values()) - float(min_cash_buffer_ratio), 0.0)
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


def _apply_capital_profile_selection_constraints(df_selection, *, capital_profile, feature_data=None, all_trade_dates=None):
    data = df_selection.copy()
    max_positions = capital_profile.get("max_positions")
    if bool(capital_profile.get("affordability_first", False)) and feature_data is not None and all_trade_dates is not None:
        data = _filter_affordable_profile_candidates(
            data,
            capital_profile=capital_profile,
            feature_data=feature_data,
            all_trade_dates=all_trade_dates,
        )
        if data.empty:
            return data
    if max_positions is not None and max_positions > 0:
        weight_col = pd.to_numeric(data.get("weight"), errors="coerce").fillna(0.0)
        data = (
            data.assign(_weight_rank=weight_col, _selection_order=np.arange(len(data)))
            .sort_values(["rebalance_date", "_weight_rank", "_selection_order"], ascending=[True, False, True])
            .groupby("rebalance_date", group_keys=False)
            .head(int(max_positions))
            .drop(columns=["_weight_rank", "_selection_order"])
        )
        totals = data.groupby("rebalance_date")["weight"].transform("sum").replace(0.0, 1.0)
        data["weight"] = pd.to_numeric(data["weight"], errors="coerce").fillna(0.0) / totals
    return data


def _filter_affordable_profile_candidates(df_selection, *, capital_profile, feature_data, all_trade_dates):
    price_col = next(
        (col for col in ["open_nominal", "open", "close_nominal", "close"] if col in feature_data.columns),
        None,
    )
    if price_col is None:
        return df_selection
    max_positions = capital_profile.get("max_positions")
    if max_positions is None or max_positions <= 0:
        max_positions = int(df_selection.groupby("rebalance_date")["symbol"].transform("count").max() or 1)
    budget = max(float(capital_profile["initial_cash"]) - float(capital_profile.get("min_cash_buffer", 0.0) or 0.0), 0.0)
    per_position_budget = budget / max(int(max_positions), 1)
    if per_position_budget <= 0.0:
        return df_selection.iloc[0:0].copy()

    trade_dates = pd.to_datetime(pd.Series(all_trade_dates).dropna().sort_values()).reset_index(drop=True)
    price_data = feature_data[["date", "symbol", price_col]].copy()
    price_data["date"] = pd.to_datetime(price_data["date"], errors="coerce")
    price_data[price_col] = pd.to_numeric(price_data[price_col], errors="coerce")
    price_lookup = price_data.dropna(subset=["date", "symbol", price_col]).set_index(["date", "symbol"])[price_col]

    kept_indexes = []
    for rebalance_date, group in df_selection.groupby("rebalance_date", sort=True):
        future_dates = trade_dates[trade_dates > pd.Timestamp(rebalance_date)]
        if future_dates.empty:
            kept_indexes.extend(group.index.tolist())
            continue
        execution_date = pd.Timestamp(future_dates.iloc[0])
        for row_index, row in group.iterrows():
            price = price_lookup.get((execution_date, row["symbol"]), np.nan)
            if pd.isna(price) or float(price) <= 0.0:
                if not bool(capital_profile.get("skip_unaffordable_symbols", False)):
                    kept_indexes.append(row_index)
                continue
            if float(price) * float(MIN_LOT_SIZE) <= per_position_budget + 1e-12:
                kept_indexes.append(row_index)
    return df_selection.loc[kept_indexes].copy()


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
