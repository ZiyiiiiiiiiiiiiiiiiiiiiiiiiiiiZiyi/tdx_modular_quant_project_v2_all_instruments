"""Exploratory promotion checks and paired block-bootstrap diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd
from itertools import combinations


def paired_block_bootstrap_interval(
    excess_returns,
    *,
    block_size: int = 5,
    samples: int = 1000,
    confidence: float = 0.90,
    random_seed: int = 42,
) -> tuple[float, float]:
    values = pd.to_numeric(pd.Series(excess_returns), errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < block_size:
        raise ValueError("Not enough observations for paired block bootstrap")
    rng = np.random.default_rng(random_seed)
    starts = np.arange(0, len(values) - block_size + 1)
    means = []
    needed = int(np.ceil(len(values) / block_size))
    for _ in range(int(samples)):
        chunks = [values[start:start + block_size] for start in rng.choice(starts, size=needed, replace=True)]
        means.append(float(np.concatenate(chunks)[: len(values)].mean()))
    alpha = (1.0 - float(confidence)) / 2.0
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))


def build_non_overlapping_window_report(
    governance_daily: pd.DataFrame,
    baseline_daily: pd.DataFrame,
    *,
    window_days: int = 63,
) -> pd.DataFrame:
    gov = _daily_return_frame(governance_daily, "governance_return")
    base = _daily_return_frame(baseline_daily, "baseline_return")
    merged = gov.merge(base, on="date", how="inner").sort_values("date").reset_index(drop=True)
    merged["window_id"] = np.arange(len(merged)) // int(window_days)
    return (
        merged.groupby("window_id", as_index=False)
        .agg(
            start_date=("date", "min"),
            end_date=("date", "max"),
            row_count=("date", "count"),
            governance_return=("governance_return", lambda values: float((1.0 + values).prod() - 1.0)),
            baseline_return=("baseline_return", lambda values: float((1.0 + values).prod() - 1.0)),
        )
        .assign(excess_return=lambda frame: frame["governance_return"] - frame["baseline_return"])
    )


def evaluate_phase_two_admission(
    governance_daily: pd.DataFrame,
    baseline_daily: pd.DataFrame,
    *,
    minimum_windows: int = 8,
    positive_window_ratio: float = 0.60,
    max_drawdown_worsening: float = 0.02,
) -> dict:
    windows = build_non_overlapping_window_report(governance_daily, baseline_daily)
    complete = windows[windows["row_count"] == 63].copy()
    merged = _daily_return_frame(governance_daily, "governance_return").merge(
        _daily_return_frame(baseline_daily, "baseline_return"),
        on="date",
        how="inner",
    )
    merged["excess_return"] = merged["governance_return"] - merged["baseline_return"]
    interval = paired_block_bootstrap_interval(merged["excess_return"]) if len(merged) >= 5 else (np.nan, np.nan)
    gov_dd = _max_drawdown(merged["governance_return"])
    base_dd = _max_drawdown(merged["baseline_return"])
    checks = {
        "minimum_non_overlapping_windows": len(complete) >= int(minimum_windows),
        "positive_window_ratio": bool(not complete.empty and (complete["excess_return"] > 0).mean() >= float(positive_window_ratio)),
        "aggregate_net_excess_positive": float((1 + merged["governance_return"]).prod() - (1 + merged["baseline_return"]).prod()) > 0,
        "max_drawdown_not_worse_than_budget": gov_dd - base_dd <= float(max_drawdown_worsening),
        "bootstrap_90pct_lower_bound_positive": bool(pd.notna(interval[0]) and interval[0] > 0),
    }
    return {
        "eligible_for_phase_two": all(checks.values()),
        "checks": checks,
        "bootstrap_90pct_interval": interval,
        "governance_max_drawdown": gov_dd,
        "baseline_max_drawdown": base_dd,
        "window_report": windows,
    }


def _daily_return_frame(frame, output_col):
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if "daily_return" in data.columns:
        values = pd.to_numeric(data["daily_return"], errors="coerce")
    elif "liquidatable_nav" in data.columns:
        values = pd.to_numeric(data["liquidatable_nav"], errors="coerce").pct_change(fill_method=None)
    else:
        raise ValueError("Daily frame must contain daily_return or liquidatable_nav")
    return pd.DataFrame({"date": data["date"], output_col: values}).dropna()


def _max_drawdown(returns):
    nav = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    return float(((nav.cummax() - nav) / nav.cummax()).max()) if not nav.empty else 0.0


def probability_of_backtest_overfitting(strategy_returns: pd.DataFrame, *, blocks: int = 8) -> dict:
    """Estimate CSCV/PBO from time-ordered strategy-return blocks."""
    data = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if data.shape[1] < 2:
        raise ValueError("PBO requires at least two candidate strategies")
    if int(blocks) < 4 or int(blocks) % 2:
        raise ValueError("PBO blocks must be an even integer >= 4")
    if len(data) < int(blocks):
        raise ValueError("PBO requires at least one row per block")
    partitions = [
        data.iloc[indexes].copy()
        for indexes in np.array_split(np.arange(len(data)), int(blocks))
        if len(indexes)
    ]
    logits = []
    for train_indexes in combinations(range(len(partitions)), len(partitions) // 2):
        train_set = set(train_indexes)
        train = pd.concat([partitions[index] for index in train_indexes], ignore_index=True)
        test = pd.concat([partitions[index] for index in range(len(partitions)) if index not in train_set], ignore_index=True)
        train_scores = (1.0 + train.fillna(0.0)).prod() - 1.0
        winner = str(train_scores.idxmax())
        test_scores = (1.0 + test.fillna(0.0)).prod() - 1.0
        rank_pct = float(test_scores.rank(pct=True, method="average").loc[winner])
        rank_pct = min(max(rank_pct, 1e-6), 1.0 - 1e-6)
        logits.append(float(np.log(rank_pct / (1.0 - rank_pct))))
    return {
        "pbo": float(np.mean(np.asarray(logits) < 0.0)),
        "cscv_combinations": len(logits),
        "median_test_rank_logit": float(np.median(logits)),
    }
