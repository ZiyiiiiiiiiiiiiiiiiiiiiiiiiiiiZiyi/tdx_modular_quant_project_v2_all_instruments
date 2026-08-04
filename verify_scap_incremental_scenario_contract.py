"""Regression checks for the incremental no-trade baseline objective."""
from __future__ import annotations

from dataclasses import replace
import pandas as pd

from functions.decision_council.integer_action_optimizer import optimize_action_proposals
from functions.decision_council.scap_v2_contracts import ActionProposal, ExposureAuthorization


def proposal(
    symbol: str,
    *,
    nav: float,
    robust: float = 60.0,
    downside: float = 120.0,
    evidence: bool = True,
    effective_samples: float = 120.0,
) -> ActionProposal:
    funding = 3_000.0
    return ActionProposal(
        proposal_id=f"d|{symbol}|entry",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="incremental_scenario_test",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=robust + 10.0,
        robust_net_profit_amount=robust,
        downside_cvar_amount=downside,
        exact_cost_amount=15.0,
        funding_cash_amount=funding,
        market_notional_amount=funding - 10.0,
        exposure_delta=funding / nav,
        authority_tier="A",
        p_win_lower=0.40,
        avg_win_return=0.04,
        avg_loss_return=0.08,
        expected_positive_pnl_amount=48.0,
        expected_loss_pnl_amount=144.0,
        lifecycle_cost_amount=15.0,
        coverage_evidence_authorized=evidence,
        calibration_effective_sample_size=effective_samples if evidence else 0.0,
        calibration_evidence_state="mature" if evidence else "cold_start",
        scenario_contract_id="scap_incremental_scenario_cvar_v1",
        economic_order_pass=True,
    )


def authorization(nav: float) -> ExposureAuthorization:
    return ExposureAuthorization(
        decision_id="d",
        nav_amount=nav,
        risk_exposure_ceiling=0.90,
        cash_buffer_amount=1_000.0,
        per_name_structural_cap=0.40,
        per_name_stress_budget_amount=5_000.0,
        portfolio_stress_budget_amount=10_000.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=False,
        current_cash_amount=nav,
        strategic_exposure_budget=0.90,
        signal_supported_exposure=0.90,
        integer_feasible_exposure=0.90,
        desired_exposure_target=0.85,
        effective_deployment_target=0.85,
        per_name_soft_cap=0.25,
    )


def optimize(item: ActionProposal, nav: float, *, scenarios=None):
    return optimize_action_proposals(
        (item,),
        authorization=authorization(nav),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
        coverage_mode="diagnostic_shadow",
        scenario_return_matrix=scenarios,
    )


def main() -> None:
    small = optimize(proposal("same", nav=20_000.0), 20_000.0)
    large = optimize(proposal("same", nav=200_000.0), 200_000.0)
    assert small.selected_proposal_ids == large.selected_proposal_ids == (
        "d|same|entry",
    )
    assert abs(small.robust_net_profit_amount - large.robust_net_profit_amount) < 1e-12
    assert small.hold_baseline_objective_amount == 0.0
    assert small.coverage_mode == "diagnostic_shadow"
    assert small.coverage_penalty_amount == 0.0
    assert small.scenario_risk_penalty_amount > 0.0
    assert small.incremental_cvar_amount > 0.0
    assert small.scenario_evidence_state == "mature_pit_incremental_scenario"
    recomputed = (
        small.proposal_robust_profit_amount
        - small.authority_penalty_amount
        - small.thesis_penalty_amount
        - small.concentration_penalty_amount
        - small.scenario_risk_penalty_amount
        - small.deployment_penalty_amount
    )
    assert abs(recomputed - small.robust_net_profit_amount) < 1e-12

    warming = optimize(
        proposal("warming", nav=20_000.0, effective_samples=30.0),
        20_000.0,
    )
    cold = optimize(proposal("cold", nav=20_000.0, evidence=False), 20_000.0)
    assert warming.scenario_evidence_state == "warming_pit_incremental_scenario"
    assert cold.scenario_evidence_state == "conservative_prior_incremental_scenario"
    assert cold.model_uncertainty_amount > warming.model_uncertainty_amount
    assert warming.model_uncertainty_amount > small.model_uncertainty_amount

    scenarios = pd.DataFrame(
        {"same": [-0.05] * 4 + [0.01] * 36},
        index=pd.date_range("2025-01-01", periods=40, freq="D"),
    )
    formal = optimize(proposal("same", nav=20_000.0), 20_000.0, scenarios=scenarios)
    assert formal.scenario_risk_measure == "joint_historical_scenario_cvar"
    assert formal.risk_model_used == "joint_historical_scenario_cvar"
    assert formal.joint_scenario_count == 40
    assert formal.scenario_evidence_state == "mature_pit_joint_historical_scenario"
    # Lifecycle cost is already deducted by candidate net value; CVaR contains
    # market tail loss only under the v2 single-risk-charge contract.
    expected_tail_loss = 0.05 * 2_990.0
    assert abs(formal.incremental_cvar_amount - expected_tail_loss) < 1e-9
    es_blocked = optimize_action_proposals(
        (proposal("same", nav=20_000.0, downside=50.0),),
        authorization=replace(
            authorization(20_000.0), portfolio_stress_budget_amount=100.0
        ),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
        scenario_return_matrix=scenarios,
    )
    assert es_blocked.selected_proposal_ids == ()

    rejected = optimize(
        proposal(
            "risk_dominated",
            nav=20_000.0,
            robust=5.0,
            downside=300.0,
            evidence=False,
        ),
        20_000.0,
    )
    assert rejected.selected_proposal_ids == ()
    assert rejected.best_rejected_proposal_ids == ("d|risk_dominated|entry",)
    assert rejected.best_rejected_objective_amount < 0.0
    assert rejected.best_rejected_cvar_amount > 0.0
    assert rejected.best_rejected_model_uncertainty_amount > 0.0
    print("[PASS] incremental hold baseline, formal joint CVaR, proxy fallback and rejected counterfactual")


if __name__ == "__main__":
    main()
