"""Independent runtime maturity states for governance diagnostics."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_REPUTATION_WARMUP_DAYS


def reputation_runtime_state(*, day_index: int, snapshot: pd.DataFrame | None) -> str:
    if day_index < int(GOVERNANCE_REPUTATION_WARMUP_DAYS):
        return "cold_start"
    if snapshot is None or snapshot.empty:
        return "degraded"
    activity = pd.to_numeric(snapshot.get("activity_ema"), errors="coerce").fillna(0.0)
    coverage = pd.to_numeric(snapshot.get("coverage_ema"), errors="coerce").fillna(0.0)
    if float(activity.mean()) < 0.10 or float(coverage.mean()) < 0.20:
        return "warming_up"
    return "calibrated"


def covariance_runtime_state(*, day_index: int, covariance_matrix: pd.DataFrame | None) -> str:
    if day_index < 20:
        return "cold_start"
    if covariance_matrix is None:
        return "degraded"
    if covariance_matrix.empty or len(covariance_matrix) < 3:
        return "warming_up"
    values = covariance_matrix.apply(pd.to_numeric, errors="coerce")
    if values.isna().all().all():
        return "degraded"
    return "calibrated" if day_index >= 60 else "warming_up"


def trade_accuracy_runtime_state(*, closed_trade_count: int) -> str:
    count = max(int(closed_trade_count), 0)
    if count < 5:
        return "cold_start"
    if count < 20:
        return "warming_up"
    return "calibrated"


def combined_runtime_maturity(
    *, probability_state: str, reputation_state: str, covariance_state: str,
    trade_accuracy_state: str, pit_state: str,
) -> str:
    states = {probability_state, reputation_state, covariance_state, trade_accuracy_state}
    if "degraded" in states or pit_state == "degraded":
        return "degraded"
    if "cold_start" in states:
        return "cold_start"
    if "warming_up" in states:
        return "warming_up"
    return "calibrated"
