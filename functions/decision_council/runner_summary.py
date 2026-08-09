"""Summary and diagnostics builders for governance backtest outputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import *  # noqa: F403 - summary preserves the runner's config-driven formulas.


def _contiguous_true_lengths(mask: pd.Series) -> list[int]:
    lengths: list[int] = []
    current = 0
    for value in mask.fillna(False).astype(bool).tolist():
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _safe_numeric_mean(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.mean())


def _safe_last(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.iloc[-1])


def _safe_numeric_max(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.max())


def _risk_gate_max_contribution(risk_contribution: pd.DataFrame) -> float:
    if risk_contribution is None or risk_contribution.empty:
        return 0.0
    data = risk_contribution.copy()
    if "risk_gate_eligible" in data.columns:
        eligible = data["risk_gate_eligible"].fillna(False).astype(bool)
        if eligible.any():
            data = data[eligible].copy()
    metric_col = (
        "positive_risk_contribution_share"
        if "positive_risk_contribution_share" in data.columns
        else "risk_contribution_share"
    )
    return _safe_numeric_max(data.get(metric_col), default=0.0)


def _recent_actual_target_ratio(exposure_rows: list[dict], *, window: int = 20) -> float:
    if not exposure_rows:
        return pd.NA
    data = pd.DataFrame(exposure_rows).tail(int(window)).copy()
    if not {"actual_exposure", "target_exposure"}.issubset(data.columns):
        return pd.NA
    actual = pd.to_numeric(data["actual_exposure"], errors="coerce")
    target = pd.to_numeric(data["target_exposure"], errors="coerce")
    ratio = (actual / target.replace(0.0, pd.NA)).dropna()
    if ratio.empty:
        return pd.NA
    return float(ratio.median())


def _ideal_vs_executed(entry_audit: pd.DataFrame, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame()
    data = entry_audit.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series("", index=data.index)).astype(str)
    buys = pd.DataFrame()
    if execution_ledger is not None and not execution_ledger.empty:
        buys = execution_ledger.copy()
        buys["trade_date"] = pd.to_datetime(buys.get("trade_date"), errors="coerce")
        buys["symbol"] = buys.get("symbol", pd.Series("", index=buys.index)).astype(str)
        buys = buys[
            buys.get("side", pd.Series("", index=buys.index)).astype(str).str.lower().eq("buy")
            & pd.to_numeric(buys.get("executed_shares", pd.Series(0.0, index=buys.index)), errors="coerce").fillna(0.0).gt(0.0)
        ].copy()
        if not buys.empty:
            buys = buys.groupby(["trade_date", "symbol"], as_index=False).agg(
                executed_buy=("executed_shares", "sum"),
                executed_notional=("trade_notional", "sum"),
                execution_status=("execution_status", "last"),
                buy_reason=("reason", "last"),
            )
    if buys.empty:
        data["executed_buy"] = 0.0
        data["executed_notional"] = 0.0
        data["execution_status"] = ""
        data["buy_reason"] = ""
    else:
        data = data.merge(
            buys,
            left_on=["date", "symbol"],
            right_on=["trade_date", "symbol"],
            how="left",
        )
        data["executed_buy"] = pd.to_numeric(data.get("executed_buy"), errors="coerce").fillna(0.0)
        data["executed_notional"] = pd.to_numeric(data.get("executed_notional"), errors="coerce").fillna(0.0)
        data["execution_status"] = data.get("execution_status", pd.Series("", index=data.index)).fillna("")
        data["buy_reason"] = data.get("buy_reason", pd.Series("", index=data.index)).fillna("")
        if "trade_date" in data.columns:
            data = data.drop(columns=["trade_date"])
    data["executed_flag"] = pd.to_numeric(data["executed_buy"], errors="coerce").fillna(0.0).gt(0.0)
    preferred = [
        "date",
        "symbol",
        "executed_flag",
        "executed_buy",
        "executed_notional",
        "execution_status",
        "buy_reason",
        "retail_executable",
        "retail_block_reason",
        "retail_executable_score",
        "entry_confirmed",
        "entry_alpha_score",
        "entry_timing_score",
        "entry_liquidity_score",
        "entry_matrix_score",
        "alpha_quality_score",
        "surge_capture_score",
        "follow_through_score",
        "exhaustion_score",
        "entry_success_probability",
        "entry_size_tier",
        "planned_entry_lots",
        "downtrend_decay_score",
        "post_entry_failure_score",
        "primary_score",
        "alpha_percentile",
        "expected_return_5d",
        "one_lot_cash_required",
        "one_lot_account_weight",
        "retail_one_lot_position_cap",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
    ]
    columns = [column for column in preferred if column in data.columns]
    extras = [column for column in data.columns if column not in columns]
    return data[columns + extras].sort_values(
        ["date", "executed_flag", "retail_executable_score", "symbol"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)


def _entry_timing_diagnostics(entry_audit: pd.DataFrame, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "symbol",
        "entry_matrix_score",
        "alpha_quality_score",
        "entry_timing_score",
        "surge_capture_score",
        "follow_through_score",
        "exhaustion_score",
        "downtrend_decay_score",
        "post_entry_failure_score",
        "entry_size_tier",
        "planned_lots",
        "executed_lots",
        "empirical_distribution_score",
        "final_entry_score",
        "tail_risk_proxy",
        "trend_direction_score",
        "peak_decay_score",
        "profit_protection_pressure",
        "dynamic_giveback_limit",
        "future_loss_risk_score",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "forward_return_10d",
        "best_buy_after_entry_date",
        "best_buy_after_entry_gap",
        "worst_drawdown_after_entry",
        "entry_confirmed",
        "entry_block_reason",
        "position_state",
        "retail_executable",
        "retail_block_reason",
    ]
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame(columns=columns)
    data = entry_audit.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series("", index=data.index)).astype(str)
    data["planned_lots"] = pd.to_numeric(data.get("planned_entry_lots"), errors="coerce").fillna(0.0)
    if execution_ledger is None or execution_ledger.empty:
        data["executed_lots"] = 0.0
    else:
        executions = execution_ledger.copy()
        executions["trade_date"] = pd.to_datetime(executions.get("trade_date"), errors="coerce")
        executions["symbol"] = executions.get("symbol", pd.Series("", index=executions.index)).astype(str)
        side = executions.get("side", pd.Series("", index=executions.index)).astype(str).str.lower()
        executions = executions[side.eq("buy")].copy()
        if executions.empty:
            data["executed_lots"] = 0.0
        else:
            buys = (
                executions.groupby(["trade_date", "symbol"], as_index=False)
                .agg(executed_shares=("executed_shares", "sum"))
            )
            buys["executed_lots"] = pd.to_numeric(buys["executed_shares"], errors="coerce").fillna(0.0) / float(MIN_LOT_SIZE)
            data = data.merge(
                buys[["trade_date", "symbol", "executed_lots"]],
                left_on=["date", "symbol"],
                right_on=["trade_date", "symbol"],
                how="left",
            )
            data["executed_lots"] = pd.to_numeric(data.get("executed_lots"), errors="coerce").fillna(0.0)
            if "trade_date" in data.columns:
                data = data.drop(columns=["trade_date"])
    for column in columns:
        if column not in data.columns:
            data[column] = pd.NA
    return data[columns].sort_values(
        ["date", "executed_lots", "entry_matrix_score", "symbol"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)


def _pnl_by_sell_reason(trade_pairs: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "sell_reason",
        "closed_trade_count",
        "closed_trade_win_rate",
        "realized_pnl",
        "gross_profit",
        "gross_loss",
        "avg_win",
        "avg_loss",
        "payoff_ratio",
        "profit_factor",
    ]
    if trade_pairs is None or trade_pairs.empty:
        return pd.DataFrame(columns=columns)
    data = trade_pairs.copy()
    data["realized_pnl_amount"] = pd.to_numeric(data.get("realized_pnl_amount"), errors="coerce")
    reason_source = data.get("sell_reason", data.get("close_reason", pd.Series("", index=data.index)))
    data["sell_reason"] = reason_source.fillna("").astype(str).replace("", "unknown")
    data = data[data["realized_pnl_amount"].notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for reason, group in data.groupby("sell_reason", dropna=False):
        pnl = pd.to_numeric(group["realized_pnl_amount"], errors="coerce").dropna()
        wins = pnl[pnl > 0.0]
        losses = pnl[pnl < 0.0]
        gross_profit = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(losses.sum()) if len(losses) else 0.0
        avg_win = float(wins.mean()) if len(wins) else pd.NA
        avg_loss = float(losses.mean()) if len(losses) else pd.NA
        rows.append(
            {
                "sell_reason": str(reason),
                "closed_trade_count": int(len(pnl)),
                "closed_trade_win_rate": float((pnl > 0.0).mean()) if len(pnl) else pd.NA,
                "realized_pnl": float(pnl.sum()) if len(pnl) else 0.0,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "payoff_ratio": (
                    float(avg_win / abs(avg_loss))
                    if pd.notna(avg_win) and pd.notna(avg_loss) and abs(float(avg_loss)) > 1e-12
                    else pd.NA
                ),
                "profit_factor": (
                    float(gross_profit / abs(gross_loss))
                    if abs(gross_loss) > 1e-12
                    else pd.NA
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("realized_pnl", ascending=False)


def _future_loss_duration_audit(trade_pairs: pd.DataFrame, features: pd.DataFrame, *, horizon_days: int = 40) -> pd.DataFrame:
    columns = [
        "symbol",
        "entry_date",
        "exit_date",
        "sell_reason",
        "exit_price",
        "exit_net_price",
        "exit_shares",
        "realized_pnl_amount",
        "realized_pnl_pct",
        "future_5d_return_if_hold",
        "future_10d_return_if_hold",
        "future_20d_return_if_hold",
        "future_40d_return_if_hold",
        "future_low_after_exit",
        "future_low_date",
        "days_to_future_low",
        "loss_days_after_exit",
        "observed_future_days",
        "avoided_loss_to_future_low",
        "continued_loss_flag",
    ]
    if trade_pairs is None or trade_pairs.empty or features is None or features.empty:
        return pd.DataFrame(columns=columns)
    required = {"symbol", "entry_date", "exit_date", "sell_reason", "exit_price", "exit_shares"}
    if not required.issubset(trade_pairs.columns):
        return pd.DataFrame(columns=columns)
    price_col = "close_nominal" if "close_nominal" in features.columns else "close"
    if not {"date", "symbol", price_col}.issubset(features.columns):
        return pd.DataFrame(columns=columns)
    trade_symbols = set(trade_pairs["symbol"].dropna().astype(str).unique())
    if not trade_symbols:
        return pd.DataFrame(columns=columns)
    source_prices = features.loc[features["symbol"].astype(str).isin(trade_symbols), ["date", "symbol", price_col]]
    prices = source_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["symbol"] = prices["symbol"].astype(str)
    prices[price_col] = pd.to_numeric(prices[price_col], errors="coerce")
    prices = prices.dropna(subset=["date", "symbol", price_col]).sort_values(["symbol", "date"])
    prices_by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in prices.groupby("symbol", sort=False)
    }
    rows = []
    for _, trade in trade_pairs.iterrows():
        symbol = str(trade.get("symbol", ""))
        exit_date = pd.to_datetime(trade.get("exit_date"), errors="coerce")
        if not symbol or pd.isna(exit_date):
            continue
        exit_price = _safe_float(trade.get("exit_net_price"), default=_safe_float(trade.get("exit_price"), default=0.0))
        shares = _safe_float(trade.get("exit_shares"), default=0.0)
        if exit_price <= 0.0 or shares <= 0.0:
            continue
        symbol_prices = prices_by_symbol.get(symbol)
        if symbol_prices is None or symbol_prices.empty:
            continue
        start_pos = int(symbol_prices["date"].searchsorted(pd.Timestamp(exit_date), side="right"))
        path = symbol_prices.iloc[start_pos : start_pos + int(horizon_days)].copy()
        if path.empty:
            continue
        close = path[price_col].astype(float).reset_index(drop=True)
        dates = path["date"].reset_index(drop=True)
        returns = {}
        for horizon in (5, 10, 20, 40):
            if len(close) >= horizon:
                returns[horizon] = float(close.iloc[horizon - 1] / exit_price - 1.0)
            else:
                returns[horizon] = pd.NA
        low_idx = int(close.idxmin())
        low_price = float(close.iloc[low_idx])
        low_date = pd.Timestamp(dates.iloc[low_idx])
        loss_days = int((close < exit_price).sum())
        rows.append(
            {
                "symbol": symbol,
                "entry_date": trade.get("entry_date", pd.NaT),
                "exit_date": exit_date,
                "sell_reason": str(trade.get("sell_reason", "")),
                "exit_price": _safe_float(trade.get("exit_price"), default=exit_price),
                "exit_net_price": exit_price,
                "exit_shares": shares,
                "realized_pnl_amount": _safe_float(trade.get("realized_pnl_amount"), default=0.0),
                "realized_pnl_pct": _safe_float(trade.get("realized_pnl_pct"), default=0.0),
                "future_5d_return_if_hold": returns[5],
                "future_10d_return_if_hold": returns[10],
                "future_20d_return_if_hold": returns[20],
                "future_40d_return_if_hold": returns[40],
                "future_low_after_exit": low_price,
                "future_low_date": low_date,
                "days_to_future_low": int(low_idx + 1),
                "loss_days_after_exit": loss_days,
                "observed_future_days": int(len(close)),
                "avoided_loss_to_future_low": max((exit_price - low_price) * shares, 0.0),
                "continued_loss_flag": bool(loss_days >= min(10, len(close)) or low_price < exit_price * 0.95),
            }
        )
    return pd.DataFrame(rows, columns=columns)


CONTROL_AVOIDED_LOSS_REASONS = ("profit_hard_stop_exit", "hard_stop_exit", "alpha_collapse_consensus", "safety_deleveraging")


def _control_avoided_loss_ledger(execution_ledger: pd.DataFrame, features: pd.DataFrame, *, as_of=None) -> pd.DataFrame:
    columns = [
        "trade_date",
        "symbol",
        "sell_reason",
        "exit_price",
        "exit_net_price",
        "executed_shares",
        "horizon_days",
        "maturity_date",
        "window_low_date",
        "window_low_price",
        "window_end_date",
        "window_end_price",
        "avoided_loss_to_window_low",
        "avoided_loss_to_window_end",
        "signed_exit_benefit_to_window_low",
        "signed_exit_benefit_to_window_end",
        "counterfactual_window_observed_days",
        "counterfactual_note",
    ]
    if execution_ledger is None or execution_ledger.empty or features is None or features.empty:
        return pd.DataFrame(columns=columns)
    required = {"trade_date", "symbol", "side", "reason", "price", "executed_shares"}
    if not required.issubset(execution_ledger.columns):
        return pd.DataFrame(columns=columns)
    price_col = "trade_close" if "trade_close" in features.columns else "close_nominal" if "close_nominal" in features.columns else "close"
    if not {"date", "symbol", price_col}.issubset(features.columns):
        return pd.DataFrame(columns=columns)
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else None
    sells = execution_ledger.copy()
    sells["trade_date"] = pd.to_datetime(sells["trade_date"], errors="coerce")
    sells["side"] = sells["side"].astype(str).str.lower()
    sells["reason"] = sells["reason"].astype(str)
    sells["executed_shares"] = pd.to_numeric(sells["executed_shares"], errors="coerce").fillna(0.0)
    sells["price"] = pd.to_numeric(sells["price"], errors="coerce")
    sells["total_cost"] = pd.to_numeric(sells.get("total_cost", pd.Series(0.0, index=sells.index)), errors="coerce").fillna(0.0)
    sells = sells[
        sells["trade_date"].notna()
        & sells["side"].eq("sell")
        & sells["reason"].isin(CONTROL_AVOIDED_LOSS_REASONS)
        & sells["executed_shares"].gt(0.0)
        & sells["price"].gt(0.0)
    ].copy()
    if sells.empty:
        return pd.DataFrame(columns=columns)
    sell_symbols = set(sells["symbol"].dropna().astype(str).unique())
    if not sell_symbols:
        return pd.DataFrame(columns=columns)
    source_prices = features.loc[features["symbol"].astype(str).isin(sell_symbols), ["date", "symbol", price_col]]
    feature_prices = source_prices.copy()
    feature_prices["date"] = pd.to_datetime(feature_prices["date"], errors="coerce")
    feature_prices["symbol"] = feature_prices["symbol"].astype(str)
    feature_prices[price_col] = pd.to_numeric(feature_prices[price_col], errors="coerce")
    feature_prices = feature_prices.dropna(subset=["date", "symbol", price_col])
    feature_prices = feature_prices.sort_values(["symbol", "date"])
    prices_by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in feature_prices.groupby("symbol", sort=False)
    }
    rows = []
    horizon_days = int(GOVERNANCE_CONTROL_AVOIDED_LOSS_HORIZON_DAYS)
    for _, sell in sells.iterrows():
        symbol = str(sell["symbol"])
        trade_date = pd.Timestamp(sell["trade_date"])
        symbol_prices = prices_by_symbol.get(symbol)
        if symbol_prices is None or symbol_prices.empty:
            continue
        start_pos = int(symbol_prices["date"].searchsorted(trade_date, side="right"))
        path = symbol_prices.iloc[start_pos:].copy()
        if as_of_ts is not None:
            path = path[path["date"] <= as_of_ts]
        path = path.head(horizon_days)
        if path.empty:
            continue
        low_idx = path[price_col].idxmin()
        low_row = path.loc[low_idx]
        end_row = path.iloc[-1]
        shares = float(sell["executed_shares"])
        exit_net_price = float(sell["price"]) - float(sell.get("total_cost", 0.0)) / max(shares, 1e-12)
        window_low_price = float(low_row[price_col])
        window_end_price = float(end_row[price_col])
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "sell_reason": str(sell["reason"]),
                "exit_price": float(sell["price"]),
                "exit_net_price": exit_net_price,
                "executed_shares": shares,
                "horizon_days": horizon_days,
                "maturity_date": pd.Timestamp(end_row["date"]),
                "window_low_date": pd.Timestamp(low_row["date"]),
                "window_low_price": window_low_price,
                "window_end_date": pd.Timestamp(end_row["date"]),
                "window_end_price": window_end_price,
                "avoided_loss_to_window_low": max((exit_net_price - window_low_price) * shares, 0.0),
                "avoided_loss_to_window_end": max((exit_net_price - window_end_price) * shares, 0.0),
                "signed_exit_benefit_to_window_low": (exit_net_price - window_low_price) * shares,
                "signed_exit_benefit_to_window_end": (exit_net_price - window_end_price) * shares,
                "counterfactual_window_observed_days": int(len(path)),
                "counterfactual_note": "If the control sell had not happened, this is the extra mark-to-low/end loss avoided in the post-exit window.",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _control_avoided_loss_summary_frame(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "sell_reason",
        "control_exit_count",
        "avoided_loss_to_window_low",
        "avoided_loss_to_window_end",
        "avg_avoided_loss_to_window_low",
        "signed_exit_benefit_to_window_low",
        "signed_exit_benefit_to_window_end",
        "avg_observed_days",
    ]
    if ledger is None or ledger.empty:
        return pd.DataFrame(columns=columns)
    data = ledger.copy()
    data["avoided_loss_to_window_low"] = pd.to_numeric(data.get("avoided_loss_to_window_low"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_end"] = pd.to_numeric(data.get("avoided_loss_to_window_end"), errors="coerce").fillna(0.0)
    data["counterfactual_window_observed_days"] = pd.to_numeric(
        data.get("counterfactual_window_observed_days"), errors="coerce"
    ).fillna(0.0)
    data["signed_exit_benefit_to_window_low"] = pd.to_numeric(
        data.get("signed_exit_benefit_to_window_low"), errors="coerce"
    ).fillna(0.0)
    data["signed_exit_benefit_to_window_end"] = pd.to_numeric(
        data.get("signed_exit_benefit_to_window_end"), errors="coerce"
    ).fillna(0.0)
    rows = []
    for reason, group in data.groupby("sell_reason", dropna=False):
        count = int(len(group))
        low_sum = float(group["avoided_loss_to_window_low"].sum())
        rows.append(
            {
                "sell_reason": str(reason),
                "control_exit_count": count,
                "avoided_loss_to_window_low": low_sum,
                "avoided_loss_to_window_end": float(group["avoided_loss_to_window_end"].sum()),
                "avg_avoided_loss_to_window_low": low_sum / max(count, 1),
                "signed_exit_benefit_to_window_low": float(
                    group["signed_exit_benefit_to_window_low"].sum()
                ),
                "signed_exit_benefit_to_window_end": float(
                    group["signed_exit_benefit_to_window_end"].sum()
                ),
                "avg_observed_days": float(group["counterfactual_window_observed_days"].mean()) if count else pd.NA,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("avoided_loss_to_window_low", ascending=False)


def _control_avoided_loss_summary(execution_ledger: pd.DataFrame, features: pd.DataFrame, *, as_of=None) -> dict:
    return _control_avoided_loss_summary_from_frame(
        _control_avoided_loss_summary_frame(
            _control_avoided_loss_ledger(execution_ledger, features, as_of=as_of)
        )
    )


def _control_avoided_loss_summary_from_frame(summary: pd.DataFrame | None) -> dict:
    result = {
        "control_exit_count": 0,
        "avoided_loss_to_window_low": 0.0,
        "avoided_loss_to_window_end": 0.0,
        "profit_hard_stop_avoided_loss_to_window_low": 0.0,
        "hard_stop_avoided_loss_to_window_low": 0.0,
        "alpha_collapse_avoided_loss_to_window_low": 0.0,
        "safety_deleveraging_avoided_loss_to_window_low": 0.0,
    }
    if summary is None or summary.empty:
        return result
    data = summary.copy()
    data["sell_reason"] = data.get("sell_reason", pd.Series("", index=data.index)).astype(str)
    data["control_exit_count"] = pd.to_numeric(data.get("control_exit_count"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_low"] = pd.to_numeric(data.get("avoided_loss_to_window_low"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_end"] = pd.to_numeric(data.get("avoided_loss_to_window_end"), errors="coerce").fillna(0.0)
    result["control_exit_count"] = int(data["control_exit_count"].sum())
    result["avoided_loss_to_window_low"] = float(data["avoided_loss_to_window_low"].sum())
    result["avoided_loss_to_window_end"] = float(data["avoided_loss_to_window_end"].sum())
    for reason, key in (
        ("profit_hard_stop_exit", "profit_hard_stop_avoided_loss_to_window_low"),
        ("hard_stop_exit", "hard_stop_avoided_loss_to_window_low"),
        ("alpha_collapse_consensus", "alpha_collapse_avoided_loss_to_window_low"),
        ("safety_deleveraging", "safety_deleveraging_avoided_loss_to_window_low"),
    ):
        rows = data[data["sell_reason"].eq(reason)]
        result[key] = float(rows["avoided_loss_to_window_low"].sum()) if not rows.empty else 0.0
    result["hard_stop_avoided_loss_to_window_low"] += result["profit_hard_stop_avoided_loss_to_window_low"]
    return result


def _format_pnl_by_sell_reason(pnl_by_sell_reason: pd.DataFrame) -> str:
    if pnl_by_sell_reason is None or pnl_by_sell_reason.empty:
        return ""
    parts = []
    data = pnl_by_sell_reason.copy()
    data["realized_pnl"] = pd.to_numeric(data.get("realized_pnl"), errors="coerce")
    for _, row in data.sort_values("realized_pnl", ascending=False).head(8).iterrows():
        parts.append(f"{row.get('sell_reason')}:{float(row.get('realized_pnl', 0.0)):.2f}")
    return "|".join(parts)


def _validation_pass_ratio(validation: pd.DataFrame) -> float:
    if validation is None or validation.empty or "passed" not in validation.columns:
        return 0.0
    values = validation["passed"].fillna(False).astype(bool)
    return float(values.mean()) if len(values) else 0.0


def _validation_fail_count(validation: pd.DataFrame) -> int:
    if validation is None or validation.empty or "passed" not in validation.columns:
        return 0
    values = validation["passed"].fillna(False).astype(bool)
    return int((~values).sum())


def _research_gate_status(research_gate: pd.DataFrame) -> str:
    if research_gate is None or research_gate.empty or "overall_status" not in research_gate.columns:
        return "unknown"
    values = research_gate["overall_status"].dropna().astype(str)
    return values.iloc[-1] if not values.empty else "unknown"


def _research_gate_fail_count(research_gate: pd.DataFrame) -> int:
    if research_gate is None or research_gate.empty or "pass_flag" not in research_gate.columns:
        return 0
    passed = research_gate["pass_flag"].fillna(False).astype(bool)
    return int((~passed).sum())


def _latest_bool(values) -> bool:
    if values is None:
        return False
    series = pd.Series(values).dropna()
    if series.empty:
        return False
    return bool(series.iloc[-1])


def _last_text(data: pd.DataFrame, column: str, default: str = "") -> str:
    if data is None or data.empty or column not in data.columns:
        return str(default)
    values = data[column].dropna().astype(str)
    return str(values.iloc[-1]) if not values.empty else str(default)


def _safe_float(value, default=0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])


def _clip01(value) -> float:
    return min(max(_safe_float(value, default=0.0), 0.0), 1.0)


def _dynamic_giveback_limit(
    *,
    mfe: float,
    trend_direction_score: float,
    peak_decay_score: float,
    orderflow_decay_score: float,
) -> float:
    mfe = max(_safe_float(mfe, default=0.0), 0.0)
    if mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_3):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_3)
    elif mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_2):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_2)
    else:
        base = float(GOVERNANCE_PROFIT_GIVEBACK_1) + 0.05
    trend_decay_penalty = max(0.55 - _safe_float(trend_direction_score, default=0.50), 0.0) * 0.30
    peak_decay_penalty = _clip01(peak_decay_score) * 0.12
    orderflow_penalty = _clip01(orderflow_decay_score) * 0.08
    return min(max(base - trend_decay_penalty - peak_decay_penalty - orderflow_penalty, 0.18), 0.55)


def _governance_round_trip_cost_rate() -> float:
    return (
        2.0 * float(COMMISSION_RATE)
        + 2.0 * float(SLIPPAGE_RATE)
        + float(STAMP_DUTY_RATE)
        + 2.0 * float(TRANSFER_FEE_RATE)
    )


def _normalize_governance_control_mode(value) -> str:
    mode = str(value or "normal").strip().lower()
    aliases = {
        "default": "normal",
        "full": "normal",
        "factor": "factor_only",
        "factor_only_stop": "factor_only",
        "stop": "factor_only",
        "stop_mode": "factor_only",
        "paper": "paper_controls",
        "paper_control": "paper_controls",
        "safe_factor": "safe_factor_only",
        "safe_stop": "safe_factor_only",
        "scap": "aggressive_profit",
        "profit": "aggressive_profit",
    }
    mode = aliases.get(mode, mode)
    allowed = {"normal", "factor_only", "paper_controls", "safe_factor_only", "aggressive_profit"}
    if mode not in allowed:
        raise ValueError(f"Unknown governance_control_mode '{value}'. Available: {sorted(allowed)}")
    return mode


def _normalize_capital_usage_mode(value) -> str:
    mode = str(value or GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT).strip().lower()
    aliases = {
        "cash": "allow_cash",
        "allow": "allow_cash",
        "idle_cash": "allow_cash",
        "force": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "forced": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "full": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "deploy": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
    }
    mode = aliases.get(mode, mode)
    if mode not in {"allow_cash", GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY}:
        return GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT
    return mode


def _state_machine_entry_mask(candidates: pd.DataFrame) -> pd.Series:
    """Confirmed entry mask that also honors the alpha role-diversity gate."""
    if candidates is None or candidates.empty:
        return pd.Series(dtype=bool)
    confirmed = candidates.get("entry_confirmed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    if "state_machine_role_pass" not in candidates.columns:
        return confirmed
    role_pass = candidates["state_machine_role_pass"].fillna(False).astype(bool)
    return confirmed & role_pass


def _best_bucket(bucket_frame: pd.DataFrame, dimension: str, metric: str) -> str:
    if bucket_frame is None or bucket_frame.empty:
        return ""
    if not {"dimension", "bucket", metric}.issubset(bucket_frame.columns):
        return ""
    data = bucket_frame[bucket_frame["dimension"].astype(str).eq(dimension)].copy()
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.dropna(subset=[metric])
    if data.empty:
        return ""
    best = data.sort_values(metric, ascending=False).iloc[0]
    return f"{best['bucket']} ({float(best[metric]):.2%})"


def _calibration_ece(calibration: pd.DataFrame, *, horizon_days: int) -> float:
    if calibration is None or calibration.empty:
        return pd.NA
    required = {"horizon_days", "sample_count", "realized_win_rate", "predicted_p_mean"}
    if not required.issubset(calibration.columns):
        return pd.NA
    data = calibration[pd.to_numeric(calibration["horizon_days"], errors="coerce").eq(int(horizon_days))].copy()
    if data.empty:
        return pd.NA
    n = pd.to_numeric(data["sample_count"], errors="coerce").fillna(0.0)
    if float(n.sum()) <= 0:
        return pd.NA
    gap = (
        pd.to_numeric(data["realized_win_rate"], errors="coerce")
        - pd.to_numeric(data["predicted_p_mean"], errors="coerce")
    ).abs()
    return float((gap * n).sum() / n.sum())


def _calibration_best_wilson(calibration: pd.DataFrame, *, horizon_days: int) -> float:
    if calibration is None or calibration.empty:
        return pd.NA
    required = {"horizon_days", "sample_count", "wilson_lower_95"}
    if not required.issubset(calibration.columns):
        return pd.NA
    data = calibration[pd.to_numeric(calibration["horizon_days"], errors="coerce").eq(int(horizon_days))].copy()
    data["sample_count"] = pd.to_numeric(data["sample_count"], errors="coerce").fillna(0.0)
    data["wilson_lower_95"] = pd.to_numeric(data["wilson_lower_95"], errors="coerce")
    data = data[(data["sample_count"] >= 50) & data["wilson_lower_95"].notna()]
    if data.empty:
        return pd.NA
    return float(data["wilson_lower_95"].max())


def _payoff_metric(payoff: pd.DataFrame, *, horizon_days: int, side: str, metric: str) -> float:
    if payoff is None or payoff.empty or metric not in payoff.columns:
        return pd.NA
    data = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(int(horizon_days))
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq(str(side))
    ].copy()
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    weights = pd.to_numeric(data.loc[values.index, "sample_count"], errors="coerce").fillna(1.0)
    return float((values * weights).sum() / max(float(weights.sum()), 1e-12))


def _payoff_reason_metric(payoff: pd.DataFrame, *, horizon_days: int, side: str, reason: str, metric: str) -> float:
    if payoff is None or payoff.empty or metric not in payoff.columns:
        return pd.NA
    data = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(int(horizon_days))
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq(str(side))
        & payoff.get("reason", pd.Series(dtype=object)).astype(str).eq(str(reason))
    ].copy()
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    weights = pd.to_numeric(data.loc[values.index, "sample_count"], errors="coerce").fillna(1.0)
    return float((values * weights).sum() / max(float(weights.sum()), 1e-12))


def _rebound_metric(report: pd.DataFrame, *, diagnostic: str, metric: str) -> float:
    if report is None or report.empty or metric not in report.columns:
        return pd.NA
    data = report[report.get("diagnostic", pd.Series(dtype=object)).astype(str).eq(str(diagnostic))]
    if data.empty:
        return pd.NA
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    return float(values.iloc[-1])


def _safe_count_true(values) -> int:
    if values is None:
        return 0
    try:
        return int(pd.Series(values).fillna(False).astype(bool).sum())
    except Exception:
        return 0


def _rolling_beat_metric(report: pd.DataFrame, *, window_days: int, segment: str = "full") -> float:
    if report is None or report.empty or "account_beat_ratio" not in report.columns:
        return pd.NA
    data = report[
        pd.to_numeric(report.get("window_days"), errors="coerce").eq(int(window_days))
        & report.get("segment", pd.Series("full", index=report.index)).fillna("full").astype(str).eq(str(segment))
    ].copy()
    values = pd.to_numeric(data.get("account_beat_ratio"), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    return float(values.iloc[-1])


def _capacity_passed(capacity: pd.DataFrame, *, multiplier: float) -> bool:
    if capacity is None or capacity.empty or "capacity_passed" not in capacity.columns:
        return False
    data = capacity[pd.to_numeric(capacity.get("capital_multiplier"), errors="coerce").eq(float(multiplier))]
    if data.empty:
        return False
    return bool(data["capacity_passed"].astype(bool).iloc[-1])


def _factor_weight_explanation(*, activity_ema: float, avg_exposure_ema: float, zero_trade_warning: bool) -> str:
    if zero_trade_warning:
        return "warning: high weight with near-zero shadow exposure"
    if activity_ema < 0.20:
        return "penalized: low active shadow coverage"
    if avg_exposure_ema < 0.05:
        return "capped: low average shadow exposure"
    return "active shadow contribution"


def _factor_primary_role(model_name: str, module: str) -> str:
    name = str(model_name).lower()
    module = str(module).lower()
    if module == "defensive" or "lowvol" in name:
        return "risk_sizer"
    if module in {"event_limit"} or "limit" in name or "event" in name:
        return "event_risk_watch"
    if module in {"trend", "flow_close"}:
        return "entry_hold_sell_watch"
    if module in {"reversal_pullback", "range_grid"}:
        return "entry_only"
    return "entry_alpha"


def _top_value_counts(values, *, limit: int = 8) -> list[dict]:
    if values is None:
        return []
    series = pd.Series(values).fillna("unknown").astype(str)
    if series.empty:
        return []
    counts = series.value_counts(dropna=False).head(int(limit))
    total = max(float(len(series)), 1.0)
    return [
        {"name": str(name), "count": int(count), "share": float(count) / total}
        for name, count in counts.items()
    ]


def _aggregate_factor_modules(factor_weights: list[dict]) -> list[dict]:
    modules: dict[str, dict] = {}
    for row in factor_weights or []:
        module = str(row.get("factor_module", "unknown"))
        if module not in modules:
            modules[module] = {
                "factor_module": module,
                "weight": 0.0,
                "weight_share": 0.0,
                "factor_count": 0,
                "avg_predicted_return_5d": 0.0,
            }
        modules[module]["weight"] += float(row.get("weight", 0.0) or 0.0)
        modules[module]["weight_share"] += float(row.get("weight_share", 0.0) or 0.0)
        modules[module]["avg_predicted_return_5d"] += float(row.get("avg_predicted_return_5d", 0.0) or 0.0)
        modules[module]["factor_count"] += 1
    for row in modules.values():
        count = max(int(row["factor_count"]), 1)
        row["avg_predicted_return_5d"] = float(row["avg_predicted_return_5d"]) / count
    return sorted(modules.values(), key=lambda item: float(item.get("weight_share", 0.0)), reverse=True)


def _confirm_post_entry_failure(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=bool)
    return _post_entry_failure_score(candidates).ge(float(GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE))


def _post_entry_failure_score(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=float)
    watch = candidates.get("post_entry_failure_watch", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    unrealized = pd.to_numeric(candidates.get("position_unrealized_return", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(candidates.get("alpha_percentile", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    alpha_quality = pd.to_numeric(candidates.get("alpha_quality_score", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    entry_alpha_quality = pd.to_numeric(
        candidates.get("position_entry_alpha_quality_score", pd.Series(alpha_quality, index=candidates.index)),
        errors="coerce",
    ).fillna(alpha_quality)
    alpha_quality_drop = (entry_alpha_quality - alpha_quality).clip(lower=0.0, upper=1.0)
    ret5 = pd.to_numeric(candidates.get("ret_5", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    ret20 = pd.to_numeric(candidates.get("ret_20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    close_to_ma20 = pd.to_numeric(candidates.get("close_to_ma20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mfe = pd.to_numeric(candidates.get("position_mfe", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mae = pd.to_numeric(candidates.get("position_mae", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    downtrend_decay = pd.to_numeric(candidates.get("downtrend_decay_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    flow_raw = pd.to_numeric(candidates.get("entry_orderflow_confirm_count", pd.Series(float("nan"), index=candidates.index)), errors="coerce")
    flow_count = flow_raw.fillna(0.0)
    holding_days = pd.to_numeric(candidates.get("position_holding_days", pd.Series(0, index=candidates.index)), errors="coerce").fillna(0)
    alpha_collapse = (
        alpha.lt(0.45).astype(float) * 0.35
        + alpha_quality.lt(0.55).astype(float) * 0.25
        + (alpha_quality_drop / 0.12).clip(0.0, 1.0) * 0.40
    ).clip(0.0, 1.0)
    trend_weak = (
        ret5.lt(-0.02).astype(float) * 0.35
        + ret20.lt(-0.04).astype(float) * 0.35
        + close_to_ma20.lt(-0.03).astype(float) * 0.30
    ).clip(0.0, 1.0)
    orderflow_bad = flow_count.le(1).astype(float).where(flow_raw.notna(), 0.5)
    loss_bad = ((-unrealized - 0.015) / 0.055).clip(0.0, 1.0)
    poor_excursion = (
        mfe.lt(0.02).astype(float) * 0.45
        + ((-mae - 0.02) / 0.08).clip(0.0, 1.0) * 0.35
        + downtrend_decay.clip(0.0, 1.0) * 0.20
    ).clip(0.0, 1.0)
    stale_bad = ((holding_days - 6.0) / 14.0).clip(0.0, 1.0)
    score = (
        0.25 * loss_bad
        + 0.25 * alpha_collapse
        + 0.20 * poor_excursion
        + 0.15 * orderflow_bad
        + 0.15 * trend_weak
        + 0.05 * stale_bad
    ) / 1.05
    score = score.clip(0.0, 1.0)
    return score.where(watch | holding_days.ge(3), 0.0)


def build_shadow_factor_diagnostics(
    shadow_ledger: pd.DataFrame,
    *,
    reputation_ledger: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank per-alpha shadow portfolios when the expensive shadow mode is enabled."""
    if shadow_ledger is None or shadow_ledger.empty:
        return pd.DataFrame()
    required = {"model_name", "date", "nominal_nav", "actual_exposure"}
    if not required.issubset(shadow_ledger.columns):
        return pd.DataFrame()

    data = shadow_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["nominal_nav"] = pd.to_numeric(data["nominal_nav"], errors="coerce")
    data["actual_exposure"] = pd.to_numeric(data["actual_exposure"], errors="coerce").fillna(0.0)
    if "holding_count" in data.columns:
        data["holding_count"] = pd.to_numeric(data["holding_count"], errors="coerce").fillna(0.0)
    else:
        data["holding_count"] = 0.0
    data = data.dropna(subset=["date", "nominal_nav"])
    if data.empty:
        return pd.DataFrame()

    latest_reputation = pd.DataFrame()
    if reputation_ledger is not None and not reputation_ledger.empty and "model_name" in reputation_ledger.columns:
        reputation = reputation_ledger.copy()
        reputation["date"] = pd.to_datetime(reputation.get("date"), errors="coerce")
        latest_reputation = reputation.sort_values("date").groupby("model_name", as_index=False).tail(1)

    rows: list[dict] = []
    for model_name, group in data.sort_values("date").groupby("model_name"):
        nav = pd.to_numeric(group["nominal_nav"], errors="coerce").dropna()
        if nav.empty:
            continue
        initial_nav = float(nav.iloc[0])
        final_nav = float(nav.iloc[-1])
        if initial_nav <= 0:
            total_return = 0.0
        else:
            total_return = final_nav / initial_nav - 1.0
        peak = nav.cummax()
        drawdown = nav / peak.where(peak != 0.0) - 1.0
        max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
        trading_days = int(group["date"].nunique())
        active_mask = pd.to_numeric(group["actual_exposure"], errors="coerce").fillna(0.0) > 0.01
        active_days = int(active_mask.sum())
        avg_exposure = float(pd.to_numeric(group["actual_exposure"], errors="coerce").fillna(0.0).mean())
        avg_holding_count = float(pd.to_numeric(group["holding_count"], errors="coerce").fillna(0.0).mean())
        latest = (
            latest_reputation[latest_reputation["model_name"].astype(str).eq(str(model_name))].iloc[-1]
            if not latest_reputation.empty
            and latest_reputation["model_name"].astype(str).eq(str(model_name)).any()
            else pd.Series(dtype=object)
        )
        latest_active_weight = _safe_float(latest.get("active_reputation_weight", 1.0), 1.0)
        latest_candidate_weight = _safe_float(latest.get("candidate_weight", 1.0), 1.0)
        latest_score_ema = _safe_float(latest.get("score_ema", 0.0), 0.0)
        latest_activity_ema = _safe_float(latest.get("activity_ema", 0.0), 0.0)
        latest_coverage_ema = _safe_float(latest.get("coverage_ema", 0.0), 0.0)
        latest_avg_exposure_ema = _safe_float(latest.get("avg_exposure_ema", 0.0), 0.0)
        active_day_ratio = active_days / max(trading_days, 1)
        zero_trade_reward_flag = bool(
            active_days == 0
            and abs(total_return) <= 1e-10
            and latest_active_weight > 1.05
        )
        low_activity_high_weight_flag = bool(active_day_ratio < 0.05 and latest_active_weight > 1.20)
        rows.append(
            {
                "model_name": model_name,
                "trading_days": trading_days,
                "first_date": group["date"].min().strftime("%Y-%m-%d"),
                "last_date": group["date"].max().strftime("%Y-%m-%d"),
                "initial_nav": initial_nav,
                "final_nav": final_nav,
                "total_return": total_return,
                "max_drawdown": max_drawdown,
                "avg_actual_exposure": avg_exposure,
                "active_days": active_days,
                "active_day_ratio": active_day_ratio,
                "avg_holding_count": avg_holding_count,
                "latest_active_reputation_weight": latest_active_weight,
                "latest_candidate_weight": latest_candidate_weight,
                "latest_score_ema": latest_score_ema,
                "latest_activity_ema": latest_activity_ema,
                "latest_coverage_ema": latest_coverage_ema,
                "latest_avg_exposure_ema": latest_avg_exposure_ema,
                "zero_trade_reward_flag": zero_trade_reward_flag,
                "low_activity_high_weight_flag": low_activity_high_weight_flag,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["return_rank"] = result["total_return"].rank(ascending=False, method="min").astype(int)
    result["drawdown_rank"] = result["max_drawdown"].rank(ascending=False, method="min").astype(int)
    result["activity_rank"] = result["active_day_ratio"].rank(ascending=False, method="min").astype(int)
    return result.sort_values(
        ["zero_trade_reward_flag", "total_return", "active_day_ratio"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def render_shadow_factor_diagnostics_markdown(diagnostics: pd.DataFrame) -> str:
    if diagnostics is None or diagnostics.empty:
        return "# Governance Shadow Factor Diagnostics\n\nNo shadow portfolio rows were available.\n"
    display = diagnostics.copy()
    percent_columns = [
        "total_return",
        "max_drawdown",
        "avg_actual_exposure",
        "active_day_ratio",
        "latest_avg_exposure_ema",
    ]
    for column in percent_columns:
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").map(lambda value: f"{value:.2%}")
    for column in (
        "latest_active_reputation_weight",
        "latest_candidate_weight",
        "latest_score_ema",
        "latest_activity_ema",
        "latest_coverage_ema",
        "avg_holding_count",
    ):
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").map(lambda value: f"{value:.4f}")
    columns = [
        "return_rank",
        "model_name",
        "total_return",
        "max_drawdown",
        "avg_actual_exposure",
        "active_days",
        "active_day_ratio",
        "latest_active_reputation_weight",
        "zero_trade_reward_flag",
        "low_activity_high_weight_flag",
    ]
    columns = [column for column in columns if column in display.columns]
    zero_warnings = int(diagnostics.get("zero_trade_reward_flag", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    low_activity_warnings = int(diagnostics.get("low_activity_high_weight_flag", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    table_rows = [columns, ["---"] * len(columns)]
    for _, row in display[columns].iterrows():
        table_rows.append([str(row.get(column, "")) for column in columns])
    table_text = "\n".join("| " + " | ".join(row) + " |" for row in table_rows)
    lines = [
        "# Governance Shadow Factor Diagnostics",
        "",
        "This report is generated only when per-alpha shadow portfolios are enabled.",
        "",
        f"- Factors: {len(diagnostics)}",
        f"- Zero-trade high-weight warnings: {zero_warnings}",
        f"- Low-activity high-weight warnings: {low_activity_warnings}",
        "",
        table_text,
        "",
    ]
    return "\n".join(lines)


def build_governance_summary(
    runner,
    *,
    daily_result,
    execution_ledger,
    safety_ledger,
    constraint_ledger,
    attribution_ledger=None,
    bucket_attribution=None,
    quality_reports=None,
    trade_pair_summary=None,
    pnl_by_sell_reason=None,
    control_avoided_loss_summary=None,
):
    if daily_result.empty:
        return pd.DataFrame(
            [
                {
                    "strategy": runner.governance_variant,
                    "strategy_source": "governance",
                    "weighting_mode": "dynamic_governance",
                }
            ]
        )
    data = daily_result.copy()
    safety = safety_ledger.copy()
    execution = execution_ledger.copy()
    constraint = constraint_ledger.copy()
    exposure_cap = pd.to_numeric(safety.get("exposure_cap", pd.Series(dtype=float)), errors="coerce")
    freeze_mask = exposure_cap.fillna(1.0) <= 0.0
    deleverage_mask = exposure_cap.fillna(1.0) < 1.0
    confirmed_crisis_mask = safety.get("risk_level", pd.Series(dtype=object)).astype(str).eq("crisis")
    confirmed_high_mask = safety.get("risk_level", pd.Series(dtype=object)).astype(str).eq("high")
    actual_forced_sell_days = int(
        execution.loc[
            execution.get("reason", pd.Series(dtype=object)).astype(str).eq("safety_deleveraging"),
            "trade_date" if "trade_date" in execution.columns else "execution_date",
        ].nunique()
    ) if not execution.empty and "reason" in execution.columns else 0
    participation_rate = pd.to_numeric(execution.get("participation_rate", pd.Series(dtype=float)), errors="coerce")
    capacity_passed = pd.to_numeric(execution.get("capacity_passed", pd.Series(dtype=float)), errors="coerce")
    turnover_budget = pd.to_numeric(constraint.get("normal_turnover_weight", pd.Series(dtype=float)), errors="coerce")
    target_exposure = pd.to_numeric(data.get("target_exposure", pd.Series(dtype=float)), errors="coerce")
    degradation_flags = []
    if bool(pd.to_numeric(safety.get("degraded", pd.Series(dtype=float)), errors="coerce").fillna(0.0).astype(bool).any()):
        degradation_flags.append("benchmark_unavailable")
    nominal_nav_series = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
    liquidatable_nav_series = pd.to_numeric(data["liquidatable_nav"], errors="coerce").dropna()
    initial_nav = float(nominal_nav_series.iloc[0])
    final_liquidatable_nav = float(liquidatable_nav_series.iloc[-1])
    daily_returns = liquidatable_nav_series.pct_change(fill_method=None).dropna()
    daily_log_returns = np.log1p(daily_returns.clip(lower=-0.999999999))
    total_log_return = float(daily_log_returns.sum()) if not daily_log_returns.empty else 0.0
    positive_log_returns = daily_log_returns[daily_log_returns > 0.0].sort_values(
        ascending=False
    )
    def _top_positive_log_share(count: int):
        if abs(total_log_return) <= 1e-12:
            return pd.NA
        return float(positive_log_returns.head(count).sum() / total_log_return)
    return_without_top5_days = (
        float(np.expm1(total_log_return - positive_log_returns.head(5).sum()))
        if not daily_log_returns.empty
        else pd.NA
    )
    trading_days = int(len(liquidatable_nav_series))
    total_return = final_liquidatable_nav / initial_nav - 1.0 if initial_nav > 0 else pd.NA
    annual_return = (
        float((1.0 + total_return) ** (252.0 / max(trading_days - 1, 1)) - 1.0)
        if trading_days > 1 and pd.notna(total_return)
        else pd.NA
    )
    annual_volatility = (
        float(daily_returns.std(ddof=0) * (252.0 ** 0.5))
        if not daily_returns.empty
        else pd.NA
    )
    sharpe = (
        float(daily_returns.mean() / daily_returns.std(ddof=0) * (252.0 ** 0.5))
        if len(daily_returns) >= 2 and float(daily_returns.std(ddof=0)) > 1e-12
        else pd.NA
    )
    running_peak = liquidatable_nav_series.cummax()
    drawdown = liquidatable_nav_series / running_peak - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else pd.NA
    win_rate = float((daily_returns > 0).mean()) if not daily_returns.empty else pd.NA
    freeze_period_lengths = _contiguous_true_lengths(freeze_mask)
    deleverage_period_lengths = _contiguous_true_lengths(deleverage_mask)
    freeze_exposure_caps = exposure_cap[freeze_mask].dropna().tolist()
    freeze_target_exposures = target_exposure[freeze_mask].dropna().tolist()
    deleverage_exposure_caps = exposure_cap[deleverage_mask].dropna().tolist()
    deleverage_target_exposures = target_exposure[deleverage_mask].dropna().tolist()
    reputation_history = runner.reputation.history_frame()
    latest_reputation = (
        reputation_history.sort_values(["date", "model_name"]).groupby("model_name", as_index=False).tail(1)
        if not reputation_history.empty
        else pd.DataFrame()
    )
    latest_trading_day_index = int(
        pd.to_numeric(latest_reputation.get("trading_day_index"), errors="coerce").dropna().max()
    ) if not latest_reputation.empty else -1
    reputation_window_observed_days = max(latest_trading_day_index + 1, 0)
    reputation_window_ready = bool(reputation_window_observed_days >= int(GOVERNANCE_REPUTATION_WARMUP_DAYS))
    ml_weight_distinction = float(
        pd.to_numeric(latest_reputation.get("model_weight_distinction"), errors="coerce").dropna().max()
    ) if not latest_reputation.empty else 0.0
    if not runner.enable_reputation:
        ml_weight_state = "equal_weight_reputation_disabled"
    elif not reputation_window_ready:
        ml_weight_state = "warmup_equal_weight_pending"
    elif ml_weight_distinction > 1e-9:
        ml_weight_state = "reputation_weighted_active"
    else:
        ml_weight_state = "reputation_ready_flat_weights"
    attribution = attribution_ledger.copy() if attribution_ledger is not None else pd.DataFrame()
    if not attribution.empty:
        benchmark_valid = (
            attribution[
                attribution.get(
                    "benchmark_return_valid",
                    pd.Series(False, index=attribution.index),
                )
                .astype("boolean")
                .fillna(False)
                .astype(bool)
            ]
            .copy()
        )
        avg_actual_exposure = _safe_numeric_mean(attribution.get("actual_exposure"))
        final_account_net_value = _safe_last(attribution.get("account_net_value"), default=1.0)
        final_invested_net_value = _safe_last(attribution.get("invested_capital_net_value"), default=1.0)
        final_valid_invested_net_value = _safe_last(attribution.get("valid_invested_capital_net_value"), default=1.0)
        final_holding_portfolio_net_value = _safe_last(attribution.get("holding_portfolio_net_value"), default=1.0)
        final_benchmark_net_value = _safe_last(attribution.get("benchmark_net_value"), default=1.0)
        final_excess_net_value = _safe_last(
            benchmark_valid.get("excess_net_value"),
            default=1.0,
        )
        final_active_difference_chain = _safe_last(
            attribution.get("active_return_difference_chain_net_value"),
            default=1.0,
        )
        final_invested_excess_net_value = _safe_last(
            benchmark_valid.get("invested_excess_net_value"),
            default=1.0,
        )
        final_valid_invested_excess_net_value = _safe_last(
            benchmark_valid.get("valid_invested_excess_net_value"),
            default=1.0,
        )
        final_holding_excess_net_value = _safe_last(
            benchmark_valid.get("holding_portfolio_excess_net_value"),
            default=1.0,
        )
        invested_capital_return = final_invested_net_value - 1.0
        valid_invested_capital_return = final_valid_invested_net_value - 1.0
        holding_portfolio_return = final_holding_portfolio_net_value - 1.0
        benchmark_total_return = final_benchmark_net_value - 1.0
        benchmark_excess_return = final_excess_net_value - 1.0
        benchmark_active_return_difference_chain = final_active_difference_chain - 1.0
        invested_excess_return = final_invested_excess_net_value - 1.0
        valid_invested_excess_return = final_valid_invested_excess_net_value - 1.0
        holding_portfolio_excess_return = final_holding_excess_net_value - 1.0
        invested_capital_max_drawdown = float(pd.to_numeric(attribution.get("invested_capital_drawdown"), errors="coerce").dropna().min()) if not pd.to_numeric(attribution.get("invested_capital_drawdown"), errors="coerce").dropna().empty else pd.NA
        valid_invested_capital_max_drawdown = float(pd.to_numeric(attribution.get("valid_invested_capital_drawdown"), errors="coerce").dropna().min()) if not pd.to_numeric(attribution.get("valid_invested_capital_drawdown"), errors="coerce").dropna().empty else pd.NA
        account_return_per_exposure = float(total_return) / max(avg_actual_exposure, 1e-12) if pd.notna(total_return) else pd.NA
        avg_factor_entropy = _safe_numeric_mean(attribution.get("factor_entropy"))
        avg_factor_top1_share = _safe_numeric_mean(attribution.get("factor_top1_share"))
        benchmark_beta = _safe_last(attribution.get("benchmark_beta_full_period"), default=0.0)
        upside_capture = _safe_last(attribution.get("upside_capture_full_period"), default=0.0)
        downside_capture = _safe_last(attribution.get("downside_capture_full_period"), default=0.0)
        valid_invested_observed_days = int(pd.Series(attribution.get("valid_invested_capital_observed", [])).fillna(False).astype(bool).sum())
    else:
        avg_actual_exposure = pd.NA
        invested_capital_return = pd.NA
        valid_invested_capital_return = pd.NA
        holding_portfolio_return = pd.NA
        benchmark_total_return = pd.NA
        benchmark_excess_return = pd.NA
        benchmark_active_return_difference_chain = pd.NA
        invested_excess_return = pd.NA
        valid_invested_excess_return = pd.NA
        holding_portfolio_excess_return = pd.NA
        invested_capital_max_drawdown = pd.NA
        valid_invested_capital_max_drawdown = pd.NA
        account_return_per_exposure = pd.NA
        avg_factor_entropy = pd.NA
        avg_factor_top1_share = pd.NA
        benchmark_beta = pd.NA
        upside_capture = pd.NA
        downside_capture = pd.NA
        valid_invested_observed_days = 0
    bucket = bucket_attribution.copy() if bucket_attribution is not None else pd.DataFrame()
    best_holding_bucket = _best_bucket(bucket, "holding_count_bucket", "valid_invested_excess_total_return")
    best_factor_entropy_bucket = _best_bucket(bucket, "factor_entropy_bucket", "valid_invested_excess_total_return")
    quality_reports = quality_reports or {}
    calibration = quality_reports.get("governance_entry_calibration_report", pd.DataFrame())
    payoff = quality_reports.get("governance_entry_payoff_report", pd.DataFrame())
    risk_contribution = quality_reports.get("governance_risk_contribution_ledger", pd.DataFrame())
    capacity = quality_reports.get("governance_capacity_stress_report", pd.DataFrame())
    lifecycle = quality_reports.get("governance_position_lifecycle_report", pd.DataFrame())
    factor_roles = quality_reports.get("governance_factor_role_report", pd.DataFrame())
    rolling_beat = quality_reports.get("governance_rolling_beat_report", pd.DataFrame())
    validation = quality_reports.get("governance_strategy_validation_matrix", pd.DataFrame())
    rebound_diagnostics = quality_reports.get("governance_rebound_entry_diagnostics", pd.DataFrame())
    research_gate = quality_reports.get("governance_research_gate_report", pd.DataFrame())
    factor_validation = quality_reports.get("governance_factor_validation_report", pd.DataFrame())
    portfolio_constraints = quality_reports.get("governance_portfolio_constraint_report", pd.DataFrame())
    trade_summary = trade_pair_summary.copy() if trade_pair_summary is not None else pd.DataFrame()
    trade_row = trade_summary.iloc[0].to_dict() if not trade_summary.empty else {}
    executions = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    if not executions.empty:
        reasons = executions.get("reason", pd.Series("", index=executions.index)).fillna("").astype(str)
        sides = executions.get("side", pd.Series("", index=executions.index)).fillna("").astype(str).str.lower()
        filled = executions.get("execution_status", pd.Series("", index=executions.index)).fillna("").astype(str).str.lower().eq("filled")
        defensive_force_mask = reasons.str.contains("force_deploy_defensive", case=False, regex=False)
        alpha_buy_mask = sides.eq("buy") & ~defensive_force_mask
        defensive_force_trade_count = int((filled & defensive_force_mask).sum())
        alpha_driven_trade_count = int((filled & alpha_buy_mask).sum())
    else:
        defensive_force_trade_count = 0
        alpha_driven_trade_count = 0
    closed_trade_count = int(_safe_float(trade_row.get("realized_trade_count"), default=0.0))
    closed_trade_win_rate = _safe_float(trade_row.get("closed_trade_win_rate"), default=float("nan"))
    realized_pnl = _safe_float(trade_row.get("realized_pnl"), default=0.0)
    gross_profit = _safe_float(trade_row.get("gross_profit"), default=0.0)
    gross_loss = _safe_float(trade_row.get("gross_loss"), default=0.0)
    avg_win = _safe_float(trade_row.get("avg_win"), default=float("nan"))
    avg_loss = _safe_float(trade_row.get("avg_loss"), default=float("nan"))
    payoff_ratio = _safe_float(trade_row.get("payoff_ratio"), default=float("nan"))
    profit_factor = _safe_float(trade_row.get("profit_factor"), default=float("nan"))
    open_position_count = int(_safe_float(trade_row.get("open_position_count"), default=0.0))
    pnl_by_sell_reason_text = _format_pnl_by_sell_reason(pnl_by_sell_reason)
    control_loss_summary = _control_avoided_loss_summary_from_frame(control_avoided_loss_summary)
    pwin10_ece = _calibration_ece(calibration, horizon_days=10)
    pwin10_wilson_lower = _calibration_best_wilson(calibration, horizon_days=10)
    buy_expectancy_10d = _payoff_metric(payoff, horizon_days=10, side="buy", metric="expectancy")
    buy_excess_10d = _payoff_metric(
        payoff,
        horizon_days=10,
        side="buy",
        metric="avg_directional_excess_return",
    )
    round_trip_variable_cost_proxy = _governance_round_trip_cost_rate()
    buy_after_variable_cost_10d = (
        float(buy_expectancy_10d) - float(round_trip_variable_cost_proxy)
        if pd.notna(buy_expectancy_10d)
        else pd.NA
    )
    buy_excess_after_variable_cost_10d = (
        float(buy_excess_10d) - float(round_trip_variable_cost_proxy)
        if pd.notna(buy_excess_10d)
        else pd.NA
    )
    buy_hit_rate_10d = _payoff_metric(payoff, horizon_days=10, side="buy", metric="hit_rate")
    sell_expectancy_10d = _payoff_metric(payoff, horizon_days=10, side="sell", metric="expectancy")
    normal_sell_expectancy_10d = _payoff_reason_metric(payoff, horizon_days=10, side="sell", reason="normal_sell", metric="expectancy")
    rebound_buy_expectancy_10d = _rebound_metric(rebound_diagnostics, diagnostic="rebound_buy_10d", metric="expectancy")
    rebound_buy_excess_10d = _rebound_metric(rebound_diagnostics, diagnostic="rebound_buy_10d", metric="avg_directional_excess_return")
    rebound_day_count = _rebound_metric(rebound_diagnostics, diagnostic="rebound_day_share", metric="sample_count")
    profit_giveback_lifecycle_flags = _safe_count_true(lifecycle.get("paper_profit_giveback_flag"))
    post_entry_failure_lifecycle_flags = _safe_count_true(lifecycle.get("post_entry_failure_flag"))
    sell_trigger_factor_count = _safe_count_true(factor_roles.get("sell_trigger_allowed"))
    risk_override_factor_count = _safe_count_true(factor_roles.get("risk_override_allowed"))
    rolling_beat_20d = _rolling_beat_metric(rolling_beat, window_days=20)
    rolling_beat_60d = _rolling_beat_metric(rolling_beat, window_days=60)
    rolling_beat_120d = _rolling_beat_metric(rolling_beat, window_days=120)
    rolling_beat_252d = _rolling_beat_metric(rolling_beat, window_days=252)
    rolling_beat_60d_2024 = _rolling_beat_metric(rolling_beat, window_days=60, segment="year_2024")
    max_risk_contribution_observed = _risk_gate_max_contribution(risk_contribution)
    capacity_10x_passed = _capacity_passed(capacity, multiplier=10)
    validation_gate_pass_ratio = _validation_pass_ratio(validation)
    validation_gate_fail_count = _validation_fail_count(validation)
    research_gate_status = _research_gate_status(research_gate)
    research_gate_fail_count = _research_gate_fail_count(research_gate)
    factor_validation_pass_count = _safe_count_true(factor_validation.get("pass_flag"))
    latest_constraint_pass = _latest_bool(portfolio_constraints.get("constraint_pass"))
    return pd.DataFrame(
        [
            {
                "strategy": runner.governance_variant,
                "strategy_source": "governance",
                "weighting_mode": "dynamic_governance",
                "trading_days": trading_days,
                "final_net_value": final_liquidatable_nav / initial_nav if initial_nav > 0 else pd.NA,
                "total_return": total_return,
                "annual_return": annual_return,
                "annual_volatility": annual_volatility,
                "sharpe": sharpe,
                "max_drawdown": max_drawdown,
                "win_rate": win_rate,
                "top1_positive_day_log_return_share": _top_positive_log_share(1),
                "top5_positive_day_log_return_share": _top_positive_log_share(5),
                "top10_positive_day_log_return_share": _top_positive_log_share(10),
                "return_without_top5_positive_days": return_without_top5_days,
                "avg_actual_exposure": avg_actual_exposure,
                "invested_capital_return": invested_capital_return,
                "valid_invested_capital_return": valid_invested_capital_return,
                "holding_portfolio_return": holding_portfolio_return,
                "benchmark_total_return": benchmark_total_return,
                "benchmark_return_method": (
                    "geometric_chain_linked_net_value"
                ),
                "benchmark_excess_return": benchmark_excess_return,
                "benchmark_excess_return_method": "geometric_nav_ratio",
                "benchmark_excess_endpoint_contract": "last_valid_benchmark_return_day",
                "benchmark_active_return_difference_chain": benchmark_active_return_difference_chain,
                "benchmark_active_return_difference_chain_method": "compounded_daily_arithmetic_difference",
                "invested_excess_return": invested_excess_return,
                "valid_invested_excess_return": valid_invested_excess_return,
                "holding_portfolio_excess_return": holding_portfolio_excess_return,
                "holding_portfolio_return_method": "exposure_scaled_account_return_approximation",
                "invested_capital_max_drawdown": invested_capital_max_drawdown,
                "valid_invested_capital_max_drawdown": valid_invested_capital_max_drawdown,
                "account_return_per_exposure": account_return_per_exposure,
                "benchmark_beta": benchmark_beta,
                "upside_capture": upside_capture,
                "downside_capture": downside_capture,
                "valid_invested_observed_days": valid_invested_observed_days,
                "avg_factor_entropy": avg_factor_entropy,
                "avg_factor_top1_share": avg_factor_top1_share,
                "best_holding_count_bucket_by_invested_excess": best_holding_bucket,
                "best_factor_entropy_bucket_by_invested_excess": best_factor_entropy_bucket,
                "p_win_10d_ece": pwin10_ece,
                "p_win_10d_best_bucket_wilson_lower": pwin10_wilson_lower,
                "buy_expectancy_10d": buy_expectancy_10d,
                "buy_forward_return_10d_gross": buy_expectancy_10d,
                "buy_forward_return_10d_after_variable_cost_proxy": buy_after_variable_cost_10d,
                "buy_forward_excess_return_10d_gross": buy_excess_10d,
                "buy_forward_excess_return_10d_after_variable_cost_proxy": buy_excess_after_variable_cost_10d,
                "buy_forward_return_10d_full_cost_status": "use_governance_scap_cost_stress_report_for_minimum_commission",
                "buy_forward_return_10d_metric_source": "governance_entry_payoff_report.expectancy_gross",
                "buy_hit_rate_10d": buy_hit_rate_10d,
                "sell_expectancy_10d": sell_expectancy_10d,
                "normal_sell_expectancy_10d": normal_sell_expectancy_10d,
                "closed_trade_count": closed_trade_count,
                "closed_trade_win_rate": closed_trade_win_rate,
                "realized_pnl": realized_pnl,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "payoff_ratio": payoff_ratio,
                "profit_factor": profit_factor,
                "open_position_count": open_position_count,
                "alpha_driven_trade_count": alpha_driven_trade_count,
                "force_deploy_defensive_trade_count": defensive_force_trade_count,
                "force_deploy_result_is_alpha_evidence": bool(
                    runner.capital_usage_mode != GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY
                ),
                "force_deploy_interpretation": (
                    "normal capital mode; account result may be evaluated as strategy evidence subject to gates"
                    if runner.capital_usage_mode != GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY
                    else "force_deploy is an execution pressure test; defensive-sleeve trades are not alpha evidence"
                ),
                "pnl_by_sell_reason": pnl_by_sell_reason_text,
                "control_exit_count": control_loss_summary["control_exit_count"],
                "control_avoided_loss_to_window_low": control_loss_summary["avoided_loss_to_window_low"],
                "control_avoided_loss_to_window_end": control_loss_summary["avoided_loss_to_window_end"],
                "hard_stop_avoided_loss_to_window_low": control_loss_summary["hard_stop_avoided_loss_to_window_low"],
                "alpha_collapse_avoided_loss_to_window_low": control_loss_summary["alpha_collapse_avoided_loss_to_window_low"],
                "safety_deleveraging_avoided_loss_to_window_low": control_loss_summary["safety_deleveraging_avoided_loss_to_window_low"],
                "control_counterfactual_note": (
                    "Avoided-loss diagnostics compare actual sell net price with the post-exit "
                    f"{int(GOVERNANCE_CONTROL_AVOIDED_LOSS_HORIZON_DAYS)}-trading-day low/end; not live tradable PnL."
                ),
                "rebound_buy_expectancy_10d": rebound_buy_expectancy_10d,
                "rebound_buy_excess_10d": rebound_buy_excess_10d,
                "rebound_day_count": rebound_day_count,
                "profit_giveback_lifecycle_flags": profit_giveback_lifecycle_flags,
                "post_entry_failure_lifecycle_flags": post_entry_failure_lifecycle_flags,
                "sell_trigger_factor_count": sell_trigger_factor_count,
                "risk_override_factor_count": risk_override_factor_count,
                "rolling_beat_ratio_20d": rolling_beat_20d,
                "rolling_beat_ratio_60d": rolling_beat_60d,
                "rolling_beat_ratio_120d": rolling_beat_120d,
                "rolling_beat_ratio_252d": rolling_beat_252d,
                "rolling_beat_ratio_60d_2024": rolling_beat_60d_2024,
                "max_risk_contribution_observed": max_risk_contribution_observed,
                "capacity_10x_passed": capacity_10x_passed,
                "validation_gate_pass_ratio": validation_gate_pass_ratio,
                "validation_gate_fail_count": validation_gate_fail_count,
                "research_gate_status": research_gate_status,
                "research_gate_fail_count": research_gate_fail_count,
                "factor_validation_pass_count": factor_validation_pass_count,
                "latest_portfolio_constraint_pass": latest_constraint_pass,
                "high_exposure_research_gate": bool(
                    closed_trade_count >= int(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES)
                    and pd.notna(profit_factor)
                    and float(profit_factor) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR)
                    and float(realized_pnl) > float(GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL)
                    and (
                        (pd.notna(payoff_ratio) and float(payoff_ratio) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO))
                        or (
                            pd.notna(closed_trade_win_rate)
                            and float(closed_trade_win_rate) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE)
                        )
                    )
                    and float(max_risk_contribution_observed or 0.0) <= float(GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION)
                ),
                "account_total_exposure": float(pd.to_numeric(data.get("actual_exposure", pd.Series(dtype=float)), errors="coerce").mean()),
                "top1_account_weight": float(pd.to_numeric(data.get("top1_account_weight", pd.Series(dtype=float)), errors="coerce").mean()),
                "top5_account_weight_sum": float(pd.to_numeric(data.get("top5_account_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                "account_effective_n": float(pd.to_numeric(data.get("account_effective_n", pd.Series(dtype=float)), errors="coerce").mean()),
                "top1_sleeve_weight": float(pd.to_numeric(data.get("top1_sleeve_weight", data.get("top1_weight", pd.Series(dtype=float))), errors="coerce").mean()),
                "top5_sleeve_weight_sum": float(pd.to_numeric(data.get("top5_sleeve_weight_sum", data.get("top5_weight_sum", pd.Series(dtype=float))), errors="coerce").mean()),
                "sleeve_effective_n": float(pd.to_numeric(data.get("sleeve_effective_n", data.get("effective_n", pd.Series(dtype=float))), errors="coerce").mean()),
                "top20pct_sleeve_weight_sum": float(pd.to_numeric(data.get("top20pct_sleeve_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                "sleeve_effective_n_ratio": float(pd.to_numeric(data.get("sleeve_effective_n_ratio", pd.Series(dtype=float)), errors="coerce").mean()),
                "sleeve_weight_hhi": float(pd.to_numeric(data.get("sleeve_weight_hhi", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_sizing_reference_positions": float(pd.to_numeric(data.get("sizing_reference_positions", pd.Series(dtype=float)), errors="coerce").mean()),
                "sizing_contract_version": _last_text(data, "sizing_contract_version", "legacy_contract_unavailable"),
                "average_executable_target_holding_count": float(pd.to_numeric(data.get("executable_target_holding_count", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_executable_target_exposure": float(pd.to_numeric(data.get("executable_target_exposure", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_authority_attainable_holding_count": float(pd.to_numeric(data.get("authority_attainable_holding_count", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_authority_attainable_exposure": float(pd.to_numeric(data.get("authority_attainable_exposure", pd.Series(dtype=float)), errors="coerce").mean()),
                "policy_floor_feasible_after_authority_day_count": int(pd.Series(data.get("policy_floor_feasible_after_authority", pd.Series(False, index=data.index))).fillna(False).astype(bool).sum()),
                "plan_floor_contract_violation_day_count": int(pd.Series(data.get("plan_floor_contract_violation", pd.Series(False, index=data.index))).fillna(False).astype(bool).sum()),
                "structural_floor_infeasible_day_count": int(pd.Series(data.get("structural_floor_infeasible", pd.Series(False, index=data.index))).fillna(False).astype(bool).sum()),
                "floor_violation_unresolved_search_day_count": int(pd.Series(data.get("floor_violation_unresolved_search", pd.Series(False, index=data.index))).fillna(False).astype(bool).sum()),
                "average_selected_action_symbol_count": float(pd.to_numeric(data.get("selected_position_count", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_planned_holding_count": float(pd.to_numeric(data.get("optimizer_planned_holding_count", data.get("planned_holding_count", pd.Series(dtype=float))), errors="coerce").mean()),
                # Deprecated compatibility alias: this is an action-symbol
                # count, not a planned portfolio holding count.
                "average_selected_position_count": float(pd.to_numeric(data.get("selected_position_count", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_profit_coverage_ratio": float(pd.to_numeric(data.get("profit_coverage_ratio", pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan).mean()),
                "average_profit_coverage_probability_lower": float(pd.to_numeric(data.get("profit_coverage_probability_lower", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_coverage_evidence_name_count": float(pd.to_numeric(data.get("coverage_evidence_name_count", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_lifecycle_cost_amount": float(pd.to_numeric(data.get("lifecycle_cost_amount", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_expected_log_growth": float(pd.to_numeric(data.get("expected_log_growth", pd.Series(dtype=float)), errors="coerce").mean()),
                "minimum_selected_marginal_utility_amount": float(pd.to_numeric(data.get("minimum_selected_marginal_utility_amount", pd.Series(dtype=float)), errors="coerce").min()),
                "maximum_rejected_marginal_utility_amount": float(pd.to_numeric(data.get("maximum_rejected_marginal_utility_amount", pd.Series(dtype=float)), errors="coerce").max()),
                "coverage_mode": _last_text(data, "coverage_mode", "diagnostic_shadow"),
                "maximum_coverage_penalty_amount": float(pd.to_numeric(data.get("coverage_penalty_amount", pd.Series(dtype=float)), errors="coerce").max()),
                "average_incremental_expected_wealth_amount": float(pd.to_numeric(data.get("incremental_expected_wealth_amount", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_incremental_cvar_amount": float(pd.to_numeric(data.get("incremental_cvar_amount", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_model_uncertainty_amount": float(pd.to_numeric(data.get("model_uncertainty_amount", pd.Series(dtype=float)), errors="coerce").mean()),
                "average_scenario_risk_penalty_amount": float(pd.to_numeric(data.get("scenario_risk_penalty_amount", pd.Series(dtype=float)), errors="coerce").mean()),
                "latest_scenario_evidence_state": _last_text(data, "scenario_evidence_state", "unavailable"),
                "latest_scenario_contract_id": _last_text(data, "scenario_contract_id", ""),
                "latest_scenario_risk_measure": _last_text(data, "scenario_risk_measure", "correlated_tail_loss_proxy"),
                "maximum_joint_scenario_count": float(pd.to_numeric(data.get("joint_scenario_count", pd.Series(dtype=float)), errors="coerce").max()),
                "average_regime_es_budget_multiplier": float(pd.to_numeric(data.get("regime_es_budget_multiplier", pd.Series(dtype=float)), errors="coerce").mean()),
                "maximum_best_rejected_objective_amount": float(pd.to_numeric(data.get("best_rejected_objective_amount", pd.Series(dtype=float)), errors="coerce").max()),
                "top20pct_risk_contribution_sum": float(pd.to_numeric(data.get("top20pct_risk_contribution_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                "risk_effective_n_ratio": float(pd.to_numeric(data.get("risk_effective_n_ratio", pd.Series(dtype=float)), errors="coerce").mean()),
                "risk_contribution_hhi": float(pd.to_numeric(data.get("risk_contribution_hhi", pd.Series(dtype=float)), errors="coerce").mean()),
                "top1_weight": float(pd.to_numeric(data.get("top1_weight", pd.Series(dtype=float)), errors="coerce").mean()),
                "top5_weight_sum": float(pd.to_numeric(data.get("top5_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                "effective_n": float(pd.to_numeric(data.get("effective_n", pd.Series(dtype=float)), errors="coerce").mean()),
                "weight_basis": "top*_weight/effective_n are legacy sleeve-weight fields; use account_* and sleeve_* fields",
                "degradation_flags": "|".join(degradation_flags),
                "degradation_count": len(degradation_flags),
                "price_basis": "nominal_unadjusted",
                "neutralization_mode": "not_applicable",
                "ml_runtime_mode": "not_applicable",
                "requested_model": "",
                "runtime_model": "",
                "benchmark_status": (
                    "exploratory: "
                    f"top_liquidity_{int(runner.performance_benchmark_top_n)}_equal_weight_"
                    f"{runner.performance_benchmark_rebalance}; prior-period fixed-N stock pool; "
                    "equal-weight research fallback until PIT free-float market capitalisation is available"
                ),
                "performance_benchmark_top_n": int(runner.performance_benchmark_top_n),
                "performance_benchmark_rebalance": str(runner.performance_benchmark_rebalance),
                "portfolio_normal_rebalance_frequency": str(
                    getattr(runner, "portfolio_normal_rebalance_frequency", "")
                ),
                "portfolio_normal_rebalance_anchor": str(
                    runner.capital_profile.get("portfolio_normal_rebalance_anchor", "")
                ),
                "safety_benchmark_symbol": str(runner.engine.safety_agent.proxy_symbol),
                "governance_variant": runner.governance_variant,
                "safety_proxy_mode": runner.engine.safety_agent.proxy_mode,
                "exposure_cap_mode": "rule_based_safety_agent" if runner.enable_safety_agent else "disabled",
                "safety_agent_enabled": runner.enable_safety_agent,
                "reputation_enabled": runner.enable_reputation,
                "governance_control_mode": runner.governance_control_mode,
                "capital_profile_name": str(runner.capital_profile.get("name", "custom")),
                "objective_metric": str(runner.capital_profile.get("objective_metric", "")),
                "special_strategy_version": str(
                    runner.capital_profile.get("special_strategy_version", "")
                ),
                "scap_exit_stage": str(
                    runner.capital_profile.get("scap_exit_stage", "E0") or "E0"
                ).upper(),
                "scap_loss_stop": float(
                    runner.capital_profile.get("scap_loss_stop", -0.12)
                ),
                "runtime_identity_hash": str(
                    getattr(runner, "runtime_identity", {}).get("runtime_identity_hash", "")
                ),
                "code_fingerprint": str(
                    getattr(runner, "runtime_identity", {}).get("code_fingerprint", "")
                ),
                "runtime_identity_schema_version": str(
                    getattr(runner, "runtime_identity", {}).get("schema_version", "")
                ),
                "experiment_sample_role": str(
                    getattr(runner, "runtime_identity", {}).get(
                        "experiment_sample_role", ""
                    )
                ),
                "reputation_control_enabled": runner._control_enabled("reputation"),
                "regime_control_enabled": bool(
                    runner.enable_market_regime_policy
                    and runner._control_enabled("regime")
                ),
                "market_state_semantics_contract_version": "v1_explicit_authority",
                "safety_market_state_active": bool(runner.enable_safety_agent),
                "safety_market_state_authority": (
                    "hard_safety_cap_and_scap_policy_band"
                    if runner.enable_safety_agent else "disabled"
                ),
                "optional_regime_overlay_enabled": bool(runner.enable_market_regime_policy),
                "optional_regime_overlay_authorized": bool(
                    runner.enable_market_regime_policy
                    and runner._control_enabled("regime")
                ),
                "performance_benchmark_authority": "attribution_only_no_trade_authority",
                "safety_benchmark_authority": "safety_market_state_input",
                "cooldown_control_enabled": runner._control_enabled("cooldown"),
                "hard_stop_control_enabled": runner._control_enabled("hard_stop_exit"),
                "alpha_collapse_exit_enabled": runner.alpha_collapse_exit_enabled,
                "reputation_window_ready": reputation_window_ready,
                "reputation_window_observed_days": reputation_window_observed_days,
                "reputation_window_required_days": int(GOVERNANCE_REPUTATION_WARMUP_DAYS),
                "ml_weight_state": ml_weight_state,
                "ml_weight_distinction": ml_weight_distinction,
                "sector_cap_enabled": runner.enable_sector_cap,
                "portfolio_exposure_cap": float(exposure_cap.mean()) if not exposure_cap.dropna().empty else pd.NA,
                "turnover_budget": float(turnover_budget.mean()) if not turnover_budget.dropna().empty else pd.NA,
                "participation_rate": float(participation_rate.mean()) if not participation_rate.dropna().empty else pd.NA,
                "capacity_passed_ratio": float(capacity_passed.mean()) if not capacity_passed.dropna().empty else pd.NA,
                "trading_freeze_trigger_count": int(len(freeze_period_lengths)),
                "trading_freeze_total_rebalance_periods": int(freeze_mask.sum()),
                "trading_freeze_period_lengths": ",".join(str(length) for length in freeze_period_lengths) if freeze_period_lengths else "",
                "trading_freeze_min_exposure_cap": min(freeze_exposure_caps) if freeze_exposure_caps else pd.NA,
                "trading_freeze_min_target_exposure": min(freeze_target_exposures) if freeze_target_exposures else pd.NA,
                "risk_confirmed_crisis_days": int(confirmed_crisis_mask.sum()),
                "risk_confirmed_high_days": int(confirmed_high_mask.sum()),
                "exposure_cap_below_full_days": int(deleverage_mask.sum()),
                "actual_emergency_sell_days": actual_forced_sell_days,
                "emergency_deleveraging_trigger_count": int(len(deleverage_period_lengths)),
                "emergency_deleveraging_total_rebalance_periods": int(deleverage_mask.sum()),
                "emergency_deleveraging_period_lengths": ",".join(str(length) for length in deleverage_period_lengths) if deleverage_period_lengths else "",
                "emergency_deleveraging_min_exposure_cap": min(deleverage_exposure_caps) if deleverage_exposure_caps else pd.NA,
                "emergency_deleveraging_min_target_exposure": min(deleverage_target_exposures) if deleverage_target_exposures else pd.NA,
                "date_window": f"{pd.to_datetime(data['date']).min().date()} -> {pd.to_datetime(data['date']).max().date()}",
                "composite_score": pd.NA,
                # Registry framework metadata
                "universe_name": runner._universe_name or "unknown",
                "universe_mode": runner._universe_mode,
                "alpha_bundle": runner._alpha_bundle or "unknown",
                **runner.factor_source_spec.summary_dict(),
                "registry_version": runner._registry_version or "unknown",
            }
        ]
    )
