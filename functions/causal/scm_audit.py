"""Synthetic-control and synthetic-DID diagnostics for one treated unit."""
from __future__ import annotations

import numpy as np
import pandas as pd


SCM_VERSION = "synthetic_control_sdid_v1"


def build_scm_audit(
    panel: pd.DataFrame,
    *,
    unit_column: str,
    date_column: str,
    outcome_column: str,
    treated_unit: str,
    treatment_date,
    maximum_pre_rmspe_ratio: float = 0.50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {unit_column, date_column, outcome_column}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"SCM panel missing columns: {missing}")
    data = panel.loc[:, list(required)].copy()
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce")
    data[outcome_column] = pd.to_numeric(data[outcome_column], errors="coerce")
    pivot = data.dropna().pivot_table(index=date_column, columns=unit_column, values=outcome_column, aggfunc="last").dropna()
    if treated_unit not in pivot or pivot.shape[1] < 3:
        return _insufficient("treated unit and at least two donors required"), pd.DataFrame()
    cutoff = pd.Timestamp(treatment_date)
    pre, post = pivot[pivot.index < cutoff], pivot[pivot.index >= cutoff]
    if len(pre) < 5 or len(post) < 2:
        return _insufficient("insufficient pre or post periods"), pd.DataFrame()
    donors = [column for column in pivot if str(column) != str(treated_unit)]
    x_pre = pre[donors].to_numpy(float)
    y_pre = pre[treated_unit].to_numpy(float)
    raw = np.linalg.lstsq(x_pre, y_pre, rcond=None)[0]
    weights = np.clip(raw, 0.0, None)
    weights = weights / weights.sum() if weights.sum() > 0.0 else np.repeat(1.0 / len(donors), len(donors))
    synthetic = pivot[donors].to_numpy(float) @ weights
    detail = pd.DataFrame({
        "date": pivot.index, "treated_outcome": pivot[treated_unit].to_numpy(float),
        "synthetic_outcome": synthetic,
    })
    detail["gap"] = detail["treated_outcome"] - detail["synthetic_outcome"]
    detail["post"] = detail["date"].ge(cutoff)
    pre_gap = detail.loc[~detail["post"], "gap"]
    post_gap = detail.loc[detail["post"], "gap"]
    pre_rmspe = float(np.sqrt(np.mean(np.square(pre_gap))))
    treated_scale = float(np.std(y_pre, ddof=1))
    ratio = pre_rmspe / treated_scale if treated_scale > 0.0 else np.inf
    scm_effect = float(post_gap.mean())
    sdid_effect = float(post_gap.mean() - pre_gap.mean())
    pass_fit = bool(np.isfinite(ratio) and ratio <= float(maximum_pre_rmspe_ratio))
    summary = pd.DataFrame([{
        "treated_unit": treated_unit, "donor_count": len(donors),
        "pre_periods": len(pre), "post_periods": len(post),
        "pre_rmspe": pre_rmspe, "pre_rmspe_to_treated_sd": ratio,
        "scm_effect": scm_effect, "synthetic_did_effect": sdid_effect,
        "donor_weights": "|".join(f"{name}:{weight:.8g}" for name, weight in zip(donors, weights)),
        "pre_fit_pass": pass_fit,
        "evidence_status": "scm_design_pass" if pass_fit else "scm_pre_fit_failed",
        "causal_grade": "C-B" if pass_fit else "C-X", "scm_version": SCM_VERSION,
    }])
    return summary, detail


def _insufficient(reason):
    return pd.DataFrame([{
        "evidence_status": "insufficient_design", "detail": reason,
        "causal_grade": "C-U", "scm_version": SCM_VERSION,
    }])
