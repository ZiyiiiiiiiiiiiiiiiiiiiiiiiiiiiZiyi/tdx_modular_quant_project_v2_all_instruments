"""Panel difference-in-differences with explicit pre-trend falsification."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.causal.common import normal_ci, ols


DID_VERSION = "panel_did_pretrend_v1"


def build_did_audit(
    panel: pd.DataFrame,
    *,
    unit_column: str,
    date_column: str,
    outcome_column: str,
    treated_column: str,
    post_column: str,
    pretrend_max_abs_t: float = 1.96,
) -> pd.DataFrame:
    required = {unit_column, date_column, outcome_column, treated_column, post_column}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"DID panel missing columns: {missing}")
    data = panel.loc[:, list(required)].copy()
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce")
    data[outcome_column] = pd.to_numeric(data[outcome_column], errors="coerce")
    data[treated_column] = data[treated_column].fillna(False).astype(bool)
    data[post_column] = data[post_column].fillna(False).astype(bool)
    data = data.dropna(subset=[date_column, outcome_column, unit_column])
    if data[treated_column].nunique() < 2 or data[post_column].nunique() < 2:
        return _insufficient("treated_and_control_pre_post_required", len(data))
    unit_dummies = pd.get_dummies(data[unit_column].astype(str), drop_first=True, dtype=float)
    date_dummies = pd.get_dummies(data[date_column].dt.strftime("%Y-%m-%d"), drop_first=True, dtype=float)
    treatment = (data[treated_column] & data[post_column]).astype(float).rename("treatment")
    x = pd.concat([pd.Series(1.0, index=data.index, name="intercept"), treatment, unit_dummies, date_dummies], axis=1)
    beta, _, covariance, _ = ols(data[outcome_column], x)
    effect = float(beta[1])
    se = float(np.sqrt(max(covariance[1, 1], 0.0)))
    lower, upper = normal_ci(effect, se)
    pre = data[~data[post_column]].copy()
    pretrend_t = _pretrend_t(pre, unit_column, date_column, outcome_column, treated_column)
    parallel = bool(np.isfinite(pretrend_t) and abs(pretrend_t) <= float(pretrend_max_abs_t))
    status = "did_design_pass" if parallel else "did_parallel_trend_failed"
    return pd.DataFrame([{
        "observations": len(data), "unit_count": data[unit_column].nunique(),
        "did_effect": effect, "standard_error": se,
        "ci_lower": lower, "ci_upper": upper, "pretrend_t_stat": pretrend_t,
        "parallel_trend_pass": parallel, "evidence_status": status,
        "causal_grade": "C-B" if parallel else "C-X", "did_version": DID_VERSION,
    }])


def _pretrend_t(data, unit, date, outcome, treated):
    dates = pd.Index(sorted(data[date].dropna().unique()))
    if len(dates) < 3:
        return np.nan
    date_number = data[date].map({value: index for index, value in enumerate(dates)}).astype(float)
    interaction = date_number * data[treated].astype(float)
    x = np.column_stack([np.ones(len(data)), date_number, data[treated].astype(float), interaction])
    beta, _, covariance, _ = ols(data[outcome], x)
    se = float(np.sqrt(max(covariance[3, 3], 0.0)))
    return float(beta[3] / se) if se > 0.0 else np.nan


def _insufficient(reason, observations):
    return pd.DataFrame([{
        "observations": int(observations), "evidence_status": "insufficient_design",
        "detail": reason, "causal_grade": "C-U", "did_version": DID_VERSION,
    }])
