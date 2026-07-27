"""Unified fail-closed research and formal-production acceptance gate."""
from __future__ import annotations

import pandas as pd


RESEARCH_GATE_VERSION = "governance_research_gate_v3_ml_treatment"


def build_unified_research_gate(
    reports: dict[str, pd.DataFrame],
    *,
    pit_runtime_state: str,
    requires_monthly_ml: bool,
    pit_level2_runtime_state: str = "degraded",
    temporal_isolation_pass: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combine independent diagnostics without changing trading decisions."""
    rows = []
    rows.append(_all_pass_check("runtime_integrity", reports.get("governance_runtime_integrity_audit"), "passed"))
    rows.append(_all_pass_check("failure_lab", reports.get("governance_failure_lab_overview"), "gate_pass"))
    rows.append(_status_check(
        "candidate_competing_risk", reports.get("governance_failure_lab_competing_risk_summary"),
        "evidence_status", {"high_score_reduces_loss_incidence"},
    ))
    rows.append(_status_check(
        "adversarial_drift", reports.get("governance_failure_lab_adversarial_drift_summary"),
        "evidence_status", {"no_material_drift_detected"},
    ))
    if requires_monthly_ml:
        rows.append(_status_check(
            "monthly_ml_stability", reports.get("governance_failure_lab_ml_stability_summary"),
            "evidence_status", {"cross_month_stability_pass"},
        ))
        rows.append(_learning_curve_check(reports.get("governance_monthly_lgbm_iteration_metrics")))
        rows.append(_ml_treatment_check(reports.get("governance_monthly_lgbm_treatment_effect")))
    else:
        rows.append(_row("monthly_ml_stability", True, "not_applicable_non_ml_strategy"))
        rows.append(_row("monthly_ml_learning_curve", True, "not_applicable_non_ml_strategy"))
        rows.append(_row("monthly_ml_treatment_effect", True, "not_applicable_non_ml_strategy"))
    rows.append(_status_check(
        "cost_capacity", reports.get("governance_failure_lab_cost_capacity_summary"),
        "evidence_status", {"cost_capacity_stress_pass"},
    ))
    rows.append(_all_pass_check("multiple_testing_overfit", reports.get("governance_overfit_overview"), "gate_pass"))
    pit_pass = str(pit_runtime_state).strip().lower() == "available"
    pit_level2_pass = str(pit_level2_runtime_state).strip().lower() == "available"
    rows.append(_row("pit_level1_formal", pit_pass, str(pit_runtime_state or "missing")))
    rows.append(_row("pit_level2_formal", pit_level2_pass, str(pit_level2_runtime_state or "missing")))
    rows.append(_row("factor_temporal_isolation_formal", bool(temporal_isolation_pass), str(bool(temporal_isolation_pass)).lower()))
    cost = reports.get("governance_failure_lab_cost_capacity_summary")
    calibrated = bool(
        cost is not None and not cost.empty and "impact_model_calibrated" in cost
        and cost["impact_model_calibrated"].fillna(False).astype(bool).all()
    )
    rows.append(_row("impact_model_calibrated_formal", calibrated, "calibrated" if calibrated else "uncalibrated_or_missing"))
    detail = pd.DataFrame(rows)
    detail["changes_trading"] = False
    detail["research_gate_version"] = RESEARCH_GATE_VERSION
    formal_only = {
        "pit_level1_formal", "pit_level2_formal", "factor_temporal_isolation_formal",
        "impact_model_calibrated_formal",
    }
    research_checks = detail[~detail["check"].isin(formal_only)]
    formal_checks = detail[detail["check"].isin(formal_only)]
    research_pass = bool(not research_checks.empty and research_checks["gate_pass"].all())
    production_pass = bool(research_pass and not formal_checks.empty and formal_checks["gate_pass"].all())
    summary = pd.DataFrame([{
        "research_acceptance_pass": research_pass,
        "factor_return_effect_acceptance": "pass" if research_pass else "fail",
        "formal_production_acceptance_pass": production_pass,
        "formal_production_acceptance": "pass" if production_pass else "fail",
        "failed_research_check_count": int((~research_checks["gate_pass"]).sum()),
        "pit_runtime_state": str(pit_runtime_state),
        "pit_level2_runtime_state": str(pit_level2_runtime_state),
        "temporal_isolation_pass": bool(temporal_isolation_pass),
        "changes_trading": False,
        "research_gate_version": RESEARCH_GATE_VERSION,
    }])
    return detail, summary


def _all_pass_check(name, frame, column):
    if frame is None or frame.empty or column not in frame.columns:
        return _row(name, False, "missing_or_insufficient")
    values = frame[column].fillna(False).astype(bool)
    return _row(name, bool(values.all()), f"passed={int(values.sum())}/{len(values)}")


def _status_check(name, frame, column, accepted):
    if frame is None or frame.empty or column not in frame.columns:
        return _row(name, False, "missing_or_insufficient")
    statuses = frame[column].fillna("missing").astype(str)
    passed = bool(statuses.isin(accepted).all())
    return _row(name, passed, "|".join(sorted(statuses.unique())))


def _row(name, passed, detail):
    return {"check": name, "gate_pass": bool(passed), "status": "pass" if passed else "fail", "detail": str(detail)}


def _learning_curve_check(frame):
    if frame is None or frame.empty or not {"dataset", "boosting_iteration", "value"}.issubset(frame.columns):
        return _row("monthly_ml_learning_curve", False, "missing_iteration_metrics")
    datasets = set(frame["dataset"].dropna().astype(str))
    purposes = set(frame.get("model_purpose", pd.Series("short_entry", index=frame.index)).dropna().astype(str))
    passed = {"train", "outer_valid"}.issubset(datasets) and {"short_entry", "medium_hold"}.issubset(purposes)
    return _row(
        "monthly_ml_learning_curve", passed,
        f"datasets={'|'.join(sorted(datasets))};purposes={'|'.join(sorted(purposes))}",
    )


def _ml_treatment_check(frame):
    column = "ml_incremental_top_k_net_alpha"
    if frame is None or frame.empty or column not in frame.columns:
        return _row("monthly_ml_treatment_effect", False, "missing_matured_treatment_effect")
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    treated = pd.to_numeric(
        frame.get("treated_candidate_count", pd.Series(0, index=frame.index)), errors="coerce"
    ).fillna(0).gt(0)
    values = pd.to_numeric(frame.loc[treated, column], errors="coerce").dropna()
    if len(values) < 5:
        return _row("monthly_ml_treatment_effect", False, f"insufficient_changed_days={len(values)}")
    mean = float(values.mean())
    from functions.decision_council.monthly_lgbm_hybrid import _hac_standard_error
    se = _hac_standard_error(values, max_lag=min(5, len(values) - 1))
    lower_bound = mean - 1.2815515655446004 * se
    return _row(
        "monthly_ml_treatment_effect", lower_bound > 0.0,
        f"changed_days={len(values)};mean={mean:.8f};hac_one_sided_90pct_lcb={lower_bound:.8f}",
    )
