"""Probability calibration diagnostics and conservative Platt scaling."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


@dataclass(frozen=True)
class CalibrationMetrics:
    brier_score: float
    expected_calibration_error: float
    sample_count: int
    bin_count: int


def calibration_table(
    probabilities,
    outcomes,
    *,
    bins: int = 10,
) -> pd.DataFrame:
    data = pd.DataFrame(
        {
            "probability": pd.to_numeric(pd.Series(probabilities), errors="coerce"),
            "outcome": pd.to_numeric(pd.Series(outcomes), errors="coerce"),
        }
    ).dropna()
    data = data[data["outcome"].isin([0, 1])]
    if data.empty:
        return pd.DataFrame(
            columns=[
                "bin",
                "count",
                "mean_probability",
                "actual_win_rate",
                "absolute_gap",
            ]
        )
    data["probability"] = data["probability"].clip(0.0, 1.0)
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    data["bin"] = pd.cut(
        data["probability"],
        bins=edges,
        include_lowest=True,
        duplicates="drop",
    )
    table = (
        data.groupby("bin", observed=True)
        .agg(
            count=("outcome", "size"),
            mean_probability=("probability", "mean"),
            actual_win_rate=("outcome", "mean"),
        )
        .reset_index()
    )
    table["absolute_gap"] = (
        table["mean_probability"] - table["actual_win_rate"]
    ).abs()
    table["bin"] = table["bin"].astype(str)
    return table


def calibration_metrics(probabilities, outcomes, *, bins: int = 10) -> CalibrationMetrics:
    probability = pd.to_numeric(pd.Series(probabilities), errors="coerce")
    outcome = pd.to_numeric(pd.Series(outcomes), errors="coerce")
    valid = probability.notna() & outcome.isin([0, 1])
    probability = probability[valid].clip(0.0, 1.0)
    outcome = outcome[valid].astype(float)
    if probability.empty:
        return CalibrationMetrics(float("nan"), float("nan"), 0, 0)
    table = calibration_table(probability, outcome, bins=bins)
    brier = float(np.mean(np.square(probability.to_numpy() - outcome.to_numpy())))
    ece = float(
        (
            table["absolute_gap"]
            * table["count"]
            / max(int(table["count"].sum()), 1)
        ).sum()
    )
    return CalibrationMetrics(brier, ece, len(probability), len(table))


def fit_platt_scaler(raw_scores, outcomes, *, minimum_samples: int = 100):
    score = pd.to_numeric(pd.Series(raw_scores), errors="coerce")
    outcome = pd.to_numeric(pd.Series(outcomes), errors="coerce")
    valid = score.notna() & outcome.isin([0, 1])
    score = score[valid]
    outcome = outcome[valid].astype(int)
    if len(score) < int(minimum_samples) or outcome.nunique() < 2:
        return None
    model = LogisticRegression(C=1.0, solver="lbfgs")
    model.fit(score.to_numpy().reshape(-1, 1), outcome.to_numpy())
    return model


def apply_platt_scaler(model, raw_scores) -> pd.Series:
    score = pd.to_numeric(pd.Series(raw_scores), errors="coerce")
    result = pd.Series(np.nan, index=score.index, dtype=float)
    valid = score.notna()
    if model is not None and valid.any():
        result.loc[valid] = model.predict_proba(
            score.loc[valid].to_numpy().reshape(-1, 1)
        )[:, 1]
    return result


def parameter_stability_report(
    window_parameters: pd.DataFrame,
    *,
    parameter_columns: list[str],
    max_relative_range: float = 0.50,
) -> pd.DataFrame:
    rows = []
    for column in parameter_columns:
        values = pd.to_numeric(window_parameters[column], errors="coerce").dropna()
        if values.empty:
            rows.append(
                {
                    "parameter": column,
                    "window_count": 0,
                    "relative_range": np.nan,
                    "stable": False,
                }
            )
            continue
        denominator = max(abs(float(values.median())), 1e-12)
        relative_range = float((values.max() - values.min()) / denominator)
        rows.append(
            {
                "parameter": column,
                "window_count": int(len(values)),
                "relative_range": relative_range,
                "stable": bool(relative_range <= float(max_relative_range)),
            }
        )
    return pd.DataFrame(rows)
