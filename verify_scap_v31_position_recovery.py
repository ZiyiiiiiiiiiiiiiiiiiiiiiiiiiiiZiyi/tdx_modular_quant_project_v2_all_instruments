"""Focused contracts for SCAP-V3.1 position recovery remediation."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.candidate_funnel_audit import (
    reconcile_funnel_daily,
)
from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.runner import _holding_target_contract
from functions.decision_council.scap_v2_contracts import ExposureAuthorization
from functions.decision_council.scap_v31_authority import (
    attach_scap_v31_authority,
)
from functions.decision_council.small_capital_aggressive import (
    attach_scap_candidate_utility,
)


def _authorization(*, cash: float = 16_000.0) -> ExposureAuthorization:
    return ExposureAuthorization(
        decision_id="position_recovery_test",
        nav_amount=20_000.0,
        risk_exposure_ceiling=0.85,
        cash_buffer_amount=1_000.0,
        per_name_structural_cap=0.40,
        per_name_stress_budget_amount=3_200.0,
        portfolio_stress_budget_amount=8_000.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=False,
        current_cash_amount=cash,
        strategic_exposure_budget=0.85,
        signal_supported_exposure=0.20,
        integer_feasible_exposure=0.20,
    )


def verify_empty_plan_is_identity() -> None:
    plan = optimize_action_proposals(
        (),
        authorization=_authorization(),
        current_lots_by_symbol={"sz000001": 100},
        current_weights_by_symbol={"sz000001": 0.20},
        current_exposure=0.20,
        max_positions=5,
    )
    assert plan.target_lots_by_symbol == {"sz000001": 100}
    assert abs(plan.projected_cash - 16_000.0) < 1e-12
    assert abs(plan.projected_exposure - 0.20) < 1e-12
    assert abs(plan.constraint_slacks["exposure"] - 0.65) < 1e-12
    print("[PASS] empty ActionPlan preserves factual cash, lots and exposure")


def verify_zero_is_not_missing_holding_target() -> None:
    contract = _holding_target_contract(
        {
            "min_holdings": 0,
            "soft_target_positions": 4,
            "max_positions": 5,
        },
        actual_holding_count=1,
    )
    assert contract == {
        "minimum_required_holding_count": 0,
        "soft_target_holding_count": 4,
        "maximum_allowed_holding_count": 5,
        "soft_holding_shortfall_count": 3,
    }
    print("[PASS] Lean holding targets remain minimum 0, soft 4 and hard 5")


def verify_positive_pit_fallback_survives_utility_chain() -> None:
    candidates = pd.DataFrame(
        [
            {
                "symbol": "sz000001",
                "primary_score": 0.90,
                "entry_calibration_effective_sample_size_10d": 5,
                "entry_calibration_unique_session_count_10d": 5,
                "forecast_rank_ic_10d": -0.10,
                "forecast_calibration_slope_10d": -0.20,
                "forecast_drift_streak_10d": 9,
                "entry_calibration_state_10d": "drifted",
                "forecast_cluster_se_10d": 0.01,
                "comparable_expected_alpha": 0.08,
                "comparable_alpha_lcb": 0.06,
                "comparable_value_contract": "pit_factor_family_distribution",
                "comparable_value_horizon_days": 10,
                "mainline_v3_one_lot_cash_required": 1_000.0,
                "mainline_v3_minimum_buy_quantity": 100,
                "amount_ma20": 100_000_000.0,
                "volatility_20": 0.20,
                "ret_5": 0.02,
                "ret_20": 0.05,
            }
        ]
    )
    authorized = attach_scap_v31_authority(candidates, horizon_days=10)
    assert authorized.at[0, "scap_v31_authority_tier"] == "C"
    enriched = attach_scap_candidate_utility(
        authorized,
        alpha_score_column="primary_score",
        available_cash=20_000.0,
        nominal_nav=20_000.0,
        min_cash_buffer=1_000.0,
    )
    assert enriched.at[0, "scap_utility_calibration_state"] == (
        "pit_fallback_authorized"
    )
    assert float(enriched.at[0, "scap_candidate_utility"]) > 0.0
    print("[PASS] positive PIT fallback keeps C authority and positive CNY utility")


def verify_liveness_fields_survive_funnel_reconciliation() -> None:
    daily = reconcile_funnel_daily(
        pd.DataFrame(
            [
                {
                    "decision_id": "gov_20250102",
                    "date": "2025-01-02",
                    "scap_v31_positive_c_fallback_count": 3,
                    "scap_v31_all_d_streak": 0,
                    "scap_v31_normal_cash_zero_proposal_streak": 1,
                    "scap_v31_position_recovery_alert": "none",
                }
            ]
        ),
        ideal_plan=pd.DataFrame(),
        order_plan=pd.DataFrame(),
        execution_ledger=pd.DataFrame(),
    )
    assert int(daily.at[0, "scap_v31_positive_c_fallback_count"]) == 3
    assert int(daily.at[0, "scap_v31_normal_cash_zero_proposal_streak"]) == 1
    assert daily.at[0, "scap_v31_position_recovery_alert"] == "none"
    print("[PASS] liveness diagnostics survive saved funnel reconciliation")


def main() -> None:
    verify_empty_plan_is_identity()
    verify_zero_is_not_missing_holding_target()
    verify_positive_pit_fallback_survives_utility_chain()
    verify_liveness_fields_survive_funnel_reconciliation()
    print("SCAP-V3.1 position recovery verification passed.")


if __name__ == "__main__":
    main()
