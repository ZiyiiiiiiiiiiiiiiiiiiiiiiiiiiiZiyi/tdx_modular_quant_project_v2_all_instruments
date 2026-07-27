"""Product checks for the fail-closed unified research gate."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.research_gate import build_unified_research_gate


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def passing_reports():
    return {
        "governance_runtime_integrity_audit": pd.DataFrame({"passed": [True, True]}),
        "governance_failure_lab_overview": pd.DataFrame({"gate_pass": [True, True, True]}),
        "governance_failure_lab_competing_risk_summary": pd.DataFrame({"evidence_status": ["high_score_reduces_loss_incidence"]}),
        "governance_failure_lab_adversarial_drift_summary": pd.DataFrame({"evidence_status": ["no_material_drift_detected"]}),
        "governance_failure_lab_ml_stability_summary": pd.DataFrame({"evidence_status": ["cross_month_stability_pass"]}),
        "governance_failure_lab_cost_capacity_summary": pd.DataFrame({"evidence_status": ["cost_capacity_stress_pass"], "impact_model_calibrated": [True]}),
        "governance_overfit_overview": pd.DataFrame({"gate_pass": [True, True, True]}),
        "governance_monthly_lgbm_iteration_metrics": pd.DataFrame({
            "dataset": ["train", "outer_valid", "train", "outer_valid"],
            "model_purpose": ["short_entry", "short_entry", "medium_hold", "medium_hold"],
            "boosting_iteration": [1, 1, 1, 1], "value": [.7, .6, .7, .6],
        }),
        "governance_monthly_lgbm_treatment_effect": pd.DataFrame({
            "ml_incremental_top_k_net_alpha": [.01, .012, .009, .011, .013, .008],
            "treated_candidate_count": [2, 2, 2, 2, 2, 2],
        }),
    }


def main():
    detail, summary = build_unified_research_gate(passing_reports(), pit_runtime_state="available", pit_level2_runtime_state="available", temporal_isolation_pass=True, requires_monthly_ml=True)
    check(summary.iloc[0]["research_acceptance_pass"], "all independent research checks can pass")
    check(summary.iloc[0]["formal_production_acceptance_pass"], "formal PIT plus research evidence can pass production")
    check(not detail["changes_trading"].any(), "research gate remains diagnostics-only")

    reports = passing_reports()
    reports["governance_overfit_overview"] = pd.DataFrame({"gate_pass": [False, False, False]})
    _, failed = build_unified_research_gate(reports, pit_runtime_state="available", pit_level2_runtime_state="available", temporal_isolation_pass=True, requires_monthly_ml=True)
    check(not failed.iloc[0]["research_acceptance_pass"], "insufficient overfit evidence fails research acceptance")

    _, degraded = build_unified_research_gate(passing_reports(), pit_runtime_state="degraded", requires_monthly_ml=True)
    check(degraded.iloc[0]["research_acceptance_pass"], "PIT state does not rewrite factor/return evidence")
    check(not degraded.iloc[0]["formal_production_acceptance_pass"], "degraded PIT independently blocks formal production")

    inconclusive = passing_reports()
    inconclusive["governance_failure_lab_competing_risk_summary"] = pd.DataFrame({"evidence_status": ["inconclusive"]})
    _, inconclusive_summary = build_unified_research_gate(inconclusive, pit_runtime_state="available", requires_monthly_ml=True)
    check(not inconclusive_summary.iloc[0]["research_acceptance_pass"], "inconclusive competing-risk evidence no longer passes")

    missing = passing_reports()
    missing.pop("governance_failure_lab_cost_capacity_summary")
    _, missing_summary = build_unified_research_gate(missing, pit_runtime_state="available", requires_monthly_ml=False)
    check(not missing_summary.iloc[0]["research_acceptance_pass"], "missing required diagnostics fail closed")
    print("[PASS] unified research gate product verification completed")


if __name__ == "__main__":
    main()
