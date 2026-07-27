"""Purged walk-forward and one-standard-error selection contracts."""
from __future__ import annotations

import math
import pandas as pd


def purged_walk_forward_splits(dates, *, validation_days: int, purge_days: int, minimum_train_days: int):
    unique = pd.Index(sorted(pd.to_datetime(pd.Series(dates).dropna().unique())))
    valid = int(validation_days)
    purge = int(purge_days)
    minimum = int(minimum_train_days)
    if min(valid, minimum) <= 0 or purge < 0:
        raise ValueError("validation/minimum train must be positive and purge non-negative")
    splits = []
    start = minimum + purge
    for validation_start in range(start, len(unique), valid):
        validation_end = min(validation_start + valid, len(unique))
        train_end = validation_start - purge
        if train_end < minimum:
            continue
        splits.append((unique[:train_end], unique[validation_start:validation_end]))
    return splits


def one_standard_error_choice(results: pd.DataFrame, *, score_col="score_mean", se_col="score_se", complexity_col="complexity"):
    data = results.dropna(subset=[score_col, se_col, complexity_col]).copy()
    if data.empty:
        raise ValueError("no valid model-selection results")
    best = data.sort_values([score_col, complexity_col], ascending=[False, True]).iloc[0]
    floor = float(best[score_col]) - max(float(best[se_col]), 0.0)
    eligible = data[pd.to_numeric(data[score_col], errors="coerce").ge(floor)]
    return eligible.sort_values([complexity_col, score_col], ascending=[True, False]).iloc[0]


def cost_aware_rank_objective(*, ndcg: float, turnover: float, cost_rate: float, instability: float, complexity: float,
                              lambda_turnover: float, lambda_instability: float, lambda_complexity: float) -> float:
    values = (ndcg, turnover, cost_rate, instability, complexity)
    if not all(math.isfinite(float(value)) for value in values):
        return float("nan")
    return float(ndcg - lambda_turnover * turnover * cost_rate - lambda_instability * instability - lambda_complexity * complexity)
