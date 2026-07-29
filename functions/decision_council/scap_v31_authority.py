"""SCAP-V3.1 tiered trading authority without pseudo-probability fallbacks."""
from __future__ import annotations

import math

import pandas as pd


AUTHORITY_CONTRACT = "scap_v32_abcd_sizing_only_v1"


def attach_scap_v31_authority(
    candidates: pd.DataFrame,
    *,
    horizon_days: int = 10,
) -> pd.DataFrame:
    """Attach A/B/C/D authority and a cost-before decision return.

    A/B consume calibrated forecast evidence. C may only consume the existing
    PIT factor-family comparable-return distribution. D has no trading right.
    """
    data = candidates.copy()
    if data.empty:
        return data
    suffix = f"{max(int(horizon_days), 1)}d"
    required_evidence_column = (
        f"entry_calibration_effective_sample_size_{suffix}"
    )
    if required_evidence_column not in data.columns:
        legacy_return = pd.to_numeric(
            data.get(
                "scap_decision_expected_return",
                pd.Series(0.0, index=data.index),
            ),
            errors="coerce",
        ).fillna(0.0)
        legacy_utility = pd.to_numeric(
            data.get("scap_candidate_utility", pd.Series(0.0, index=data.index)),
            errors="coerce",
        ).fillna(0.0)
        allowed = legacy_return.gt(0.0) | legacy_utility.gt(0.0)
        data["scap_v31_authority_tier"] = allowed.map({True: "A", False: "D"})
        data["scap_v31_decision_expected_return"] = legacy_return
        data["scap_v31_max_lots"] = allowed.map({True: 2, False: 0}).astype(int)
        data["scap_v31_authority_contract"] = (
            AUTHORITY_CONTRACT + "|synthetic_compatibility"
        )
        data["scap_v31_authority_reason"] = allowed.map(
            {
                True: "synthetic_test_or_legacy_precomputed_authority",
                False: "missing_authority_evidence",
            }
        )
        return data
    n_eff = _numeric(data, f"entry_calibration_effective_sample_size_{suffix}")
    sessions = _numeric(data, f"entry_calibration_unique_session_count_{suffix}")
    rank_ic = _numeric(data, f"forecast_rank_ic_{suffix}")
    slope = _numeric(data, f"forecast_calibration_slope_{suffix}")
    drift = _numeric(data, f"forecast_drift_streak_{suffix}")
    state = data.get(
        f"entry_calibration_state_{suffix}",
        pd.Series("prior_only", index=data.index),
    ).astype(str)
    point = _numeric(data, "scap_expected_return_point")
    if point.isna().all():
        point = _numeric(data, "comparable_expected_alpha")
    cluster_se = _numeric(data, f"forecast_cluster_se_{suffix}").clip(lower=0.0)
    fallback_lcb = _numeric(data, "comparable_alpha_lcb")
    fallback_contract = data.get(
        "comparable_value_contract", pd.Series("", index=data.index)
    ).astype(str)

    direction_ok = rank_ic.gt(0.0) & slope.gt(0.0)
    nonnegative_direction = rank_ic.ge(0.0) & slope.ge(0.0)
    normalized_state = state.str.lower()
    stable = drift.lt(3.0) & ~normalized_state.eq("drifted")
    tier_a = (
        n_eff.ge(80.0)
        & sessions.ge(60.0)
        & direction_ok
        & stable
        & normalized_state.eq("calibrated")
    )
    tier_b = (
        ~tier_a
        & n_eff.ge(30.0)
        & sessions.ge(20.0)
        & nonnegative_direction
        & stable
        & normalized_state.isin({"calibrated", "recovering"})
    )
    tier_c = (
        ~tier_a
        & ~tier_b
        & fallback_lcb.gt(0.0)
        & fallback_contract.str.len().gt(0)
    )
    tier = pd.Series("D", index=data.index)
    tier.loc[tier_c] = "C"
    tier.loc[tier_b] = "B"
    tier.loc[tier_a] = "A"
    decision_return = pd.Series(0.0, index=data.index)
    decision_return.loc[tier_a] = (
        point.loc[tier_a] - 0.50 * cluster_se.loc[tier_a]
    )
    decision_return.loc[tier_b] = (
        point.loc[tier_b] - 0.25 * cluster_se.loc[tier_b]
    )
    decision_return.loc[tier_c] = fallback_lcb.loc[tier_c]
    negative_edge = decision_return.le(0.0)
    tier.loc[negative_edge] = "D"
    decision_return.loc[negative_edge] = 0.0

    data["scap_v31_authority_tier"] = tier
    data["scap_v31_decision_expected_return"] = decision_return
    data["scap_v31_max_lots"] = tier.map({"A": 2, "B": 1, "C": 1, "D": 0}).astype(int)
    data["scap_v32_current_authority_tier"] = tier
    data["scap_v32_authority_uncertainty_rank"] = tier.map(
        {"A": 0, "B": 1, "C": 2, "D": 3}
    ).astype(int)
    data["scap_v32_authority_role"] = "evidence_discount_and_starter_size_only"
    data["scap_v31_authority_contract"] = AUTHORITY_CONTRACT
    data["scap_v31_authority_reason"] = [
        _reason(t, ne, ss, ic, sl, ds)
        for t, ne, ss, ic, sl, ds in zip(
            tier, n_eff, sessions, rank_ic, slope, drift
        )
    ]
    return data


def _numeric(data: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(
        data.get(column, pd.Series(float("nan"), index=data.index)),
        errors="coerce",
    )


def _reason(tier, n_eff, sessions, rank_ic, slope, drift) -> str:
    if tier == "A":
        return "calibrated_a_positive_direction"
    if tier == "B":
        return "calibrated_b_exploration"
    if tier == "C":
        return "pit_factor_family_fallback_distribution"
    facts = (n_eff, sessions, rank_ic, slope, drift)
    if any(pd.notna(value) and math.isfinite(float(value)) for value in facts):
        return "insufficient_or_negative_calibration_evidence"
    return "missing_authority_evidence"
