"""Read-only path audit for a persisted SCAP governance run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _read(run_dir: Path, name: str) -> pd.DataFrame:
    path = run_dir / name
    return pd.read_csv(path, low_memory=False) if path.is_file() else pd.DataFrame()


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _finite(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _records(frame: pd.DataFrame, columns: list[str], n: int = 20) -> list[dict]:
    if frame.empty:
        return []
    data = frame.loc[:, [c for c in columns if c in frame.columns]].head(n).copy()
    for column in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[column]):
            data[column] = data[column].dt.strftime("%Y-%m-%d")
    return json.loads(data.replace({np.nan: None}).to_json(orient="records", date_format="iso"))


def audit(run_dir: Path) -> dict:
    daily = _read(run_dir, "governance_daily_result.csv")
    executions = _read(run_dir, "governance_execution_ledger.csv")
    holdings = _read(run_dir, "governance_holdings_ledger.csv")
    trades = _read(run_dir, "governance_trade_pairs.csv")
    plans = _read(run_dir, "governance_action_plan_ledger.csv")
    benchmark = _read(run_dir, "governance_performance_benchmark.csv")

    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    daily = daily.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    daily["nav"] = _finite(daily["nominal_nav"])
    daily["return"] = daily["nav"].pct_change(fill_method=None).fillna(0.0)
    daily["log_return"] = np.log1p(daily["return"].clip(lower=-0.999999999))
    daily["holding"] = _finite(daily["holding_count"]).fillna(0).astype(int)
    daily["holding_delta"] = daily["holding"].diff().fillna(daily["holding"]).astype(int)
    daily["economic_cap"] = _finite(daily["economic_position_cap"])
    daily["effective_cap"] = _finite(daily["effective_position_cap"])
    daily["exposure"] = _finite(daily["actual_exposure"])
    daily["allow_rebalance"] = _bool(daily["allow_normal_rebalance"])
    daily["month"] = daily["date"].dt.to_period("M").astype(str)

    total_log = float(daily["log_return"].sum())
    positive = daily[daily["log_return"] > 0].sort_values("log_return", ascending=False)
    top_share = {}
    for count in (1, 5, 10, 20):
        top_log = float(positive.head(count)["log_return"].sum())
        top_share[str(count)] = {
            "log_return_sum": top_log,
            "share_of_total_log_return": top_log / total_log if abs(total_log) > 1e-12 else None,
        }
    monthly = (
        daily.groupby("month", sort=True)
        .agg(
            return_sum=("log_return", lambda x: float(np.expm1(x.sum()))),
            average_holding=("holding", "mean"),
            maximum_holding=("holding", "max"),
            average_exposure=("exposure", "mean"),
        )
        .reset_index()
    )

    abrupt = daily.loc[daily["holding_delta"].abs() >= 3].copy()
    max_holding_rows = daily.loc[daily["holding"].eq(daily["holding"].max())].copy()

    if not holdings.empty:
        holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce").dt.normalize()
        holdings["account_weight_num"] = _finite(holdings["account_weight"])
        daily_top_weight = holdings.groupby("date")["account_weight_num"].max()
    else:
        daily_top_weight = pd.Series(dtype=float)

    if not executions.empty:
        for column in ("signal_date", "trade_date"):
            executions[column] = pd.to_datetime(executions[column], errors="coerce").dt.normalize()
        executions["trade_notional_num"] = _finite(executions["trade_notional"]).fillna(0.0)
        executions["total_cost_num"] = _finite(executions["total_cost"]).fillna(0.0)
        executions["executed_shares_num"] = _finite(executions["executed_shares"]).fillna(0.0)
        executions = executions[executions["execution_status"].astype(str).eq("filled")].copy()
        allowed_map = daily.set_index("date")["allow_rebalance"]
        executions["signal_allow_normal_rebalance"] = executions["signal_date"].map(allowed_map).fillna(False)
        executions["trade_month"] = executions["trade_date"].dt.to_period("M").astype(str)
        trade_by_month = (
            executions.groupby(["trade_month", "side"], dropna=False)
            .agg(fills=("order_id", "count"), notional=("trade_notional_num", "sum"), cost=("total_cost_num", "sum"))
            .reset_index()
        )
        reason_counts = (
            executions.groupby(["side", "reason"], dropna=False)
            .size().rename("count").reset_index().sort_values("count", ascending=False)
        )
    else:
        trade_by_month = pd.DataFrame()
        reason_counts = pd.DataFrame()

    if not plans.empty:
        plans["decision_date"] = pd.to_datetime(plans["decision_date"], errors="coerce").dt.normalize()
        plans["selected_count_num"] = _finite(plans["selected_position_count"]).fillna(0).astype(int)
        plans["target_changed"] = plans["target_lots_by_symbol"].astype(str).ne(
            plans["target_lots_by_symbol"].astype(str).shift()
        )
        plans["allow_rebalance"] = plans["decision_date"].map(
            daily.set_index("date")["allow_rebalance"]
        ).fillna(False)
        target_changes = plans[plans["target_changed"]].copy()
    else:
        target_changes = pd.DataFrame()

    if not trades.empty:
        trades["realized_pnl_amount_num"] = _finite(trades["realized_pnl_amount"]).fillna(0.0)
        trades["realized_pnl_pct_num"] = _finite(trades["realized_pnl_pct"])
        pnl_reasons = (
            trades.groupby("sell_reason", dropna=False)
            .agg(
                trades=("trade_id", "count"),
                pnl=("realized_pnl_amount_num", "sum"),
                average_return=("realized_pnl_pct_num", "mean"),
                wins=("realized_pnl_amount_num", lambda x: int((x > 0).sum())),
            )
            .reset_index().sort_values("pnl")
        )
    else:
        pnl_reasons = pd.DataFrame()

    benchmark_summary = {}
    if not benchmark.empty and "benchmark_net_value" in benchmark.columns:
        b = _finite(benchmark["benchmark_net_value"]).dropna()
        if len(b):
            benchmark_summary = {
                "rows": int(len(benchmark)),
                "valid_values": int(len(b)),
                "total_return": float(b.iloc[-1] / b.iloc[0] - 1.0) if b.iloc[0] else None,
            }

    return {
        "path": str(run_dir),
        "daily": {
            "days": int(len(daily)),
            "start": daily["date"].min().strftime("%Y-%m-%d"),
            "end": daily["date"].max().strftime("%Y-%m-%d"),
            "start_nav": float(daily["nav"].iloc[0]),
            "end_nav": float(daily["nav"].iloc[-1]),
            "total_return": float(daily["nav"].iloc[-1] / daily["nav"].iloc[0] - 1.0),
            "up_days": int((daily["return"] > 1e-12).sum()),
            "down_days": int((daily["return"] < -1e-12).sum()),
            "flat_days": int((daily["return"].abs() <= 1e-12).sum()),
            "zero_holding_days": int(daily["holding"].eq(0).sum()),
            "top_positive_day_concentration": top_share,
            "top_positive_days": _records(positive, ["date", "return", "nav", "holding", "exposure"], 20),
            "worst_days": _records(daily.sort_values("return"), ["date", "return", "nav", "holding", "exposure"], 20),
            "monthly": _records(monthly, list(monthly.columns), len(monthly)),
        },
        "holdings": {
            "maximum": int(daily["holding"].max()),
            "mean": float(daily["holding"].mean()),
            "median": float(daily["holding"].median()),
            "days_over_5": int(daily["holding"].gt(5).sum()),
            "days_at_least_8": int(daily["holding"].ge(8).sum()),
            "days_at_or_over_effective_cap": int(daily["holding"].ge(daily["effective_cap"]).sum()),
            "days_over_effective_cap": int(daily["holding"].gt(daily["effective_cap"]).sum()),
            "economic_cap_min": float(daily["economic_cap"].min()),
            "economic_cap_max": float(daily["economic_cap"].max()),
            "average_exposure": float(daily["exposure"].mean()),
            "days_exposure_over_90pct": int(daily["exposure"].gt(0.90).sum()),
            "maximum_daily_single_name_weight": float(daily_top_weight.max()) if len(daily_top_weight) else None,
            "abrupt_changes_abs_ge_3": _records(abrupt, ["date", "holding", "holding_delta", "economic_cap", "effective_cap", "exposure", "regime_name"], 50),
            "maximum_holding_dates": _records(max_holding_rows, ["date", "holding", "economic_cap", "effective_cap", "exposure", "regime_name"], 50),
        },
        "rebalancing": {
            "normal_rebalance_allowed_days": int(daily["allow_rebalance"].sum()),
            "normal_rebalance_blocked_days": int((~daily["allow_rebalance"]).sum()),
            "filled_orders": int(len(executions)),
            "filled_buys": int(executions["side"].astype(str).eq("buy").sum()) if not executions.empty else 0,
            "filled_sells": int(executions["side"].astype(str).eq("sell").sum()) if not executions.empty else 0,
            "buy_signals_outside_normal_rebalance": int(
                (executions["side"].astype(str).eq("buy") & ~executions["signal_allow_normal_rebalance"]).sum()
            ) if not executions.empty else 0,
            "sell_signals_outside_normal_rebalance": int(
                (executions["side"].astype(str).eq("sell") & ~executions["signal_allow_normal_rebalance"]).sum()
            ) if not executions.empty else 0,
            "unique_signal_dates": int(executions["signal_date"].nunique()) if not executions.empty else 0,
            "unique_trade_dates": int(executions["trade_date"].nunique()) if not executions.empty else 0,
            "target_change_days": int(target_changes["decision_date"].nunique()) if not target_changes.empty else 0,
            "target_changes_outside_normal_rebalance": int((~target_changes["allow_rebalance"]).sum()) if not target_changes.empty else 0,
            "trade_by_month": _records(trade_by_month, list(trade_by_month.columns), 100),
            "reason_counts": _records(reason_counts, list(reason_counts.columns), 100),
            "outside_rebalance_orders": _records(
                executions[~executions["signal_allow_normal_rebalance"]],
                ["signal_date", "trade_date", "symbol", "side", "reason", "position_exit_reason", "trade_notional_num"],
                100,
            ) if not executions.empty else [],
        },
        "trades": {
            "closed": int(len(trades)),
            "realized_pnl": float(trades["realized_pnl_amount_num"].sum()) if not trades.empty else 0.0,
            "reason_summary": _records(pnl_reasons, list(pnl_reasons.columns), 100),
        },
        "benchmark": benchmark_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()
    print(json.dumps(audit(Path(args.run_dir).resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
