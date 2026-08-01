"""Scalable solver and normalized breadth properties."""
from functions.decision_council.integer_action_optimizer import (
    _normalized_breadth_score,
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)


def proposal(index: int, *, nav: float) -> ActionProposal:
    funding = 5_000.0
    robust = 100.0 - index
    return ActionProposal(
        proposal_id=f"d|s{index:02d}|entry",
        decision_id="d",
        symbol=f"s{index:02d}",
        action_type="new_entry",
        source_module="scalable_test",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=robust,
        robust_net_profit_amount=robust,
        downside_cvar_amount=250.0,
        exact_cost_amount=8.0,
        funding_cash_amount=funding,
        exposure_delta=funding / nav,
        authority_tier="A",
        thesis=f"pool{index % 6}",
        pool_id=f"pool{index % 6}",
        primary_score=1.0 - index / 100.0,
        primary_rank=float(index + 1),
        unit_capital_robust_return=robust / funding,
    )


def authorization(nav: float) -> ExposureAuthorization:
    return ExposureAuthorization(
        decision_id="d",
        nav_amount=nav,
        risk_exposure_ceiling=0.90,
        cash_buffer_amount=5_000.0,
        per_name_structural_cap=0.12,
        per_name_stress_budget_amount=5_000.0,
        portfolio_stress_budget_amount=50_000.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=False,
        current_cash_amount=nav,
        strategic_exposure_budget=0.90,
        signal_supported_exposure=0.90,
        integer_feasible_exposure=0.90,
        desired_exposure_target=0.85,
        effective_deployment_target=0.85,
        per_name_soft_cap=0.08,
    )


nav = 100_000.0
items = tuple(proposal(index, nav=nav) for index in range(20))
plan = optimize_action_proposals(
    items,
    authorization=authorization(nav),
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=12,
    max_names_per_thesis=4,
    candidate_limit=40,
    beam_width=128,
)
assert plan.solver_status == "feasible_bounded_beam_search"
assert 1 <= len(plan.selected_proposal_ids) <= 12
assert int(plan.constraint_slacks["solver_optimality_proven"]) == 0
assert int(plan.constraint_slacks["solver_beam_width"]) == 128

small_plan = optimize_action_proposals(
    items[:5],
    authorization=authorization(nav),
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=5,
    max_names_per_thesis=3,
    candidate_limit=24,
)
assert small_plan.solver_status == "optimal_full_universe_exhaustive"
assert int(small_plan.constraint_slacks["solver_optimality_proven"]) == 1
recomputed_objective = (
    small_plan.proposal_robust_profit_amount
    - small_plan.authority_penalty_amount
    - small_plan.thesis_penalty_amount
    - small_plan.concentration_penalty_amount
    - small_plan.marginal_risk_penalty_amount
    - small_plan.deployment_penalty_amount
)
assert abs(recomputed_objective - small_plan.robust_net_profit_amount) < 1e-10

reduced_plan = optimize_action_proposals(
    items[:10],
    authorization=authorization(nav),
    current_lots_by_symbol={},
    current_weights_by_symbol={},
    current_exposure=0.0,
    max_positions=5,
    max_names_per_thesis=3,
    candidate_limit=5,
)
assert reduced_plan.solver_status == "optimal_reduced_universe_exhaustive"
assert int(reduced_plan.constraint_slacks["solver_optimality_proven"]) == 0
assert int(reduced_plan.constraint_slacks["solver_reduced_universe_optimality_proven"]) == 1

balanced = _normalized_breadth_score(
    {f"s{i}": 0.10 for i in range(8)},
    {f"p{i}" for i in range(4)},
    max_positions=10,
)
concentrated = _normalized_breadth_score(
    {"s0": 0.65, "s1": 0.15},
    {"p0"},
    max_positions=10,
)
assert balanced > concentrated

print("[PASS] exact-small / bounded-large solver and normalized breadth contract")
