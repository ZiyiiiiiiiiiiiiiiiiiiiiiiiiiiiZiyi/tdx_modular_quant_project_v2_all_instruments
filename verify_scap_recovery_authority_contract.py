"""Verify exposure bands and recovery authority are independent of rebalance."""
from types import SimpleNamespace

import pandas as pd

from functions.decision_council.execution_runtime import is_monthly_normal_buy
from functions.decision_council.exposure_catchup import decide_exposure_catchup
from functions.decision_council.exposure_contract import resolve_strategic_exposure_band
from functions.decision_council.integer_action_optimizer import optimize_action_proposals
from functions.decision_council.pending_orders import (
    PENDING_ORDER_COLUMNS,
    build_pending_order_snapshot,
)
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.scap_v2_contracts import ActionProposal, ExposureAuthorization


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def make_proposal(symbol, robust):
    return ActionProposal(
        proposal_id=f"d|{symbol}", decision_id="d", symbol=symbol,
        action_type="new_entry", source_module="verify", requested_lots=1,
        baseline_action="hold_cash", horizon_sessions=10,
        expected_net_profit_amount=robust + 5.0,
        robust_net_profit_amount=robust, downside_cvar_amount=20.0,
        exact_cost_amount=5.0, funding_cash_amount=2005.0,
        buy_cash_required_amount=2005.0, market_notional_amount=2000.0,
        exposure_delta=0.10, decision_return_basis="lcb",
    )


def main():
    neutral = resolve_strategic_exposure_band(
        risk_level="normal", structural_regime_level="unknown", safety_exposure_cap=1.0
    )
    check("unknown regime fails neutral", (neutral.target, neutral.lower_bound, neutral.upper_bound, neutral.hard_ceiling) == (0.75, 0.60, 0.85, 0.90))
    weak = resolve_strategic_exposure_band(
        risk_level="warning", structural_regime_level="weak", safety_exposure_cap=1.0
    )
    check("weak band is bounded", (weak.target, weak.lower_bound, weak.hard_ceiling) == (0.55, 0.40, 0.70))
    high = resolve_strategic_exposure_band(
        risk_level="high", structural_regime_level="bear", safety_exposure_cap=1.0
    )
    check("high risk has no forced lower exposure", high.lower_bound == 0.0 and high.hard_ceiling == 0.35)

    recovery = decide_exposure_catchup(
        actual_exposure=0.40, target_exposure=0.75, strategic_lower_bound=0.60,
        risk_level="normal", structural_regime_level="neutral",
        market_liquidity_stress_ratio=0.0, qualified_entry_count=2,
        transition_only=False, risk_contribution_gate_pass=False,
        hard_risk_gate_enabled=True, recovery_daily_exposure_cap=0.15,
    )
    check("research gate cannot veto recovery", recovery.catchup_allowed)
    check("research failure remains visible", "diagnostic_only" in recovery.research_gate_warning)
    check("recovery is capped at 15 percent NAV", abs(recovery.catchup_buy_budget - 0.15) < 1e-12)
    check("recovery is limited to one new name", recovery.recovery_max_new_names == 1)

    no_candidate = decide_exposure_catchup(
        actual_exposure=0.40, target_exposure=0.75, strategic_lower_bound=0.60,
        risk_level="normal", structural_regime_level="neutral",
        market_liquidity_stress_ratio=0.0, qualified_entry_count=0,
        transition_only=False,
    )
    check("cash is allowed when no candidate exists", not no_candidate.catchup_allowed)
    check("no candidate does not erase exposure gap", abs(no_candidate.exposure_gap - 0.20) < 1e-12)

    authorization = ExposureAuthorization(
        decision_id="d", nav_amount=20_000.0, risk_exposure_ceiling=0.90,
        cash_buffer_amount=1_000.0, per_name_structural_cap=0.40,
        per_name_stress_budget_amount=2_000.0,
        portfolio_stress_budget_amount=5_000.0, new_entry_allowed=True,
        add_allowed=False, replacement_allowed=False,
        current_cash_amount=20_000.0, desired_exposure_target=0.75,
        effective_deployment_target=0.60,
    )
    plan = optimize_action_proposals(
        (make_proposal("000001", 20.0), make_proposal("000002", 19.0)),
        authorization=authorization, current_lots_by_symbol={},
        current_weights_by_symbol={}, current_exposure=0.40, max_positions=5,
        max_new_buy_names=1, max_incremental_buy_exposure=0.15,
    )
    check("recovery optimizer selects at most one new name", len(plan.selected_proposal_ids) == 1)
    check("recovery optimizer respects daily exposure cap", plan.projected_exposure <= 0.55 + 1e-12)

    catchup_context = SimpleNamespace(
        decision_id="d", decision_date=pd.Timestamp("2025-02-06"),
        catchup_allowed=True, allow_normal_rebalance=False,
    )
    catchup_order = RulesBasedPresidentPolicy._order_row(
        catchup_context, "000001", 0.0, 0.10, "normal_buy"
    )
    check("non-monthly recovery order has an explicit reason", catchup_order["reason"] == "exposure_catchup_buy")
    check(
        "recovery order never inherits the monthly pending window",
        not is_monthly_normal_buy(
            side="buy", order_reason=catchup_order["reason"],
            rebalance_frequency="monthly",
        ),
    )
    check(
        "ordinary monthly buy retains the monthly pending window",
        is_monthly_normal_buy(
            side="buy", order_reason="normal_buy", rebalance_frequency="monthly"
        ),
    )
    pending_row = {column: pd.NA for column in PENDING_ORDER_COLUMNS}
    pending_row.update(
        {
            "decision_id": "d", "symbol": "000001", "side": "buy",
            "reason": "exposure_catchup_buy", "status": "pending",
        }
    )
    terminal_snapshot = build_pending_order_snapshot(
        pd.DataFrame([pending_row]), snapshot_date="2025-02-06"
    )
    check(
        "final-day recovery order is included in the terminal snapshot",
        len(terminal_snapshot) == 1
        and terminal_snapshot.iloc[0]["event_type"] == "terminal_state_snapshot"
        and str(terminal_snapshot.iloc[0]["snapshot_date"].date()) == "2025-02-06",
    )


if __name__ == "__main__":
    main()
