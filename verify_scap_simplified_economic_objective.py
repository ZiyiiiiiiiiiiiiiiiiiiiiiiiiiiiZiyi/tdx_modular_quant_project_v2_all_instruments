"""Verify the single conservative-net-value and portfolio-risk objective."""
from functions.decision_council.action_utility import (
    LifecycleCostEstimate,
    assess_economic_order,
)
from functions.decision_council.portfolio_scenario_model import (
    evaluate_incremental_scenario_risk,
)
from functions.decision_council.scap_v2_contracts import ActionProposal


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def proposal(*, robust=10.0, expected=20.0, downside=20.0, basis="lcb"):
    return ActionProposal(
        proposal_id="p1",
        decision_id="d1",
        symbol="000001",
        action_type="new_entry",
        source_module="verify",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=expected,
        robust_net_profit_amount=robust,
        downside_cvar_amount=downside,
        exact_cost_amount=5.0,
        funding_cash_amount=1005.0,
        buy_cash_required_amount=1005.0,
        market_notional_amount=1000.0,
        exposure_delta=0.10,
        decision_return_basis=basis,
    )


def main():
    lifecycle = LifecycleCostEstimate(5.0, 5.0, 0.0, 0.0, 10.0, 0.01)
    small_positive = assess_economic_order(
        market_notional_amount=1000.0,
        lifecycle_cost=lifecycle,
        conservative_gross_profit_amount=20.0,
        robust_net_profit_amount=5.0,
        cost_profile={
            "scap_max_lifecycle_cost_to_gross_profit_ratio": 0.30,
            "scap_hard_max_lifecycle_cost_to_gross_profit_ratio": 0.60,
            "scap_minimum_robust_profit_hurdle_amount": 15.0,
        },
    )
    check("positive net value below 15 CNY is not vetoed", small_positive.passed)
    check("30 percent band is diagnostic", "lifecycle_cost_share_quality_band" in small_positive.warnings)
    check("15 CNY band is diagnostic", "robust_profit_below_quality_hurdle" in small_positive.warnings)

    negative = assess_economic_order(
        market_notional_amount=1000.0,
        lifecycle_cost=lifecycle,
        conservative_gross_profit_amount=20.0,
        robust_net_profit_amount=0.0,
        cost_profile={"scap_hard_max_lifecycle_cost_to_gross_profit_ratio": 0.60},
    )
    check("non-positive conservative net value remains a hard veto", not negative.passed)

    lcb_risk = evaluate_incremental_scenario_risk(
        [proposal(basis="lcb")],
        cvar_risk_aversion=0.05,
        model_uncertainty_risk_aversion=0.10,
    )
    check("LCB and model uncertainty are not charged together", lcb_risk.model_uncertainty_amount == 0.0)
    check("tail risk is charged once at portfolio level", abs(lcb_risk.scenario_risk_penalty_amount - 1.0) < 1e-12)

    point_risk = evaluate_incremental_scenario_risk(
        [proposal(basis="point")],
        cvar_risk_aversion=0.0,
        model_uncertainty_risk_aversion=0.10,
    )
    check("non-LCB return retains explicit uncertainty", point_risk.model_uncertainty_amount > 0.0)

    audited_recovery = evaluate_incremental_scenario_risk(
        [proposal(robust=12.23063012302482, expected=17.63697028409922, downside=287.3847429350658, basis="lcb")],
        cvar_risk_aversion=0.01,
        model_uncertainty_risk_aversion=0.10,
    )
    objective = (
        audited_recovery.incremental_robust_wealth_amount
        - 3.359
        - audited_recovery.scenario_risk_penalty_amount
    )
    check("audited positive-net recovery survives bounded soft CVaR", objective > 0.0)


if __name__ == "__main__":
    main()
