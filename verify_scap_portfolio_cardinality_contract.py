"""Boundary tests for SCAP holding count, effective-N and pool diversity."""
from __future__ import annotations

from functions.decision_council.integer_action_optimizer import (
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)


def candidate(symbol: str, pool: str, robust: float, exposure: float) -> ActionProposal:
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
        funding_cash_amount=exposure * 100_000.0,
        market_notional_amount=exposure * 100_000.0,
        exposure_delta=exposure,
        thesis=pool,
        pool_id=pool,
    )


authorization = ExposureAuthorization(
    decision_id="d",
    nav_amount=100_000.0,
    risk_exposure_ceiling=0.90,
    cash_buffer_amount=10_000.0,
    per_name_structural_cap=0.20,
    per_name_stress_budget_amount=10_000.0,
    portfolio_stress_budget_amount=50_000.0,
    new_entry_allowed=True,
    add_allowed=True,
    replacement_allowed=False,
    current_cash_amount=100_000.0,
    strategic_exposure_budget=0.75,
    signal_supported_exposure=0.75,
    integer_feasible_exposure=0.75,
)

proposals = (
    candidate("A", "p1", 30.0, 0.15),
    candidate("B", "p1", 29.0, 0.15),
    candidate("C", "p2", 28.0, 0.15),
    candidate("D", "p2", 27.0, 0.15),
    candidate("E", "p3", 26.0, 0.15),
    candidate("F", "p4", 25.0, 0.15),
)
theses = {item.symbol: item.pool_id for item in proposals}
plan = optimize_action_proposals(
    proposals,
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=7,
    thesis_by_symbol=theses,
    max_names_per_thesis=4,
    minimum_positions=5,
    target_positions=6,
    minimum_exposure=0.60,
    target_exposure=0.75,
    minimum_active_pool_size=5,
    minimum_effective_n_ratio=0.75,
    minimum_pool_count=3,
    wealth_materiality_epsilon_amount=1.0,
)
assert plan.planned_holding_count >= 5
assert plan.constraint_slacks["atomic_pool_violation_count"] == 0
assert plan.constraint_slacks["effective_n_violation"] <= 1e-12
assert plan.constraint_slacks["pool_count_violation"] == 0
print("[PASS] a cash portfolio is built as a diversified pool, not one orphan name")

capacity_shortfall = optimize_action_proposals(
    proposals[:4],
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=4,
    thesis_by_symbol=theses,
    max_names_per_thesis=4,
    minimum_positions=4,
    target_positions=4,
    minimum_active_pool_size=5,
    minimum_effective_n_ratio=0.75,
    minimum_pool_count=3,
)
assert capacity_shortfall.planned_holding_count == 0
assert not capacity_shortfall.selected_proposal_ids
print("[PASS] dynamic capacity cannot rewrite a five-name product minimum to four")

concentrated = (
    candidate("X", "one_pool", 40.0, 0.60),
    candidate("Y", "two_pool", 10.0, 0.05),
    candidate("Z", "three_pool", 9.0, 0.05),
)
concentrated_plan = optimize_action_proposals(
    concentrated,
    authorization=authorization,
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=3,
    thesis_by_symbol={item.symbol: item.pool_id for item in concentrated},
    max_names_per_thesis=2,
    minimum_positions=3,
    target_positions=3,
    minimum_active_pool_size=3,
    minimum_effective_n_ratio=0.75,
    minimum_pool_count=3,
)
assert concentrated_plan.constraint_slacks["effective_n_violation"] > 0.0
assert concentrated_plan.constraint_slacks["pool_count_violation"] == 0
print("[PASS] special-value concentration is surfaced as an explicit effective-N breach")

print("[PASS] SCAP portfolio cardinality contract verification completed")
