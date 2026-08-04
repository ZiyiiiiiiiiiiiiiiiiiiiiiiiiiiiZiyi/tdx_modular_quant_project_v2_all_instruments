from __future__ import annotations

import pandas as pd

from functions.decision_council.action_utility import (
    assess_economic_order,
    estimate_lifecycle_cost,
    minimum_economic_order_amount,
)
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.scap_v3_lean import build_lean_decision


PROFILE = {
    "commission_rate": 0.0003,
    "minimum_commission": 5.0,
    "scap_candidate_minimum_commission": 5.0,
    "stamp_duty_rate": 0.0005,
    "slippage_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
    "scap_max_round_trip_fixed_cost_ratio": 0.005,
    "scap_max_lifecycle_cost_to_gross_profit_ratio": 0.30,
    "scap_hard_max_lifecycle_cost_to_gross_profit_ratio": 0.60,
    "scap_minimum_robust_profit_hurdle_amount": 15.0,
    "scap_high_confidence_small_order_exception_enabled": False,
}


def main() -> None:
    minimum = minimum_economic_order_amount(cost_profile=PROFILE)
    assert abs(minimum - 2873.563218390805) < 1e-6, minimum

    small = estimate_lifecycle_cost(
        symbol="sz000001", price=15.0, shares=100, cost_profile=PROFILE
    )
    assert small.buy_cost_amount > 5.0
    assert small.sell_cost_amount > small.buy_cost_amount
    small_gate = assess_economic_order(
        market_notional_amount=1500.0,
        lifecycle_cost=small,
        conservative_gross_profit_amount=120.0,
        robust_net_profit_amount=60.0,
        cost_profile=PROFILE,
    )
    assert small_gate.passed
    assert "minimum_economic_notional" in small_gate.warnings
    assert "round_trip_cost_ratio" in small_gate.warnings

    economic = estimate_lifecycle_cost(
        symbol="sz000001", price=30.0, shares=100, cost_profile=PROFILE
    )
    passed = assess_economic_order(
        market_notional_amount=3000.0,
        lifecycle_cost=economic,
        conservative_gross_profit_amount=150.0,
        robust_net_profit_amount=80.0,
        cost_profile=PROFILE,
    )
    assert passed.passed, passed

    fee_drained = assess_economic_order(
        market_notional_amount=3000.0,
        lifecycle_cost=economic,
        conservative_gross_profit_amount=30.0,
        robust_net_profit_amount=10.0,
        cost_profile=PROFILE,
    )
    assert fee_drained.passed
    assert "lifecycle_cost_share_quality_band" in fee_drained.warnings
    assert "robust_profit_below_quality_hurdle" in fee_drained.warnings

    explicit = dict(PROFILE)
    explicit["scap_expected_add_probability"] = 0.25
    explicit["scap_expected_replacement_probability"] = 0.10
    lifecycle = estimate_lifecycle_cost(
        symbol="sh600000", price=30.0, shares=100, cost_profile=explicit
    )
    assert lifecycle.total_lifecycle_cost_amount > (
        lifecycle.buy_cost_amount + lifecycle.sell_cost_amount
    )

    candidate = pd.DataFrame(
        [
            {
                "symbol": "sz000001",
                "close_nominal": 15.0,
                "mainline_v3_minimum_buy_quantity": 100,
                "mainline_v3_one_lot_market_notional": 1500.0,
                "mainline_v3_one_lot_cash_required": 1506.0,
                "mainline_v3_one_lot_weight": 0.075,
                "mainline_v3_lot_feasible": True,
                "scap_action_candidate": True,
                "scap_v31_authority_tier": "A",
                "scap_v31_decision_expected_return": 0.06,
                "scap_v31_max_lots": 2,
                "scap_expected_return_point": 0.07,
                "scap_candidate_utility": 100.0,
                "primary_score": 0.90,
                "cabinet_entry_thesis": "quality",
                "entry_calibration_state_10d": "calibrated",
                "p_win_10d_wilson_lower": 0.60,
                "avg_win_10d_by_bucket": 0.08,
                "avg_loss_10d_by_bucket": 0.04,
                "downside_cvar_10d_by_bucket": 0.08,
            }
        ]
    )
    profile = dict(PROFILE)
    profile["scap_economic_order_contract_enabled"] = True
    profile["scap_round_trip_cost_ratio_hard_gate_enabled"] = True
    profile["scap_minimum_economic_notional_hard_gate_enabled"] = True
    decision = build_lean_decision(
        DecisionContext(
            decision_id="economic_gate",
            decision_date=pd.Timestamp("2025-01-10"),
            candidates=candidate,
            current_weights={},
            holding_days={},
            pending_locked_symbols=frozenset(),
            safety=SafetyDecision(
                decision_date=pd.Timestamp("2025-01-10"),
                risk_level="normal",
                exposure_cap=0.90,
                benchmark_drawdown_5d=0.0,
                market_liquidity_stress_ratio=0.0,
                proxy_symbol="sh510300",
                proxy_mode="strict",
            ),
            top_n=5,
            entry_rank_limit=20,
            nav_amount=20_000.0,
            cash_amount=20_000.0,
            cash_buffer_amount=1_000.0,
            per_name_structural_cap=0.40,
            portfolio_stress_budget_amount=8_000.0,
            control_mode="aggressive_lean",
            forecast_horizon_sessions=10,
            execution_cost_profile=profile,
            desired_exposure_target=0.90,
        ),
        candidate,
    )
    one_lot = next(p for p in decision.proposals if p.requested_lots == 1)
    two_lot = next(p for p in decision.proposals if p.requested_lots == 2)
    assert not one_lot.economic_order_pass
    assert not one_lot.executable
    assert "minimum_economic_notional" in one_lot.economic_order_reason
    assert two_lot.economic_order_pass
    assert two_lot.executable
    assert two_lot.downside_cvar_amount == 240.0
    assert two_lot.proposal_id in decision.plan.selected_proposal_ids
    print("[PASS] SCAP economic-order and lifecycle-cost contract")


if __name__ == "__main__":
    main()
