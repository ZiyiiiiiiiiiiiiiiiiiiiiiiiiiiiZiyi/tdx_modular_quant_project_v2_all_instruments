"""Optimizer properties for conditional holding/exposure floors."""
from __future__ import annotations

from functions.decision_council.integer_action_optimizer import optimize_action_proposals
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)


def proposal(symbol: str, robust: float, *, exposure: float = 0.15) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"d|{symbol}|buy",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="fixture",
        requested_lots=1,
        baseline_action="hold",
        horizon_sessions=10,
        expected_net_profit_amount=robust,
        robust_net_profit_amount=robust,
        downside_cvar_amount=1.0,
        exact_cost_amount=1.0,
        funding_cash_amount=2_000.0,
        buy_cash_required_amount=2_000.0,
        market_notional_amount=2_000.0,
        exposure_delta=exposure,
    )


authorization = ExposureAuthorization(
    decision_id="d",
    nav_amount=20_000.0,
    risk_exposure_ceiling=0.90,
    cash_buffer_amount=1_000.0,
    per_name_structural_cap=0.40,
    per_name_stress_budget_amount=2_000.0,
    portfolio_stress_budget_amount=10_000.0,
    new_entry_allowed=True,
    add_allowed=True,
    replacement_allowed=False,
    current_cash_amount=20_000.0,
    strategic_exposure_budget=0.75,
    signal_supported_exposure=0.75,
    integer_feasible_exposure=0.75,
    desired_exposure_target=0.75,
    effective_deployment_target=0.75,
)

positive = tuple(proposal(f"S{index}", robust=10.0 + index) for index in range(4))
plan = optimize_action_proposals(
    positive,
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=5,
    minimum_positions=3,
    minimum_exposure=0.45,
    target_positions=4,
    target_exposure=0.60,
    wealth_materiality_epsilon_amount=1.0,
)
assert plan.planned_holding_count >= 3
assert plan.projected_exposure >= 0.45 - 1e-12
assert plan.holding_floor_violation_count == 0
assert plan.exposure_floor_violation <= 1e-12
print("[PASS] feasible conditional holding and exposure floors dominate no-trade")

negative = tuple(proposal(f"N{index}", robust=-1.0) for index in range(3))
empty = optimize_action_proposals(
    negative,
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=5,
    minimum_positions=0,
    minimum_exposure=0.0,
    target_positions=3,
    target_exposure=0.45,
    wealth_materiality_epsilon_amount=1.0,
)
assert not empty.selected_proposal_ids
assert empty.planned_holding_count == 0
print("[PASS] soft target cannot resurrect negative-value proposals")

tiny = (
    proposal("A", robust=10.10),
    proposal("B", robust=10.20),
    proposal("C", robust=10.30),
)
near = optimize_action_proposals(
    tiny,
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=5,
    minimum_positions=2,
    minimum_exposure=0.30,
    target_positions=3,
    target_exposure=0.45,
    wealth_materiality_epsilon_amount=1.0,
)
assert near.planned_holding_count == 3
print("[PASS] yuan materiality admits target breadth within the wealth-near-optimal set")

print("[PASS] SCAP optimizer floor contract verification completed")
