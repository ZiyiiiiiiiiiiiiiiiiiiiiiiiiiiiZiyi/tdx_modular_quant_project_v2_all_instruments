from __future__ import annotations

import pandas as pd

from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.multi_horizon_value import attach_multi_horizon_value_contract
from functions.decision_council.policy import RulesBasedPresidentPolicy


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    candidates = pd.DataFrame([
        {"symbol": "sh600000", "volatility_20": 0.02, "alpha_score": 0.2, "alpha_percentile": 0.2,
         "primary_score": 0.2, "candidate_rank": 100, "expected_edge_10d": 0.001,
         "conservative_expected_edge_10d": -0.005, "entry_confirmed": False,
         "state_machine_role_pass": True, "mainline_v3_lot_feasible": True,
         "mainline_v3_one_lot_weight": 0.05, "strategy_logic_version": "mainline_v3_cabinet_native"},
        {"symbol": "sz000001", "volatility_20": 0.02, "alpha_score": 0.9, "alpha_percentile": 0.9,
         "primary_score": 0.9, "candidate_rank": 1, "expected_edge_10d": 0.030,
         "conservative_expected_edge_10d": 0.020, "entry_confirmed": True,
         "state_machine_role_pass": True, "mainline_v3_lot_feasible": True,
         "mainline_v3_one_lot_weight": 0.06, "entry_size_tier": "starter_1_lot",
         "candidate_state": "entry_selected", "strategy_logic_version": "mainline_v3_cabinet_native"},
    ])
    candidates = attach_multi_horizon_value_contract(candidates)
    safety = SafetyDecision(pd.Timestamp("2024-01-10"), "normal", 1.0, None, 0.0, "sh510300", "strict")
    context = DecisionContext(
        decision_id="replacement_test",
        decision_date=pd.Timestamp("2024-01-10"),
        candidates=candidates,
        current_weights={"sh600000": 0.20},
        holding_days={"sh600000": 10},
        pending_locked_symbols=frozenset(),
        safety=safety,
        top_n=1,
        entry_rank_limit=20,
        hold_rank_limit=100,
        minimum_holding_days=5,
        turnover_budget=0.01,
        partial_adjustment_rate=0.25,
    )
    _, orders, diagnostics = RulesBasedPresidentPolicy().decide(context)
    sell = orders[orders["reason"].eq("replacement_opportunity_exit")]
    buy = orders[orders["reason"].eq("replacement_opportunity_buy")]
    expect(len(sell) == 1 and len(buy) == 1, "active replacement emits both paired legs")
    expect(abs(float(sell.iloc[0]["delta_weight"]) + 0.20) < 1e-12,
           "replacement sells the full small-account holding instead of a fractional stub")
    expect(str(sell.iloc[0]["replacement_pair_id"]) == str(buy.iloc[0]["replacement_pair_id"]),
           "sell and buy legs share a durable pair identifier")
    expect(float(sell.iloc[0]["replacement_lcb_net_edge"]) > 0.0,
           "order ledger preserves the cost-after-return lower bound")
    expect(int(diagnostics["active_replacement_pair_count"]) == 1,
           "policy diagnostics count active replacement pairs")
    disabled_context = DecisionContext(
        decision_id="replacement_disabled_test",
        decision_date=pd.Timestamp("2024-01-10"),
        candidates=candidates,
        current_weights={"sh600000": 0.20},
        holding_days={"sh600000": 10},
        pending_locked_symbols=frozenset(),
        safety=safety,
        top_n=1,
        entry_rank_limit=20,
        hold_rank_limit=100,
        minimum_holding_days=5,
        active_replacement_enabled=False,
    )
    _, disabled_orders, disabled_diagnostics = RulesBasedPresidentPolicy().decide(disabled_context)
    expect(
        not disabled_orders["reason"].isin(
            {"replacement_opportunity_exit", "replacement_opportunity_buy"}
        ).any(),
        "a capital profile can fail active replacement closed without disabling other policy actions",
    )
    expect(
        disabled_diagnostics["active_replacement_enabled"] is False,
        "replacement enablement is explicit in policy diagnostics",
    )
    print("[PASS] active replacement policy integration verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
