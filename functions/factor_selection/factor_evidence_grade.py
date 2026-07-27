"""Separate predictive, causal, and data-readiness grades for factor candidates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


EVIDENCE_GRADE_VERSION = "factor_evidence_grade_v1"


@dataclass(frozen=True)
class EvidenceThresholds:
    minimum_coverage: float = 0.50
    minimum_ic_ir: float = 0.10
    minimum_positive_ic_ratio: float = 0.55
    minimum_cost_adjusted_spread: float = 0.0


def grade_factor_evidence(
    candidates: pd.DataFrame,
    *,
    thresholds: EvidenceThresholds = EvidenceThresholds(),
) -> pd.DataFrame:
    data = candidates.copy()
    for column, default in (
        ("coverage", 0.0), ("best_ic_ir", np.nan), ("ic_ir", np.nan),
        ("positive_ic_ratio", np.nan), ("best_cost_adjusted_top_bottom_spread", np.nan),
        ("cost_adjusted_top_bottom_spread", np.nan),
    ):
        if column not in data:
            data[column] = default
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if "temporal_isolation_pass" not in data:
        data["temporal_isolation_pass"] = False
    if "negative_control_pass" not in data:
        data["negative_control_pass"] = False
    if "pit_status" not in data:
        data["pit_status"] = "missing"
    if "causal_grade" not in data:
        data["causal_grade"] = "C-U"

    ic_ir = data["best_ic_ir"].fillna(data["ic_ir"])
    spread = data["best_cost_adjusted_top_bottom_spread"].fillna(data["cost_adjusted_top_bottom_spread"])
    hard = (
        data["temporal_isolation_pass"].eq(True)
        & data["negative_control_pass"].eq(True)
        & data["coverage"].fillna(0.0).ge(float(thresholds.minimum_coverage))
        & data["pit_status"].astype(str).isin(["formal", "research", "not_required"])
    )
    strong = (
        ic_ir.ge(float(thresholds.minimum_ic_ir))
        & data["positive_ic_ratio"].ge(float(thresholds.minimum_positive_ic_ratio))
        & spread.gt(float(thresholds.minimum_cost_adjusted_spread))
    )
    moderate = (
        ic_ir.gt(0.0)
        & data["positive_ic_ratio"].ge(0.50)
        & spread.ge(float(thresholds.minimum_cost_adjusted_spread))
    )
    data["hard_evidence_gate_pass"] = hard
    data["predictive_grade"] = "P-X"
    data.loc[hard & ~moderate, "predictive_grade"] = "P-C"
    data.loc[hard & moderate, "predictive_grade"] = "P-B"
    data.loc[hard & strong, "predictive_grade"] = "P-A"
    data["replacement_eligible"] = data["predictive_grade"].isin(["P-A", "P-B"])
    data["strict_alpha_eligible"] = (
        data["replacement_eligible"]
        & data["causal_grade"].astype(str).isin(["C-A", "C-B", "C-C"])
    )
    data["evidence_grade_version"] = EVIDENCE_GRADE_VERSION
    return data
