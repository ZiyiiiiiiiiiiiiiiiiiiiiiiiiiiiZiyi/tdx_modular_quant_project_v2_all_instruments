"""Decision-council timestamp watermark and split audit."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_TRAIN_EMBARGO_PERIODS, GOVERNANCE_TRAIN_PURGE_PERIODS


def audit_timestamp_watermarks(
    feature_df: pd.DataFrame,
    *,
    decision_col: str = "decision_date",
    available_col: str = "feature_available_at",
    label_start_col: str = "label_window_start",
) -> pd.DataFrame:
    required = {decision_col, available_col, label_start_col}
    missing = sorted(required - set(feature_df.columns))
    if missing:
        return pd.DataFrame([{"check": "timestamp_columns", "status": "failed", "detail": f"missing={missing}"}])
    data = feature_df[list(required)].copy()
    for col in required:
        data[col] = pd.to_datetime(data[col], errors="coerce")
    feature_late = data[available_col].isna() | data[decision_col].isna() | (data[available_col] > data[decision_col])
    label_not_future = data[label_start_col].isna() | data[decision_col].isna() | (data[label_start_col] <= data[decision_col])
    return pd.DataFrame(
        [
            {"check": "feature_available_at_lte_decision_date", "status": "passed" if not feature_late.any() else "failed", "detail": f"invalid_rows={int(feature_late.sum())}"},
            {"check": "label_window_start_gt_decision_date", "status": "passed" if not label_not_future.any() else "failed", "detail": f"invalid_rows={int(label_not_future.sum())}"},
        ]
    )


def validate_governance_split(purge_periods: int, embargo_periods: int, max_label_horizon: int = 20) -> list[str]:
    failures = []
    if purge_periods < max(max_label_horizon, GOVERNANCE_TRAIN_PURGE_PERIODS):
        failures.append("purge_periods must cover the maximum governance label horizon")
    if embargo_periods < GOVERNANCE_TRAIN_EMBARGO_PERIODS:
        failures.append("embargo_periods must be at least the governance embargo minimum")
    return failures


def audit_training_window_boundaries(
    splits: pd.DataFrame,
    *,
    label_end_col: str = "train_label_window_end",
    validation_start_col: str = "validation_start",
    embargo_periods: int = GOVERNANCE_TRAIN_EMBARGO_PERIODS,
) -> pd.DataFrame:
    """Reject validation splits whose training labels cross the embargo boundary."""
    required = {label_end_col, validation_start_col}
    missing = sorted(required - set(splits.columns))
    if missing:
        return pd.DataFrame([{"check": "training_window_columns", "status": "failed", "detail": f"missing={missing}"}])
    data = splits[[label_end_col, validation_start_col]].copy()
    data[label_end_col] = pd.to_datetime(data[label_end_col], errors="coerce")
    data[validation_start_col] = pd.to_datetime(data[validation_start_col], errors="coerce")
    boundary = data[validation_start_col] - pd.offsets.BDay(int(embargo_periods))
    invalid = data[label_end_col].isna() | data[validation_start_col].isna() | (data[label_end_col] >= boundary)
    return pd.DataFrame(
        [
            {
                "check": "train_label_window_end_lt_validation_start_minus_embargo",
                "status": "passed" if not invalid.any() else "failed",
                "detail": f"invalid_rows={int(invalid.sum())}",
            }
        ]
    )
