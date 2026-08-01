"""Governance attribution metrics beyond headline NAV."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config import (
    COMMISSION_RATE,
    GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
    GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    TRANSFER_FEE_RATE,
)
from functions.execution.fee_schedule import stamp_duty_rate_for


VALID_INVESTED_EXPOSURE_FLOOR = 0.05
TOP_POOL_BENCHMARK_ID_PREFIX = "top_liquidity"


def build_governance_attribution(
    *,
    daily_result: pd.DataFrame,
    feature_data: pd.DataFrame,
    benchmark_symbol: str | None,
    factor_weight_ledger: pd.DataFrame | None = None,
    benchmark_top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    benchmark_rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> pd.DataFrame:
    """Add benchmark, invested-capital, exposure-adjusted, and factor-state metrics."""
    if daily_result is None or daily_result.empty:
        return pd.DataFrame()
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for column in ["nominal_nav", "liquidatable_nav", "cash", "invested_value", "target_exposure", "actual_exposure"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    if "actual_exposure" not in data.columns:
        data["actual_exposure"] = data["invested_value"] / data["nominal_nav"].replace(0.0, np.nan)
    data["actual_exposure"] = data["actual_exposure"].fillna(0.0).clip(lower=0.0)

    initial_nav = _first_positive(data["liquidatable_nav"])
    data["account_net_value"] = data["liquidatable_nav"] / initial_nav if initial_nav > 0 else np.nan
    data["account_daily_return"] = data["account_net_value"].pct_change(fill_method=None).fillna(0.0)
    data["account_drawdown"] = data["account_net_value"] / data["account_net_value"].cummax() - 1.0

    exposure = data["actual_exposure"].replace(0.0, np.nan)
    data["exposure_adjusted_daily_return"] = (data["account_daily_return"] / exposure).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    data["invested_capital_net_value"] = (1.0 + data["exposure_adjusted_daily_return"]).cumprod()
    data["invested_capital_drawdown"] = (
        data["invested_capital_net_value"] / data["invested_capital_net_value"].cummax() - 1.0
    )
    valid_exposure = data["actual_exposure"] >= float(VALID_INVESTED_EXPOSURE_FLOOR)
    data["valid_invested_capital_daily_return"] = np.where(
        valid_exposure,
        data["exposure_adjusted_daily_return"],
        0.0,
    )
    data["valid_invested_capital_net_value"] = (1.0 + data["valid_invested_capital_daily_return"]).cumprod()
    data["valid_invested_capital_drawdown"] = (
        data["valid_invested_capital_net_value"] / data["valid_invested_capital_net_value"].cummax() - 1.0
    )
    data["valid_invested_capital_observed"] = valid_exposure.astype(bool)
    # Approximation used for online diagnostics; exact holding-level return needs fill-level cash-flow attribution.
    data["holding_portfolio_daily_return"] = data["valid_invested_capital_daily_return"]
    data["holding_portfolio_net_value"] = data["valid_invested_capital_net_value"]
    data["cash_drag_daily_return"] = data["exposure_adjusted_daily_return"] - data["account_daily_return"]
    data["valid_cash_drag_daily_return"] = data["valid_invested_capital_daily_return"] - data["account_daily_return"]
    data["cash_drag_net_value"] = (1.0 + data["cash_drag_daily_return"]).cumprod()
    data["valid_cash_drag_net_value"] = (1.0 + data["valid_cash_drag_daily_return"]).cumprod()

    benchmark = _benchmark_series(
        feature_data,
        benchmark_symbol,
        top_n=benchmark_top_n,
        rebalance=benchmark_rebalance,
    )
    data = data.merge(benchmark, on="date", how="left")
    if "benchmark_return_valid" not in data.columns:
        data["benchmark_return_valid"] = data["benchmark_net_value"].notna()
    else:
        data["benchmark_return_valid"] = data["benchmark_return_valid"].astype("boolean").fillna(False).astype(bool)
    data["benchmark_net_value"] = data["benchmark_net_value"].ffill()
    benchmark_initial = _first_positive(data["benchmark_net_value"])
    if benchmark_initial > 0:
        data["benchmark_net_value"] = data["benchmark_net_value"] / benchmark_initial
    data["benchmark_daily_return_display"] = data["benchmark_net_value"].pct_change(fill_method=None).fillna(0.0)
    # Keep a continuous benchmark NAV for display, but never let a return with
    # incomplete constituent prices enter alpha, beta or capture statistics.
    data["benchmark_daily_return"] = data["benchmark_daily_return_display"].where(
        data["benchmark_return_valid"]
    )
    data["matched_exposure_benchmark_daily_return"] = (
        data["benchmark_daily_return"] * data["actual_exposure"].clip(0.0, 1.0)
    )
    data["matched_exposure_benchmark_net_value"] = (
        1.0 + data["matched_exposure_benchmark_daily_return"]
    ).cumprod()
    # Canonical relative wealth is a geometric NAV ratio.  Compounding the
    # arithmetic daily return difference is a different statistic and must not
    # be reported as benchmark excess return.
    benchmark_nav = data["benchmark_net_value"].replace(0.0, np.nan)
    data["excess_net_value"] = data["account_net_value"] / benchmark_nav
    relative_return = data["excess_net_value"].pct_change(fill_method=None)
    data["excess_daily_return"] = relative_return.where(
        data["benchmark_return_valid"]
    )
    data.loc[
        data["benchmark_return_valid"] & relative_return.isna(),
        "excess_daily_return",
    ] = 0.0
    data["invested_excess_net_value"] = data["invested_capital_net_value"] / benchmark_nav
    invested_relative_return = data["invested_excess_net_value"].pct_change(fill_method=None)
    data["invested_excess_daily_return"] = invested_relative_return.where(
        data["benchmark_return_valid"]
    )
    data.loc[
        data["benchmark_return_valid"] & invested_relative_return.isna(),
        "invested_excess_daily_return",
    ] = 0.0
    data["valid_invested_excess_net_value"] = data["valid_invested_capital_net_value"] / benchmark_nav
    valid_invested_relative_return = data[
        "valid_invested_excess_net_value"
    ].pct_change(fill_method=None)
    data["valid_invested_excess_daily_return"] = valid_invested_relative_return.where(
        data["benchmark_return_valid"]
    )
    data.loc[
        data["benchmark_return_valid"] & valid_invested_relative_return.isna(),
        "valid_invested_excess_daily_return",
    ] = 0.0
    data["holding_portfolio_excess_net_value"] = data["holding_portfolio_net_value"] / benchmark_nav
    holding_relative_return = data["holding_portfolio_excess_net_value"].pct_change(
        fill_method=None
    )
    data["holding_portfolio_excess_daily_return"] = holding_relative_return.where(
        data["benchmark_return_valid"]
    )
    data.loc[
        data["benchmark_return_valid"] & holding_relative_return.isna(),
        "holding_portfolio_excess_daily_return",
    ] = 0.0
    data["active_return_difference_daily"] = (
        data["account_daily_return"] - data["benchmark_daily_return"]
    )
    data["active_return_difference_chain_net_value"] = (
        1.0 + data["active_return_difference_daily"]
    ).cumprod()
    data["benchmark_relative_return_method"] = "geometric_nav_ratio"
    data["holding_portfolio_return_method"] = "exposure_scaled_account_return_approximation"

    beta, upside_capture, downside_capture = _benchmark_capture_stats(
        account_return=data["account_daily_return"],
        benchmark_return=data["benchmark_daily_return"],
    )
    data["benchmark_beta_full_period"] = beta
    data["upside_capture_full_period"] = upside_capture
    data["downside_capture_full_period"] = downside_capture

    data["holding_count_bucket"] = pd.cut(
        pd.to_numeric(data.get("holding_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0),
        bins=[-0.1, 0.1, 3, 8, 15, math.inf],
        labels=["zero", "1-3", "4-8", "9-15", "16+"],
    ).astype(str)
    data["exposure_bucket"] = pd.cut(
        data["actual_exposure"].fillna(0.0),
        bins=[-0.001, 0.10, 0.25, 0.50, 0.75, math.inf],
        labels=["0-10%", "10-25%", "25-50%", "50-75%", "75%+"],
    ).astype(str)

    factor_state = build_factor_state_ledger(factor_weight_ledger)
    if not factor_state.empty:
        data = data.merge(factor_state, on="date", how="left")
    else:
        data["factor_entropy"] = np.nan
        data["factor_hhi"] = np.nan
        data["factor_top1_share"] = np.nan
        data["factor_top3_share"] = np.nan
        data["dominant_factor"] = ""
        data["dominant_factor_module"] = ""
    data["factor_entropy_bucket"] = pd.cut(
        pd.to_numeric(data["factor_entropy"], errors="coerce"),
        bins=[-0.001, 0.45, 0.70, 0.88, 1.001],
        labels=["concentrated", "tilted", "diversified", "flat/noisy"],
    ).astype(str)
    return data


def build_bucket_attribution(attribution: pd.DataFrame) -> pd.DataFrame:
    """Summarize whether exposure, holding count, and factor concentration explain returns."""
    if attribution is None or attribution.empty:
        return pd.DataFrame()
    rows = []
    for dimension in ["holding_count_bucket", "exposure_bucket", "factor_entropy_bucket", "dominant_factor_module"]:
        if dimension not in attribution.columns:
            continue
        for bucket, group in attribution.groupby(dimension, dropna=False):
            if group.empty:
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "bucket": str(bucket),
                    "days": int(len(group)),
                    "avg_actual_exposure": _safe_mean(group.get("actual_exposure")),
                    "account_total_return": _compound(group.get("account_daily_return")),
                    "invested_capital_total_return": _compound(group.get("exposure_adjusted_daily_return")),
                    "valid_invested_capital_total_return": _compound(group.get("valid_invested_capital_daily_return")),
                    "holding_portfolio_total_return": _compound(group.get("holding_portfolio_daily_return")),
                    "benchmark_total_return": _compound(group.get("benchmark_daily_return")),
                    "excess_total_return": _compound(group.get("excess_daily_return")),
                    "invested_excess_total_return": _compound(group.get("invested_excess_daily_return")),
                    "valid_invested_excess_total_return": _compound(group.get("valid_invested_excess_daily_return")),
                    "holding_portfolio_excess_total_return": _compound(group.get("holding_portfolio_excess_daily_return")),
                    "account_win_rate": _win_rate(group.get("account_daily_return")),
                    "excess_win_rate": _win_rate(group.get("excess_daily_return")),
                    "valid_invested_observed_days": int(pd.Series(group.get("valid_invested_capital_observed", [])).fillna(False).astype(bool).sum()),
                    "avg_factor_entropy": _safe_mean(group.get("factor_entropy")),
                    "avg_factor_top1_share": _safe_mean(group.get("factor_top1_share")),
                }
            )
    return pd.DataFrame(rows)


def build_factor_state_ledger(factor_weight_ledger: pd.DataFrame | None) -> pd.DataFrame:
    if factor_weight_ledger is None or factor_weight_ledger.empty:
        return pd.DataFrame()
    data = factor_weight_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["weight_share"] = pd.to_numeric(data["weight_share"], errors="coerce").clip(lower=0.0)
    data = data.dropna(subset=["date", "model_name", "weight_share"])
    if data.empty:
        return pd.DataFrame()
    rows = []
    for date, group in data.groupby("date", sort=True):
        shares = group["weight_share"].to_numpy(dtype=float)
        total = float(np.nansum(shares))
        if total <= 0:
            continue
        shares = shares / total
        positive = shares[shares > 0]
        entropy = -float(np.sum(positive * np.log(positive))) / math.log(len(shares)) if len(shares) > 1 else 0.0
        sorted_group = group.assign(_share=shares).sort_values("_share", ascending=False)
        top = sorted_group.iloc[0]
        rows.append(
            {
                "date": pd.Timestamp(date),
                "factor_entropy": entropy,
                "factor_hhi": float(np.sum(np.square(shares))),
                "factor_top1_share": float(sorted_group["_share"].iloc[0]),
                "factor_top3_share": float(sorted_group["_share"].head(3).sum()),
                "dominant_factor": str(top["model_name"]),
                "dominant_factor_module": str(top.get("factor_module", "unknown")),
            }
        )
    return pd.DataFrame(rows)


def factor_module(model_name: str) -> str:
    name = str(model_name).lower()
    if name.startswith("candidate_grid_rank_ratio__"):
        return "grid_ratio"
    if name.startswith("candidate_grid_rank_spread__"):
        return "grid_rank_spread"
    if name.startswith("candidate_grid_rank_product__"):
        return "grid_rank_interaction"
    if name.startswith("candidate_grid_rank_gate_"):
        return "grid_conditional"
    if name.startswith("candidate_grid_rank_mean__"):
        return "grid_rank_blend"
    if name.startswith("candidate_grid_base_rank__size"):
        return "grid_size"
    if name.startswith("candidate_grid_base_rank__rev"):
        return "grid_reversal"
    if name.startswith("candidate_grid_base_rank__vol") or name.startswith("candidate_grid_base_rank__downvol"):
        return "grid_volatility"
    if name.startswith("candidate_grid_base_rank__drawdown"):
        return "grid_risk"
    if name.startswith("candidate_size_"):
        return "size"
    if name.startswith("candidate_idiosyncratic_vol") or name.startswith("candidate_max_drawdown"):
        return "risk"
    if name.startswith("candidate_volatility") or name.startswith("candidate_downside_volatility"):
        return "volatility"
    if "orderflow" in name or "volume" in name or "close_strength" in name:
        return "flow_close"
    if "limit" in name or "event" in name or "holiday" in name:
        return "event_limit"
    if "momentum" in name or "macd" in name or "breakout" in name or "ma_" in name:
        return "trend"
    if "reversal" in name or "decline" in name or "oversold" in name or "pullback" in name:
        return "reversal_pullback"
    if "lowvol" in name or "low_vol" in name:
        return "defensive"
    if "grid" in name:
        return "range_grid"
    return "other"


def build_top_pool_benchmark_series(
    feature_data: pd.DataFrame,
    *,
    top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> pd.DataFrame:
    """Build a prior-period fixed-N, top-liquidity opportunity-set benchmark.

    Membership is chosen using information available at T and becomes effective
    on T+1.  Equal weights are set only at the requested rebalance; weights then
    drift with member returns. Missing T+1 prices are marked at zero return, not
    removed before ranking, preventing future-availability selection leakage.
    """
    columns = [
        "date", "benchmark_net_value", "benchmark_daily_return",
        "benchmark_gross_daily_return", "benchmark_gross_net_value",
        "benchmark_transaction_cost_rate", "benchmark_return_valid",
        "benchmark_member_count", "benchmark_return_coverage",
        "benchmark_rebalanced", "benchmark_turnover", "benchmark_id",
        "benchmark_constituent_rule", "benchmark_weighting", "benchmark_return_basis",
    ]
    if feature_data is None or feature_data.empty:
        return pd.DataFrame(columns=columns)
    requested_top_n = int(top_n)
    if requested_top_n <= 0:
        raise ValueError("benchmark top_n must be positive")
    rebalance_mode = str(rebalance or "monthly").strip().lower()
    if rebalance_mode not in {"daily", "weekly", "monthly"}:
        raise ValueError("benchmark rebalance must be daily, weekly, or monthly")
    close_col = "close_nominal" if "close_nominal" in feature_data.columns else "close"
    if close_col not in feature_data.columns:
        return pd.DataFrame(columns=columns)
    liquidity_columns = [column for column in ("amount_ma20", "amount") if column in feature_data.columns]
    if not liquidity_columns:
        return pd.DataFrame(columns=columns)

    required = ["date", "symbol", close_col, *liquidity_columns]
    required.extend(column for column in ("instrument_type", "is_trading") if column in feature_data.columns)
    data = feature_data[required].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    for column in liquidity_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if "amount" in data.columns:
        rolling_amount = data.sort_values(["symbol", "date"]).groupby("symbol", sort=False)["amount"].transform(
            lambda values: values.rolling(20, min_periods=1).mean()
        )
    else:
        rolling_amount = pd.Series(float("nan"), index=data.index)
    data["_benchmark_liquidity"] = (
        data["amount_ma20"].combine_first(rolling_amount)
        if "amount_ma20" in data.columns else rolling_amount
    )
    if "instrument_type" in data.columns:
        data = data[data["instrument_type"].astype(str).eq("stock")]
    data = data.dropna(subset=["date", "symbol", close_col]).drop_duplicates(
        ["date", "symbol"], keep="last"
    ).sort_values(["date", "symbol"])
    if data.empty:
        return pd.DataFrame(columns=columns)

    close_pivot = data.pivot_table(index="date", columns="symbol", values=close_col, aggfunc="last").sort_index()
    liquidity_pivot = data.pivot_table(index="date", columns="symbol", values="_benchmark_liquidity", aggfunc="last").reindex(close_pivot.index)
    trading_pivot = None
    if "is_trading" in data.columns:
        trading_pivot = data.pivot_table(index="date", columns="symbol", values="is_trading", aggfunc="last").reindex(close_pivot.index)
    if len(close_pivot.index) < 2:
        return pd.DataFrame(columns=columns)

    rows = [
        {
            "date": pd.Timestamp(close_pivot.index[0]),
            "benchmark_daily_return": 0.0,
            "benchmark_member_count": 0,
            "benchmark_return_coverage": 0.0,
            "benchmark_rebalanced": False,
            "benchmark_turnover": 0.0,
        }
    ]
    weights = pd.Series(dtype=float)
    for idx in range(len(close_pivot.index) - 1):
        current_date = close_pivot.index[idx]
        next_date = close_pivot.index[idx + 1]
        should_rebalance = weights.empty or _benchmark_rebalance_due(
            current_date, next_date, rebalance_mode
        )
        turnover = 0.0
        initial_rebalance = weights.empty
        if should_rebalance:
            liquidity = pd.to_numeric(liquidity_pivot.loc[current_date], errors="coerce")
            current_close = pd.to_numeric(close_pivot.loc[current_date], errors="coerce")
            eligible = liquidity.notna() & liquidity.gt(0.0) & current_close.notna() & current_close.gt(0.0)
            if trading_pivot is not None:
                trading_known = trading_pivot.loc[current_date].astype("boolean").fillna(False)
                eligible &= trading_known.astype(bool)
            selected = liquidity[eligible].sort_values(ascending=False).head(requested_top_n).index
            new_weights = pd.Series(1.0 / len(selected), index=selected, dtype=float) if len(selected) else pd.Series(dtype=float)
            union = weights.index.union(new_weights.index)
            turnover = float(
                0.5 * (
                    weights.reindex(union, fill_value=0.0)
                    - new_weights.reindex(union, fill_value=0.0)
                ).abs().sum()
            ) if not weights.empty else 1.0 if not new_weights.empty else 0.0
            weights = new_weights

        if weights.empty:
            gross_daily_return = 0.0
            member_count = 0
            coverage = 0.0
        else:
            current_prices = pd.to_numeric(close_pivot.loc[current_date].reindex(weights.index), errors="coerce")
            next_prices = pd.to_numeric(close_pivot.loc[next_date].reindex(weights.index), errors="coerce")
            observed = current_prices.gt(0.0) & next_prices.notna() & next_prices.gt(0.0)
            member_returns = (next_prices / current_prices - 1.0).replace([np.inf, -np.inf], np.nan)
            member_returns = member_returns.where(observed, 0.0).fillna(0.0)
            gross_daily_return = float((weights * member_returns).sum())
            member_count = int(len(weights))
            coverage = float(observed.mean()) if member_count else 0.0
            grown = weights * (1.0 + member_returns)
            total = float(grown.sum())
            weights = grown / total if total > 0.0 else weights
        buy_rate = float(COMMISSION_RATE + SLIPPAGE_RATE + TRANSFER_FEE_RATE)
        sell_rate = buy_rate + float(stamp_duty_rate_for(next_date, fallback_rate=STAMP_DUTY_RATE))
        transaction_cost_rate = (
            float(turnover) * (buy_rate if initial_rebalance else buy_rate + sell_rate)
            if should_rebalance else 0.0
        )
        return_valid = bool(member_count == 0 or coverage >= 1.0 - 1e-12)
        rows.append(
            {
                "date": pd.Timestamp(next_date),
                "benchmark_gross_daily_return": gross_daily_return,
                "benchmark_daily_return": gross_daily_return - transaction_cost_rate,
                "benchmark_transaction_cost_rate": transaction_cost_rate,
                "benchmark_return_valid": return_valid,
                "benchmark_member_count": int(member_count),
                "benchmark_return_coverage": coverage,
                "benchmark_rebalanced": bool(should_rebalance),
                "benchmark_turnover": turnover,
            }
        )

    result = pd.DataFrame(rows).sort_values("date")
    result["benchmark_gross_daily_return"] = pd.to_numeric(
        result.get("benchmark_gross_daily_return"), errors="coerce"
    ).fillna(0.0)
    result["benchmark_gross_net_value"] = (1.0 + result["benchmark_gross_daily_return"]).cumprod()
    result["benchmark_transaction_cost_rate"] = pd.to_numeric(
        result.get("benchmark_transaction_cost_rate"), errors="coerce"
    ).fillna(0.0)
    result["benchmark_return_valid"] = result.get(
        "benchmark_return_valid", pd.Series(False, index=result.index, dtype="boolean")
    ).astype("boolean").fillna(False).astype(bool)
    result["benchmark_daily_return"] = pd.to_numeric(result["benchmark_daily_return"], errors="coerce").fillna(0.0)
    result["benchmark_net_value"] = (1.0 + result["benchmark_daily_return"]).cumprod()
    result["benchmark_id"] = f"{TOP_POOL_BENCHMARK_ID_PREFIX}_{requested_top_n}_equal_weight_{rebalance_mode}"
    result["benchmark_constituent_rule"] = "prior_period_top_liquidity_fixed_n"
    result["benchmark_weighting"] = "equal_weight_research_fallback"
    result["benchmark_return_basis"] = (
        "net_proportional_cost;missing_price_zero_for_nav_display;"
        "invalid_dates_excluded_from_attribution"
    )
    return result[columns]


def build_top_strength_benchmark_series(
    feature_data: pd.DataFrame,
    *,
    top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> pd.DataFrame:
    """Compatibility alias for the retired percentage-based benchmark API."""
    return build_top_pool_benchmark_series(feature_data, top_n=top_n, rebalance=rebalance)


def build_top_pool_benchmark_sensitivity(
    feature_data: pd.DataFrame,
    *,
    top_n_values=(50, 100, 300),
    rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
    evaluation_start=None,
    evaluation_end=None,
) -> pd.DataFrame:
    """Report alternative fixed-N definitions without selecting the ex-post winner."""
    rows = []
    for top_n in tuple(dict.fromkeys(int(value) for value in top_n_values)):
        series = build_top_pool_benchmark_series(feature_data, top_n=top_n, rebalance=rebalance)
        if series.empty:
            continue
        evaluation = series.copy()
        evaluation["date"] = pd.to_datetime(evaluation["date"], errors="coerce")
        if evaluation_start is not None:
            evaluation = evaluation[evaluation["date"] >= pd.Timestamp(evaluation_start)]
        if evaluation_end is not None:
            evaluation = evaluation[evaluation["date"] <= pd.Timestamp(evaluation_end)]
        if evaluation.empty:
            continue
        daily = pd.to_numeric(evaluation["benchmark_daily_return"], errors="coerce").dropna()
        # The account NAV is initialized on evaluation_start; the benchmark
        # must share that same zero-return origin instead of importing the
        # preload-to-start return into a bounded comparison.
        if not daily.empty:
            daily.iloc[0] = 0.0
        nav = (1.0 + daily).cumprod()
        active = evaluation[pd.to_numeric(evaluation["benchmark_member_count"], errors="coerce").gt(0)]
        rows.append(
            {
                "benchmark_id": str(series["benchmark_id"].iloc[-1]),
                "top_n": int(top_n),
                "rebalance": str(rebalance),
                "observed_days": int(len(daily)),
                "total_return": float(nav.iloc[-1] - 1.0) if len(nav) else np.nan,
                "annualized_volatility": float(daily.std(ddof=1) * math.sqrt(252.0)) if len(daily) > 1 else np.nan,
                "average_member_count": float(pd.to_numeric(active["benchmark_member_count"], errors="coerce").mean()) if not active.empty else 0.0,
                "average_return_coverage": float(pd.to_numeric(active["benchmark_return_coverage"], errors="coerce").mean()) if not active.empty else 0.0,
                "average_daily_turnover": float(pd.to_numeric(evaluation["benchmark_turnover"], errors="coerce").mean()),
                "rebalance_count": int(evaluation["benchmark_rebalanced"].fillna(False).astype(bool).sum()),
                "evaluation_start": pd.Timestamp(evaluation["date"].min()),
                "evaluation_end": pd.Timestamp(evaluation["date"].max()),
                "selection_policy": "pre_registered_only_do_not_choose_best_ex_post",
            }
        )
    return pd.DataFrame(rows)


def _benchmark_rebalance_due(current_date, next_date, mode: str) -> bool:
    current = pd.Timestamp(current_date)
    following = pd.Timestamp(next_date)
    if mode == "daily":
        return True
    if mode == "weekly":
        return current.to_period("W-FRI") != following.to_period("W-FRI")
    return current.to_period("M") != following.to_period("M")


def _cross_sectional_strength_score(data: pd.DataFrame, strength_columns: list[str]) -> pd.Series:
    ranked = []
    for column in strength_columns:
        values = pd.to_numeric(data[column], errors="coerce")
        if column == "volatility_20":
            values = -values
        ranked.append(values.groupby(data["date"]).rank(pct=True, method="average"))
    if not ranked:
        return pd.Series(np.nan, index=data.index)
    return pd.concat(ranked, axis=1).mean(axis=1, skipna=True)


def _benchmark_series(feature_data: pd.DataFrame, benchmark_symbol: str | None, *, top_n: int, rebalance: str) -> pd.DataFrame:
    top_pool = build_top_pool_benchmark_series(feature_data, top_n=top_n, rebalance=rebalance)
    if not top_pool.empty:
        return top_pool
    if feature_data is None or feature_data.empty or not benchmark_symbol:
        return pd.DataFrame(columns=["date", "benchmark_net_value", "benchmark_daily_return"])
    data = feature_data.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    close_col = "close_nominal" if "close_nominal" in data.columns else "close"
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    data = data[(data["symbol"].astype(str) == str(benchmark_symbol))].dropna(subset=["date", close_col]).sort_values("date")
    if data.empty:
        return pd.DataFrame(columns=["date", "benchmark_net_value", "benchmark_daily_return"])
    initial = _first_positive(data[close_col])
    data["benchmark_net_value"] = data[close_col] / initial if initial > 0 else np.nan
    data["benchmark_daily_return"] = data["benchmark_net_value"].pct_change(fill_method=None).fillna(0.0)
    return data[["date", "benchmark_net_value", "benchmark_daily_return"]]


def _first_positive(series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values > 0]
    return float(values.iloc[0]) if not values.empty else 1.0


def _safe_mean(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float(values.mean()) if not values.empty else 0.0


def _compound(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float((1.0 + values).prod() - 1.0) if not values.empty else 0.0


def _win_rate(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float((values > 0).mean()) if not values.empty else 0.0


def _benchmark_capture_stats(*, account_return: pd.Series, benchmark_return: pd.Series) -> tuple[float, float, float]:
    account = pd.to_numeric(account_return, errors="coerce")
    benchmark = pd.to_numeric(benchmark_return, errors="coerce")
    aligned = pd.DataFrame({"account": account, "benchmark": benchmark}).dropna()
    if aligned.empty:
        return 0.0, 0.0, 0.0
    variance = float(aligned["benchmark"].var(ddof=0))
    beta = float(aligned["account"].cov(aligned["benchmark"]) / variance) if variance > 1e-12 else 0.0
    up = aligned[aligned["benchmark"] > 0.0]
    down = aligned[aligned["benchmark"] < 0.0]
    upside = float(up["account"].mean() / up["benchmark"].mean()) if not up.empty and abs(float(up["benchmark"].mean())) > 1e-12 else 0.0
    downside = float(down["account"].mean() / down["benchmark"].mean()) if not down.empty and abs(float(down["benchmark"].mean())) > 1e-12 else 0.0
    return beta, upside, downside
