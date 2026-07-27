"""Local-linear regression discontinuity with balance and density checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.causal.common import normal_ci, ols


RDD_VERSION = "local_linear_rdd_v1"


def build_rdd_audit(
    frame: pd.DataFrame,
    *,
    running_column: str,
    outcome_column: str,
    cutoff: float,
    bandwidth: float,
    covariate_columns=(),
    minimum_side_observations: int = 20,
    maximum_density_ratio: float = 2.0,
) -> pd.DataFrame:
    required = {running_column, outcome_column, *covariate_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"RDD frame missing columns: {missing}")
    data = frame.loc[:, list(required)].apply(pd.to_numeric, errors="coerce").dropna()
    centered = data[running_column] - float(cutoff)
    local = data[centered.abs().le(float(bandwidth))].copy()
    x_centered = local[running_column] - float(cutoff)
    treated = x_centered.ge(0.0).astype(float)
    left_count, right_count = int((treated == 0).sum()), int((treated == 1).sum())
    if min(left_count, right_count) < int(minimum_side_observations):
        return _insufficient("minimum observations per cutoff side not met", left_count, right_count)
    x = np.column_stack([np.ones(len(local)), treated, x_centered, treated * x_centered])
    beta, _, covariance, _ = ols(local[outcome_column], x)
    effect = float(beta[1])
    se = float(np.sqrt(max(covariance[1, 1], 0.0)))
    lower, upper = normal_ci(effect, se)
    density_ratio = max(left_count, right_count) / max(min(left_count, right_count), 1)
    balance_max = 0.0
    for column in covariate_columns:
        scale = float(local[column].std(ddof=1))
        difference = float(local.loc[treated.eq(1), column].mean() - local.loc[treated.eq(0), column].mean())
        balance_max = max(balance_max, abs(difference / scale) if scale > 0.0 else 0.0)
    design_pass = density_ratio <= float(maximum_density_ratio) and balance_max <= 0.25
    return pd.DataFrame([{
        "observations": len(local), "left_count": left_count, "right_count": right_count,
        "cutoff": cutoff, "bandwidth": bandwidth, "local_treatment_effect": effect,
        "standard_error": se, "ci_lower": lower, "ci_upper": upper,
        "density_count_ratio": density_ratio, "maximum_covariate_standardized_gap": balance_max,
        "manipulation_balance_pass": design_pass,
        "evidence_status": "rdd_design_pass" if design_pass else "rdd_design_failed",
        "causal_grade": "C-A" if design_pass else "C-X", "rdd_version": RDD_VERSION,
    }])


def _insufficient(reason, left, right):
    return pd.DataFrame([{
        "left_count": left, "right_count": right, "evidence_status": "insufficient_design",
        "detail": reason, "causal_grade": "C-U", "rdd_version": RDD_VERSION,
    }])
