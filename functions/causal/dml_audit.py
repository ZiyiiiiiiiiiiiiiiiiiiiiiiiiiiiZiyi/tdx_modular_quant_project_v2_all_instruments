"""Cross-fitted partially-linear DML for continuous factor treatments."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.causal.common import normal_ci, ols


DML_VERSION = "cross_fitted_partial_linear_dml_v1"


def build_dml_audit(
    frame: pd.DataFrame,
    *,
    outcome_column: str,
    treatment_column: str,
    control_columns,
    fold_column: str,
    ridge: float = 1e-6,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    controls = tuple(control_columns)
    required = {outcome_column, treatment_column, fold_column, *controls}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"DML frame missing columns: {missing}")
    data = frame.loc[:, list(required)].copy()
    for column in (outcome_column, treatment_column, *controls):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna()
    folds = list(pd.unique(data[fold_column]))
    if len(folds) < 2 or len(data) < max(30, 5 * (len(controls) + 2)):
        return _insufficient("cross-fitting requires at least two folds and sufficient rows"), pd.DataFrame()
    residual_rows = []
    for fold in folds:
        train, test = data[data[fold_column].ne(fold)], data[data[fold_column].eq(fold)]
        x_train = np.column_stack([np.ones(len(train)), train.loc[:, controls].to_numpy(float)])
        x_test = np.column_stack([np.ones(len(test)), test.loc[:, controls].to_numpy(float)])
        beta_y, _, _, _ = ols(train[outcome_column], x_train, ridge=ridge)
        beta_d, _, _, _ = ols(train[treatment_column], x_train, ridge=ridge)
        residual_rows.append(pd.DataFrame({
            "fold": fold, "outcome_residual": test[outcome_column].to_numpy(float) - x_test @ beta_y,
            "treatment_residual": test[treatment_column].to_numpy(float) - x_test @ beta_d,
        }, index=test.index))
    residuals = pd.concat(residual_rows).sort_index()
    d = residuals["treatment_residual"].to_numpy(float)
    y = residuals["outcome_residual"].to_numpy(float)
    denominator = float(d @ d)
    if denominator <= 1e-12:
        return _insufficient("residualized treatment has no variation"), residuals.reset_index(drop=True)
    theta = float(d @ y / denominator)
    error = y - theta * d
    se = float(np.sqrt(np.sum(np.square(d * error)) / max(denominator ** 2, 1e-12)))
    lower, upper = normal_ci(theta, se)
    status = "dml_effect_evidence" if lower > 0.0 or upper < 0.0 else "dml_effect_inconclusive"
    summary = pd.DataFrame([{
        "observations": len(residuals), "fold_count": len(folds),
        "orthogonal_effect": theta, "standard_error": se,
        "ci_lower": lower, "ci_upper": upper,
        "evidence_status": status, "causal_grade": "C-C" if status == "dml_effect_evidence" else "C-U",
        "dml_version": DML_VERSION,
    }])
    return summary, residuals.reset_index(drop=True)


def _insufficient(reason):
    return pd.DataFrame([{
        "evidence_status": "insufficient_design", "detail": reason,
        "causal_grade": "C-U", "dml_version": DML_VERSION,
    }])
