"""Eight-day full-runner smoke for the monthly-LightGBM v3 path."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from functions.decision_council.factor_source import FACTOR_SOURCE_SELECTED_CABINET, resolve_factor_source
from functions.decision_council.monthly_lgbm_hybrid import FusionCalibration, fit_monthly_lgbm_ranker
from functions.decision_council.runner import GovernanceBacktestRunner
from verify_governance_mainline_v3_runner_smoke import RUN_ID, _check, _features


ROLE_FEATURES = (
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_risk_safety_score",
    "cabinet_liquidity_health_score",
    "cabinet_hold_support_score",
)


def _artifact():
    rng = np.random.default_rng(20260717)
    dates = pd.bdate_range("2023-01-02", periods=90)
    rows = []
    for date_index, date in enumerate(dates):
        for symbol_index in range(24):
            values = rng.uniform(0.0, 1.0, len(ROLE_FEATURES))
            rows.append(
                {
                    "date": date,
                    "symbol": f"T{symbol_index:03d}",
                    "label_maturity_date": dates[min(date_index + 5, len(dates) - 1)],
                    "future_excess_log_return_net": 0.02 * values[0] + 0.01 * values[2] + rng.normal(0, 0.006),
                    **dict(zip(ROLE_FEATURES, values)),
                }
            )
    return fit_monthly_lgbm_ranker(
        pd.DataFrame(rows),
        feature_columns=ROLE_FEATURES,
        as_of_date=dates[-6],
        horizon_days=5,
        validation_date_count=15,
        model_params={"n_estimators": 50},
    )


def main() -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=RUN_ID,
    )
    output = Path("reports") / f"codex_smoke_mainline_v3_monthly_lgbm_{datetime.now():%Y%m%d_%H%M%S}"
    full_features = _features(spec, periods=30)
    decision_features = full_features[full_features["date"].isin(sorted(full_features["date"].unique())[:8])].copy()
    artifact = _artifact()
    calibration = FusionCalibration(
        ml_weight=0.35,
        unconstrained_weight=0.42,
        reliability=0.84,
        maximum_ml_weight=0.40,
        validation_rank_ic_mean=artifact.validation_rank_ic_mean,
        validation_rank_ic_standard_error=0.02,
        status="active",
    )
    runner = GovernanceBacktestRunner(
        decision_features,
        audit_price_df=full_features[["date", "symbol", "close"]],
        initial_cash=20_000.0,
        safety_proxy_mode="strict",
        output_dir=output,
        alpha_models=spec.alpha_models,
        enable_shadow_portfolios=False,
        enable_reputation=False,
        governance_variant="governance_layer_validation",
        entry_confirmation_mode="factor_only",
        selection_weight_mode="factor_judged",
        universe_name="synthetic_v3_ml_smoke",
        universe_mode="quality_fallback",
        require_constituents=False,
        allow_fallback=True,
        max_positions=3,
        factor_source_spec=spec,
        strategy_logic_version="mainline_v3_monthly_lgbm_hybrid",
        pit_runtime_state="degraded",
        monthly_lgbm_artifact=artifact,
        monthly_lgbm_fusion_calibration=calibration,
        capital_profile={
            "name": "smoke_20k", "retail_lot_adapter": False, "max_positions": 3,
            "min_cash_buffer": 1000.0, "retail_single_position_cap": 0.40,
            "capital_usage_mode": "allow_cash",
        },
    )
    saved = runner.run(max_days=8, show_progress=False, show_live_monitor=False)
    gates = pd.read_csv(saved["governance_candidate_gate_audit"])
    required = {
        "monthly_lgbm_raw_score", "monthly_lgbm_rank_percentile", "hybrid_final_score",
        "hybrid_ml_weight", "hybrid_fusion_status", "strategy_logic_version",
    }
    _check(required.issubset(gates.columns), "candidate audit preserves monthly ML and fusion evidence")
    _check(gates["strategy_logic_version"].eq("mainline_v3_monthly_lgbm_hybrid").all(), "candidate audit is hybrid-v3 version isolated")
    _check(pd.to_numeric(gates["hybrid_ml_weight"], errors="coerce").eq(0.35).all(), "runner applies the supplied validated ML weight continuously")
    orders = pd.read_csv(saved["executable_order_plan"])
    executions = pd.read_csv(saved["governance_execution_ledger"])
    _check(required.issubset(orders.columns), "order plan preserves hybrid decision evidence")
    _check(required.issubset(executions.columns), "execution ledger preserves hybrid decision evidence")
    buys = executions[
        executions["side"].astype(str).str.lower().eq("buy")
        & executions["execution_status"].astype(str).str.lower().eq("filled")
    ]
    _check(not buys.empty, "hybrid candidate reaches a filled buy")
    _check(pd.to_numeric(buys["executed_shares"], errors="coerce").eq(100.0).all(), "hybrid filled buys remain exactly one lot")
    _check(buys["strategy_logic_version"].eq("mainline_v3_monthly_lgbm_hybrid").all(), "filled buys retain hybrid logic version")
    fusion = pd.read_csv(saved["governance_monthly_lgbm_fusion_audit"])
    _check(len(fusion) == 8 and fusion["status"].eq("active").all(), "daily fusion audit records model health and authority")
    account = pd.read_csv(saved["governance_account_audit_ledger"])
    _check(account["reconciliation_passed"].fillna(False).astype(bool).all(), "cash and holdings reconcile after hybrid fills")
    integrity = pd.read_csv(saved["governance_runtime_integrity_audit"])
    _check(integrity["passed"].fillna(False).astype(bool).all(), "full runner integrity audit passes")
    failure_outputs = {
        "governance_failure_lab_layer_increment",
        "governance_failure_lab_role_marginal_summary",
        "governance_failure_lab_permutation_report",
        "governance_failure_lab_negative_control_audit",
        "governance_failure_lab_overview",
    }
    _check(failure_outputs.issubset(saved), "runner publishes every failure-lab product artifact")
    overview = pd.read_csv(saved["governance_failure_lab_overview"])
    _check(overview["changes_trading"].eq(False).all(), "failure lab remains diagnostics-only")
    controls = pd.read_csv(saved["governance_failure_lab_negative_control_audit"])
    _check("negative_control_gate_pass" in controls, "runner publishes the leakage-control gate")
    new_failure_outputs = {
        "governance_failure_lab_competing_risk_summary",
        "governance_failure_lab_adversarial_drift_summary",
        "governance_failure_lab_ml_stability_summary",
        "governance_failure_lab_cost_capacity_summary",
        "governance_overfit_overview",
        "governance_unified_research_gate_summary",
    }
    _check(new_failure_outputs.issubset(saved), "runner publishes all extended failure-lab gates")
    stability = pd.read_csv(saved["governance_failure_lab_ml_stability_summary"])
    _check(stability.iloc[0]["evidence_status"] == "insufficient_model_months", "single supplied model cannot masquerade as cross-month stability")
    unified = pd.read_csv(saved["governance_unified_research_gate_summary"])
    _check(not bool(unified.iloc[0]["research_acceptance_pass"]), "short smoke fails research acceptance closed")
    _check(not bool(unified.iloc[0]["formal_production_acceptance_pass"]), "degraded PIT blocks formal production acceptance")
    print(f"Smoke output: {output.resolve()}")


if __name__ == "__main__":
    main()
