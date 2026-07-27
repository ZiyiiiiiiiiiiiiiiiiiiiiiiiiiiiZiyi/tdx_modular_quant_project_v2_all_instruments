"""Product checks for monthly LightGBM cross-month stability."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.ml_stability_audit import build_monthly_lgbm_stability_reports


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture(ics, concentrated=False):
    months = [f"2024-{month:02d}" for month in range(1, len(ics) + 1)]
    training = pd.DataFrame({"training_month": months, "status": "calibrated", "validation_rank_ic_mean": ics})
    rows = []
    for month, model_ic in zip(months, ics):
        for index, feature in enumerate(("strict", "timing", "risk", "orderflow")):
            share = .85 if concentrated and index == 0 else (.05 if concentrated else .25)
            rows.append({
                "model_month": month, "feature": feature,
                "validation_feature_rank_ic_mean": model_ic * (1 if index < 3 else -1),
                "gain_importance_share": share, "ml_weight": .2,
            })
    return training, pd.DataFrame(rows)


def main():
    training, diagnostics = fixture([.05, .04, .06, .03])
    before = diagnostics.copy(deep=True)
    stable = build_monthly_lgbm_stability_reports(training, diagnostics)
    check(stable["governance_failure_lab_ml_stability_summary"].iloc[0]["evidence_status"] == "cross_month_stability_pass", "stable planted monthly models pass")
    check(diagnostics.equals(before), "stability audit does not mutate diagnostics")

    alternating, alternating_diag = fixture([.05, -.04, .06, -.03])
    unstable = build_monthly_lgbm_stability_reports(alternating, alternating_diag)
    check(unstable["governance_failure_lab_ml_stability_summary"].iloc[0]["evidence_status"] == "unstable_validation_ic_sign", "alternating validation IC signs are rejected")

    concentrated, concentrated_diag = fixture([.05, .04, .06], concentrated=True)
    concentration = build_monthly_lgbm_stability_reports(concentrated, concentrated_diag)
    check(concentration["governance_failure_lab_ml_stability_summary"].iloc[0]["evidence_status"] == "unstable_feature_concentration", "single-feature importance concentration is rejected")

    short, short_diag = fixture([.05, .04])
    insufficient = build_monthly_lgbm_stability_reports(short, short_diag)
    check(insufficient["governance_failure_lab_ml_stability_summary"].iloc[0]["evidence_status"] == "insufficient_model_months", "two monthly models fail closed")
    cold_start = pd.DataFrame({
        "training_month": ["2024-01"],
        "status": ["insufficient_history_dates"],
    })
    cold = build_monthly_lgbm_stability_reports(cold_start, pd.DataFrame())
    cold_summary = cold["governance_failure_lab_ml_stability_summary"].iloc[0]
    check(cold_summary["trained_model_month_count"] == 0, "cold-start audit accepts a missing validation IC column")
    check(cold_summary["evidence_status"] == "insufficient_model_months", "cold-start audit fails closed instead of crashing")
    print("[PASS] monthly LightGBM stability product verification completed")


if __name__ == "__main__":
    main()
