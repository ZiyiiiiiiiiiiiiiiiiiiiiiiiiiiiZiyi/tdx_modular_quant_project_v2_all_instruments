"""Verify bounded optimizer search and idle-day proposal suppression."""
import time

from functions.decision_council.candidate_pool_contract import (
    select_feasible_candidate_pool,
)
from functions.decision_council.integer_action_optimizer import optimize_action_proposals
from functions.decision_council.scap_v2_contracts import ActionProposal, ExposureAuthorization


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def proposal(index):
    return ActionProposal(
        proposal_id=f"d|p{index}", decision_id="d", symbol=f"{index:06d}",
        action_type="new_entry", source_module="verify", requested_lots=1,
        baseline_action="hold_cash", horizon_sessions=10,
        expected_net_profit_amount=50.0 - index,
        robust_net_profit_amount=40.0 - index,
        downside_cvar_amount=5.0, exact_cost_amount=2.0,
        funding_cash_amount=402.0, buy_cash_required_amount=402.0,
        market_notional_amount=400.0, exposure_delta=0.02,
        decision_return_basis="lcb",
    )


def main():
    import pandas as pd
    pool_frame = pd.DataFrame(
        [
            {
                "symbol": "D",
                "scap_v31_decision_expected_return": 0.20,
                "scap_candidate_utility": 200.0,
                "scap_v31_authority_tier": "D",
                "scap_v31_max_lots": 0,
                "mainline_v3_minimum_buy_quantity": 100,
                "mainline_v3_one_lot_cash_required": 1_000.0,
            },
            {
                "symbol": "C",
                "scap_v31_decision_expected_return": 0.03,
                "scap_candidate_utility": 20.0,
                "scap_v31_authority_tier": "C",
                "scap_v31_max_lots": 1,
                "mainline_v3_minimum_buy_quantity": 100,
                "mainline_v3_one_lot_cash_required": 1_000.0,
                "primary_score": 0.5,
            },
        ]
    )
    for field in (
        "mainline_v3_market_permission_feasible",
        "mainline_v3_lot_feasible",
        "mainline_v3_structural_feasible",
        "mainline_v3_cash_feasible",
    ):
        pool_frame[field] = True
    selected, _, _ = select_feasible_candidate_pool(
        pool_frame,
        limit=1,
    )
    shortlist = frozenset(pool_frame.loc[selected, "symbol"].astype(str))
    check("non-authorized D tier cannot consume shortlist capacity", shortlist == frozenset({"C"}))

    authorization = ExposureAuthorization(
        decision_id="d", nav_amount=20_000.0, risk_exposure_ceiling=0.90,
        cash_buffer_amount=1_000.0, per_name_structural_cap=0.25,
        per_name_stress_budget_amount=1_000.0,
        portfolio_stress_budget_amount=5_000.0, new_entry_allowed=True,
        add_allowed=False, replacement_allowed=False,
        current_cash_amount=20_000.0, desired_exposure_target=0.75,
        effective_deployment_target=0.60,
    )
    started = time.perf_counter()
    plan = optimize_action_proposals(
        tuple(proposal(index) for index in range(20)),
        authorization=authorization, current_lots_by_symbol={},
        current_weights_by_symbol={}, current_exposure=0.0,
        max_positions=6,
    )
    elapsed = time.perf_counter() - started
    check("candidate universe is compressed to twelve", plan.constraint_slacks["solver_reduced_candidate_count"] == 12)
    check("position cap above five uses bounded search", plan.solver_status == "feasible_bounded_beam_search")
    check("bounded search respects position cap", plan.selected_position_count <= 6)
    check("bounded synthetic search completes promptly", elapsed < 5.0)
    check("rejected detail remains in proposal lineage", len(plan.rejected_proposals) >= 8)


if __name__ == "__main__":
    main()
