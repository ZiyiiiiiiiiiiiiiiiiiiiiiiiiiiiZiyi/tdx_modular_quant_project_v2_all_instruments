"""Verify covariance labels and conservative scenario fallback stay truthful."""
import pandas as pd

from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.runtime_maturity import covariance_runtime_state
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)


proposal = ActionProposal(
    proposal_id="d|B|entry",
    decision_id="d",
    symbol="B",
    action_type="new_entry",
    source_module="test",
    requested_lots=1,
    baseline_action="hold_cash",
    horizon_sessions=20,
    expected_net_profit_amount=100.0,
    robust_net_profit_amount=80.0,
    downside_cvar_amount=200.0,
    exact_cost_amount=10.0,
    funding_cash_amount=4_010.0,
    buy_cash_required_amount=4_010.0,
    market_notional_amount=4_000.0,
    exposure_delta=0.20,
)
authorization = ExposureAuthorization(
    decision_id="d",
    nav_amount=20_000.0,
    risk_exposure_ceiling=0.90,
    cash_buffer_amount=1_000.0,
    per_name_structural_cap=0.40,
    per_name_stress_budget_amount=3_000.0,
    portfolio_stress_budget_amount=8_000.0,
    new_entry_allowed=True,
    add_allowed=True,
    replacement_allowed=False,
    current_cash_amount=20_000.0,
    strategic_exposure_budget=0.90,
    signal_supported_exposure=0.20,
    integer_feasible_exposure=0.20,
    effective_deployment_target=0.20,
    fallback_risk_model="thesis_and_per_name_stress_caps",
)
incomplete = pd.DataFrame([[0.01]], index=["A"], columns=["A"])
fallback_plan = optimize_action_proposals(
    (proposal,),
    authorization=authorization,
    max_positions=7,
    covariance_matrix=incomplete,
)
assert fallback_plan.risk_model_used == "thesis_and_per_name_stress_caps"
assert fallback_plan.scenario_risk_penalty_amount > 0.0
assert fallback_plan.scenario_evidence_state == "conservative_prior_incremental_scenario"

complete = pd.DataFrame([[0.01]], index=["B"], columns=["B"])
complete.attrs["pair_coverage_ratio"] = 1.0
covariance_plan = optimize_action_proposals(
    (proposal,),
    authorization=authorization,
    max_positions=7,
    covariance_matrix=complete,
)
assert covariance_plan.risk_model_used == "covariance_with_correlated_tail_loss_proxy"
assert covariance_plan.scenario_risk_measure == "correlated_tail_loss_proxy"
assert covariance_plan.scenario_risk_penalty_amount > 0.0
assert covariance_runtime_state(day_index=19, covariance_matrix=complete) == "cold_start"
three_names = pd.DataFrame(
    [[0.01, 0.0, 0.0], [0.0, 0.02, 0.0], [0.0, 0.0, 0.03]],
    index=["A", "B", "C"],
    columns=["A", "B", "C"],
)
three_names.attrs["pair_coverage_ratio"] = 1.0
assert covariance_runtime_state(day_index=60, covariance_matrix=three_names) == "calibrated"
three_names.loc["A", "B"] = float("nan")
assert covariance_runtime_state(day_index=60, covariance_matrix=three_names) == "degraded"
print("[PASS] covariance requires maturity and 100% selected-symbol/pair coverage")
