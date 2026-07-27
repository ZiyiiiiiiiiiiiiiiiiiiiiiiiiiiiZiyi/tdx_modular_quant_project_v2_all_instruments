"""Deterministic permutation and future-to-past negative controls."""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd


NEGATIVE_CONTROL_VERSION = "causal_negative_controls_v1"


def build_negative_control_audit(
    frame: pd.DataFrame,
    *,
    factor_column: str,
    outcome_column: str,
    date_column: str,
    permutation_samples: int = 500,
    alpha: float = 0.10,
) -> pd.DataFrame:
    required = {factor_column, outcome_column, date_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"negative-control frame missing columns: {missing}")
    data = frame.loc[:, list(required)].copy()
    data[factor_column] = pd.to_numeric(data[factor_column], errors="coerce")
    data[outcome_column] = pd.to_numeric(data[outcome_column], errors="coerce")
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce")
    data = data.dropna().sort_values(date_column)
    if len(data) < 20:
        return pd.DataFrame([{
            "evidence_status": "insufficient_observations", "negative_control_pass": False,
            "negative_control_version": NEGATIVE_CONTROL_VERSION,
        }])
    observed = _corr(data[factor_column], data[outcome_column])
    past_outcome = data[outcome_column].shift(1)
    future_to_past = _corr(data[factor_column], past_outcome)
    rng = np.random.default_rng(_seed(factor_column, outcome_column, len(data)))
    permuted = []
    values = data[factor_column].to_numpy(float)
    outcome = data[outcome_column].to_numpy(float)
    for _ in range(int(permutation_samples)):
        permuted.append(_corr(pd.Series(rng.permutation(values)), pd.Series(outcome)))
    p_value = float((1 + np.sum(np.abs(permuted) >= abs(observed))) / (len(permuted) + 1))
    future_past_null = not np.isfinite(future_to_past) or abs(future_to_past) < max(abs(observed), 0.05)
    passed = bool(p_value <= float(alpha) and future_past_null)
    return pd.DataFrame([{
        "observed_correlation": observed, "permutation_p_value": p_value,
        "future_factor_to_past_outcome_correlation": future_to_past,
        "future_to_past_null_pass": future_past_null,
        "negative_control_pass": passed,
        "evidence_status": "negative_controls_pass" if passed else "negative_controls_failed",
        "negative_control_version": NEGATIVE_CONTROL_VERSION,
    }])


def _corr(left, right):
    pair = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(pair) < 3 or pair["left"].nunique() < 2 or pair["right"].nunique() < 2:
        return np.nan
    return float(pair["left"].corr(pair["right"], method="spearman"))


def _seed(*parts):
    text = "|".join(map(str, parts))
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
