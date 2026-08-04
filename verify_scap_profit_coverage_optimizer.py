from __future__ import annotations

from functions.decision_council.integer_action_optimizer import (
    _portfolio_coverage_metrics,
    optimize_action_proposals,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)


def proposal(symbol: str, *, robust: float, p: float, win: float, loss: float) -> ActionProposal:
    notional = 3000.0
    return ActionProposal(
        proposal_id=f"d|{symbol}|entry",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="coverage_test",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=robust,
        robust_net_profit_amount=robust,
        downside_cvar_amount=300.0,
        exact_cost_amount=15.0,
        funding_cash_amount=3010.0,
        market_notional_amount=notional,
        exposure_delta=0.15,
        p_win_lower=p,
        avg_win_return=win,
        avg_loss_return=loss,
        expected_positive_pnl_amount=p * win * notional,
        expected_loss_pnl_amount=(1.0 - p) * loss * notional,
        lifecycle_cost_amount=15.0,
        coverage_evidence_authorized=True,
        economic_order_pass=True,
    )


def authorization() -> ExposureAuthorization:
    return ExposureAuthorization(
        decision_id="d",
        nav_amount=20_000.0,
        risk_exposure_ceiling=0.90,
        cash_buffer_amount=1_000.0,
        per_name_structural_cap=0.40,
        per_name_stress_budget_amount=4_000.0,
        portfolio_stress_budget_amount=8_000.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=False,
        current_cash_amount=20_000.0,
        strategic_exposure_budget=0.90,
        signal_supported_exposure=0.90,
        integer_feasible_exposure=0.90,
        desired_exposure_target=0.85,
        effective_deployment_target=0.85,
        per_name_soft_cap=0.25,
    )


def main() -> None:
    strong_a = proposal("a", robust=100.0, p=0.65, win=0.10, loss=0.03)
    strong_b = proposal("b", robust=95.0, p=0.65, win=0.10, loss=0.03)
    weak = proposal("weak", robust=8.0, p=0.35, win=0.03, loss=0.10)
    strong_metrics = _portfolio_coverage_metrics(
        (strong_a, strong_b),
        covariance_matrix=None,
        correlation_floor=0.35,
        minimum_evidence_names=1,
    )
    weak_metrics = _portfolio_coverage_metrics(
        (strong_a, strong_b, weak),
        covariance_matrix=None,
        correlation_floor=0.35,
        minimum_evidence_names=1,
    )
    assert strong_metrics["profit_coverage_ratio"] > weak_metrics["profit_coverage_ratio"]
    assert strong_metrics["profit_coverage_probability_lower"] > weak_metrics[
        "profit_coverage_probability_lower"
    ]

    plan = optimize_action_proposals(
        (strong_a, strong_b, weak),
        authorization=authorization(),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
        minimum_profit_coverage_ratio=1.25,
        minimum_profit_coverage_probability=0.55,
        minimum_coverage_evidence_names=1,
    )
    assert strong_a.proposal_id in plan.selected_proposal_ids
    assert strong_b.proposal_id in plan.selected_proposal_ids
    assert weak.proposal_id not in plan.selected_proposal_ids
    assert plan.coverage_state == "pit_calibrated_cantelli_lower_bound"
    assert plan.selected_position_count == 2
    assert plan.profit_coverage_ratio > 1.25
    assert plan.constraint_slacks["profit_coverage_ratio"] == plan.profit_coverage_ratio
    assert plan.minimum_selected_marginal_utility_amount > 0.0
    assert plan.maximum_rejected_marginal_utility_amount <= 0.0

    unavailable = optimize_action_proposals(
        (ActionProposal(**{**strong_a.as_dict(), "proposal_id": "d|cold|entry", "symbol": "cold", "coverage_evidence_authorized": False}),),
        authorization=authorization(),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
    )
    assert unavailable.coverage_state == "insufficient_pit_coverage_evidence"
    assert unavailable.coverage_penalty_amount == 0.0

    # Coverage may authorize the seventh/ceiling name, but unavailable or weak
    # evidence must leave the result at the six-name product target.
    ceiling_candidates = tuple(
        ActionProposal(
            **{
                **proposal(
                    f"ceiling_{index}",
                    robust=100.0 - index,
                    p=0.65,
                    win=0.10,
                    loss=0.03,
                ).as_dict(),
                "funding_cash_amount": 2_500.0,
                "buy_cash_required_amount": 2_500.0,
                "market_notional_amount": 2_490.0,
                "exposure_delta": 0.12,
            }
        )
        for index in range(7)
    )
    ceiling_plan = optimize_action_proposals(
        ceiling_candidates,
        authorization=authorization(),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=7,
        target_positions=6,
        coverage_mode="authorized_ceiling_only",
        minimum_coverage_evidence_names=6,
        minimum_profit_coverage_ratio=1.25,
        minimum_profit_coverage_probability=0.55,
    )
    assert ceiling_plan.planned_holding_count == 7
    cold_candidates = tuple(
        ActionProposal(
            **{
                **item.as_dict(),
                "proposal_id": item.proposal_id.replace("ceiling", "cold"),
                "symbol": item.symbol.replace("ceiling", "cold"),
                "coverage_evidence_authorized": False,
            }
        )
        for item in ceiling_candidates
    )
    cold_plan = optimize_action_proposals(
        cold_candidates,
        authorization=authorization(),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=7,
        target_positions=6,
        coverage_mode="authorized_ceiling_only",
        minimum_coverage_evidence_names=6,
    )
    assert cold_plan.planned_holding_count <= 6
    print("[PASS] PIT profit coverage, dependence inflation and marginal K objective")


if __name__ == "__main__":
    main()
