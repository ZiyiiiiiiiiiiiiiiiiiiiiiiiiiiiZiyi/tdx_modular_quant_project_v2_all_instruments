"""Cross-month stability diagnostics for the monthly LightGBM hybrid."""
from __future__ import annotations

import numpy as np
import pandas as pd


ML_STABILITY_VERSION = "monthly_lgbm_stability_v1"


def build_insufficient_ml_stability_reports(reason: str) -> dict[str, pd.DataFrame]:
    detail = str(reason or "monthly_training_history_unavailable")
    return {
        "governance_failure_lab_ml_stability_summary": pd.DataFrame([{
            "attempted_month_count": 0, "trained_model_month_count": 0,
            "evidence_status": "insufficient_model_months", "production_eligible": False,
            "detail": detail, "ml_stability_version": ML_STABILITY_VERSION,
        }]),
        "governance_failure_lab_ml_stability_monthly": pd.DataFrame(),
        "governance_failure_lab_ml_stability_features": pd.DataFrame(),
    }


def build_monthly_lgbm_stability_reports(
    training_audit: pd.DataFrame,
    feature_diagnostics: pd.DataFrame,
    *,
    minimum_model_months: int = 3,
    maximum_importance_hhi: float = 0.50,
    minimum_ic_sign_share: float = 0.67,
) -> dict[str, pd.DataFrame]:
    """Summarize model availability, IC signs, weights and feature concentration."""
    if int(minimum_model_months) < 2:
        raise ValueError("minimum_model_months must be at least two")
    required_training = {"training_month", "status"}
    required_features = {
        "model_month", "feature", "validation_feature_rank_ic_mean",
        "gain_importance_share", "ml_weight",
    }
    missing_training = sorted(required_training - set(training_audit.columns))
    missing_features = sorted(required_features - set(feature_diagnostics.columns))
    if missing_training:
        raise ValueError(f"training stability audit missing columns: {missing_training}")
    if not feature_diagnostics.empty and missing_features:
        raise ValueError(f"feature stability audit missing columns: {missing_features}")

    training = training_audit.copy()
    diagnostics = feature_diagnostics.copy()
    attempted_months = int(training["training_month"].astype(str).nunique())
    validation_ic = pd.to_numeric(
        training.get(
            "validation_rank_ic_mean",
            pd.Series(float("nan"), index=training.index, dtype=float),
        ),
        errors="coerce",
    )
    trained = training[validation_ic.notna()].copy()
    trained_months = int(trained["training_month"].astype(str).nunique())
    month_rows = []
    if not diagnostics.empty:
        for month, group in diagnostics.groupby("model_month", sort=True):
            shares = pd.to_numeric(group["gain_importance_share"], errors="coerce").fillna(0.0).clip(lower=0.0)
            total = shares.sum()
            shares = shares / total if total > 0 else shares
            month_rows.append({
                "model_month": str(month),
                "feature_count": int(group["feature"].nunique()),
                "importance_hhi": float(np.square(shares).sum()) if total > 0 else np.nan,
                "top_feature_importance_share": float(shares.max()) if total > 0 else np.nan,
                "ml_weight": float(pd.to_numeric(group["ml_weight"], errors="coerce").median()),
                "positive_feature_ic_share": float(
                    (pd.to_numeric(group["validation_feature_rank_ic_mean"], errors="coerce") > 0).mean()
                ),
                "ml_stability_version": ML_STABILITY_VERSION,
            })
    monthly = pd.DataFrame(month_rows)
    feature_rows = []
    if not diagnostics.empty:
        for feature, group in diagnostics.groupby("feature", sort=True):
            ic = pd.to_numeric(group["validation_feature_rank_ic_mean"], errors="coerce").dropna()
            importance = pd.to_numeric(group["gain_importance_share"], errors="coerce").dropna()
            nonzero = ic[ic.ne(0.0)]
            sign_share = max(float((nonzero > 0).mean()), float((nonzero < 0).mean())) if len(nonzero) else np.nan
            feature_rows.append({
                "feature": str(feature), "model_month_count": int(group["model_month"].astype(str).nunique()),
                "mean_validation_feature_rank_ic": float(ic.mean()) if len(ic) else np.nan,
                "ic_sign_consistency_share": sign_share,
                "mean_gain_importance_share": float(importance.mean()) if len(importance) else np.nan,
                "active_importance_month_share": float((importance > 0.0).mean()) if len(importance) else np.nan,
                "sign_stable": bool(np.isfinite(sign_share) and sign_share >= float(minimum_ic_sign_share)),
                "ml_stability_version": ML_STABILITY_VERSION,
            })
    feature_summary = pd.DataFrame(feature_rows)

    status = "insufficient_model_months"
    if trained_months >= int(minimum_model_months) and len(monthly) >= int(minimum_model_months):
        ic = pd.to_numeric(trained["validation_rank_ic_mean"], errors="coerce").dropna()
        positive_share = float((ic > 0).mean()) if len(ic) else np.nan
        worst_hhi = float(monthly["importance_hhi"].max())
        if positive_share < float(minimum_ic_sign_share):
            status = "unstable_validation_ic_sign"
        elif worst_hhi > float(maximum_importance_hhi):
            status = "unstable_feature_concentration"
        else:
            status = "cross_month_stability_pass"
    else:
        positive_share = np.nan
        worst_hhi = float(monthly["importance_hhi"].max()) if not monthly.empty else np.nan
    weights = pd.to_numeric(monthly.get("ml_weight", pd.Series(dtype=float)), errors="coerce").dropna()
    summary = pd.DataFrame([{
        "attempted_month_count": attempted_months, "trained_model_month_count": trained_months,
        "minimum_model_months": int(minimum_model_months),
        "validation_ic_positive_month_share": positive_share,
        "maximum_monthly_importance_hhi": worst_hhi,
        "mean_ml_weight": float(weights.mean()) if len(weights) else np.nan,
        "ml_weight_standard_deviation": float(weights.std(ddof=0)) if len(weights) else np.nan,
        "evidence_status": status, "production_eligible": status == "cross_month_stability_pass",
        "ml_stability_version": ML_STABILITY_VERSION,
    }])
    return {
        "governance_failure_lab_ml_stability_summary": summary,
        "governance_failure_lab_ml_stability_monthly": monthly,
        "governance_failure_lab_ml_stability_features": feature_summary,
    }
