# -*- coding: utf-8 -*-
"""Export Kelly prior sensitivity diagnostics from historical strategy stats."""
from __future__ import annotations

import argparse

import pandas as pd
import pyarrow.parquet as pq

from config import (
    FEATURE_DAILY_PARQUET,
    KELLY_PRIOR_SENSITIVITY_CSV,
    KELLY_PRIOR_SENSITIVITY_MD,
    POSITION_BAYES_PRIOR_P,
    POSITION_BAYES_PRIOR_STRENGTH,
    STRATEGY_END_DATE,
    assert_valid_configuration,
)
from functions.event_statistics import kelly_prior_sensitivity_grid
from functions.position_managed_selection import _calibrate_strategy_stats_from_history
from functions.report_builder import save_strategy_report
from functions.feature_engineering import required_feature_columns_for_strategy


def main():
    assert_valid_configuration()
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-ids", nargs="*", default=None)
    parser.add_argument("--rebalance-date", default=STRATEGY_END_DATE)
    parser.add_argument("--prior-ps", nargs="*", type=float, default=[0.40, 0.50, 0.60])
    parser.add_argument("--prior-strengths", nargs="*", type=float, default=[0.0, 5.0, 20.0, 60.0])
    args = parser.parse_args()

    features = _load_sensitivity_feature_slice(args.strategy_ids)
    stats = _calibrate_strategy_stats_from_history(
        features,
        rebalance_date=args.rebalance_date,
        strategy_ids=args.strategy_ids,
    )
    if stats.empty:
        raise SystemExit("No historical strategy stats available for Kelly prior sensitivity.")

    rows = []
    for row in stats.to_dict("records"):
        wins = float(row.get("wins", 0.0))
        losses = float(row.get("losses", 0.0))
        avg_win = float(row.get("avg_win", 0.0))
        avg_loss = float(row.get("avg_loss", 0.0))
        payoff_ratio = avg_win / abs(avg_loss) if avg_win > 0 and avg_loss < 0 else 1.0
        sensitivity = kelly_prior_sensitivity_grid(
            wins=wins,
            losses=losses,
            payoff_ratio=payoff_ratio,
            prior_ps=[float(item) for item in args.prior_ps],
            prior_strengths=[float(item) for item in args.prior_strengths],
        )
        sensitivity.insert(0, "strategy_id", str(row["strategy_id"]))
        sensitivity.insert(1, "reputation_weight", float(row.get("reputation_weight", 1.0)))
        sensitivity.insert(2, "avg_win", avg_win)
        sensitivity.insert(3, "avg_loss", avg_loss)
        rows.append(sensitivity)

    result = pd.concat(rows, ignore_index=True)
    result.to_csv(KELLY_PRIOR_SENSITIVITY_CSV, index=False, encoding="utf-8-sig")
    report = build_kelly_prior_sensitivity_report(
        result,
        rebalance_date=str(args.rebalance_date),
        baseline_prior_p=float(POSITION_BAYES_PRIOR_P),
        baseline_prior_strength=float(POSITION_BAYES_PRIOR_STRENGTH),
    )
    save_strategy_report(report, KELLY_PRIOR_SENSITIVITY_MD)
    print(f"Saved Kelly prior sensitivity CSV: {KELLY_PRIOR_SENSITIVITY_CSV}")
    print(f"Saved Kelly prior sensitivity report: {KELLY_PRIOR_SENSITIVITY_MD}")


def _load_sensitivity_feature_slice(strategy_ids):
    strategy_ids = [str(item) for item in strategy_ids] if strategy_ids else [
        "macd_cross",
        "rsi_reversal",
        "low_volume_pullback",
        "mean_reversion",
        "turtle_breakout",
        "price_volume_breakout",
        "holiday_effect",
        "consecutive_decline_rebound",
        "eod_close_strength",
        "limit_up_follow",
        "ma_cross",
        "kdj_oversold_cross",
        "grid_trading",
        "alpha_hedge",
        "event_driven",
    ]
    schema = set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    columns = {"date", "symbol", "close", "amount", "ret_20", "future_ret_5", "future_ret_10", "future_ret_20"}
    for strategy_id in strategy_ids:
        columns.update(required_feature_columns_for_strategy(strategy_id))
    selected = sorted(col for col in columns if col in schema)
    return pd.read_parquet(FEATURE_DAILY_PARQUET, columns=selected)


def build_kelly_prior_sensitivity_report(result: pd.DataFrame, *, rebalance_date: str, baseline_prior_p: float, baseline_prior_strength: float) -> str:
    lines = [
        "# Kelly Prior Sensitivity Report",
        "",
        "## Summary",
        f"- Rebalance date: `{rebalance_date}`",
        f"- Baseline prior_p: `{baseline_prior_p:.2f}`",
        f"- Baseline prior_strength: `{baseline_prior_strength:.2f}`",
        "- This artifact shows how posterior win-rate and Kelly sizing change under alternate priors.",
        "",
        "## Records",
        result[
            [
                "strategy_id",
                "prior_p",
                "prior_strength",
                "wins",
                "losses",
                "posterior_mean",
                "posterior_lower_bound",
                "payoff_ratio",
                "kelly_mean",
                "kelly_lower_bound",
            ]
        ].to_markdown(index=False),
    ]
    baseline = result[
        (pd.to_numeric(result["prior_p"], errors="coerce").round(6) == round(float(baseline_prior_p), 6))
        & (pd.to_numeric(result["prior_strength"], errors="coerce").round(6) == round(float(baseline_prior_strength), 6))
    ].copy()
    if not baseline.empty:
        lines.extend(
            [
                "",
                "## Baseline Rows",
                baseline[
                    [
                        "strategy_id",
                        "wins",
                        "losses",
                        "posterior_mean",
                        "posterior_lower_bound",
                        "kelly_mean",
                        "kelly_lower_bound",
                    ]
                ].to_markdown(index=False),
            ]
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
